"""Executor das evals: roda o agente de verdade em cada caso e resume os resultados (ADR 0007)."""

import math
import sqlite3
import statistics
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any

from app.agente import responder
from app.db.connection import abrir_somente_leitura
from app.db.seed import gerar_banco
from app.llm.client import ErroDeConexao, ErroLLM
from app.tools.erros import ErroDeFerramenta
from app.tools.registro import executar_ferramenta
from evals.casos import Caso
from evals.checagens import aprovada, avaliar
from evals.cliente import ClienteComEspera, TetoDeChamadas

MAX_NAO_EXECUTADAS_SEGUIDAS = 3
AMOSTRA_PEQUENA = 30
# Métricas do resumo: nome -> checagem de onde ela sai.
METRICAS = (
    "ferramenta",
    "argumentos_equivalentes",
    "argumentos_identicos",
    "numeros",
    "fidelidade",
    "comportamento",
)


class Bancos:
    """Bancos sintéticos por semente, em arquivos temporários abertos em modo somente leitura
    (o mesmo tipo de conexão que o agente usa de verdade)."""

    def __init__(self) -> None:
        self._pasta = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._abertos: dict[int, sqlite3.Connection] = {}

    def abrir(self, semente: int) -> sqlite3.Connection:
        if semente not in self._abertos:
            caminho = Path(self._pasta.name) / f"rebanho-{semente}.db"
            gerar_banco(caminho, semente)
            self._abertos[semente] = abrir_somente_leitura(caminho)
        return self._abertos[semente]

    def fechar(self) -> None:
        for conn in self._abertos.values():
            conn.close()
        self._abertos.clear()
        self._pasta.cleanup()

    def __enter__(self) -> "Bancos":
        return self

    def __exit__(
        self,
        tipo: type[BaseException] | None,
        erro: BaseException | None,
        rastro: TracebackType | None,
    ) -> None:
        self.fechar()


@dataclass(frozen=True)
class Execucao:
    """Uma pergunta feita ao agente uma vez."""

    caso_id: str
    variante: int  # posição da pergunta entre as variantes do caso (começa em 1)
    pergunta: str
    repeticao: int
    executada: bool  # falso = falha de infraestrutura; não conta como erro nem como acerto
    passou: bool | None
    checagens: dict[str, bool | None]
    chamadas: tuple[dict[str, Any], ...]
    resposta: str | None
    passos: int | None
    latencia_s: float | None  # tempo dentro do modelo, sem as esperas entre chamadas
    erro: str | None
    chamadas_a_mais: int | None = None  # chamadas além das esperadas, quando a sequência bateu
    # Textos que a trava do agente barrou por trazerem litros sem origem (ADR 0008), para saber
    # se foi invenção, arredondamento ou falso positivo.
    respostas_barradas: tuple[str, ...] = ()


def falha_de_infraestrutura(erro: ErroLLM) -> bool:
    """Verdadeiro se o erro não diz nada sobre o agente: rede fora do ar, chave recusada
    (401, 403), limite de uso (429) ou falha do servidor do provedor (5xx)."""
    codigo = erro.codigo
    return isinstance(erro, ErroDeConexao) or (
        codigo is not None and (codigo in (401, 403, 429) or codigo >= 500)
    )


@dataclass(frozen=True)
class Rodada:
    execucoes: tuple[Execucao, ...]
    interrompida: str | None  # motivo, se a rodada parou antes do fim


def resultados_das_chamadas_esperadas(conn: sqlite3.Connection, caso: Caso) -> list[dict[str, Any]]:
    """Executa as chamadas esperadas do caso no banco. Um erro previsto da ferramenta vira o
    mesmo `{"erro": ...}` que o agente receberia."""
    resultados: list[dict[str, Any]] = []
    for chamada in caso.chamadas_esperadas or ():
        try:
            resultados.append(executar_ferramenta(conn, chamada.ferramenta, chamada.argumentos))
        except ErroDeFerramenta as erro:
            resultados.append({"erro": str(erro)})
    return resultados


def executar(
    casos: Sequence[Caso],
    cliente: ClienteComEspera,
    bancos: Bancos,
    *,
    repeticoes: int = 3,
    ao_terminar: Callable[[Execucao], None] | None = None,
) -> Rodada:
    """Roda cada pergunta de cada caso `repeticoes` vezes com o agente real.

    Uma falha ao falar com o modelo marca a execução como não executada. Três seguidas, ou o
    teto de chamadas, encerram a rodada; o que já foi medido é devolvido.
    """
    if repeticoes < 1:
        raise ValueError("`repeticoes` deve ser pelo menos 1.")
    execucoes: list[Execucao] = []
    falhas_seguidas = 0
    for caso in casos:
        conn = bancos.abrir(caso.semente)
        esperados = resultados_das_chamadas_esperadas(conn, caso)
        for variante, pergunta in enumerate(caso.perguntas, start=1):
            for repeticao in range(1, repeticoes + 1):
                antes = cliente.tempo_no_modelo
                try:
                    resposta = responder(pergunta, conn, cliente)
                except TetoDeChamadas as erro:
                    return Rodada(tuple(execucoes), str(erro))
                except KeyboardInterrupt:
                    # Ctrl+C: devolve o que já foi medido, para o relatório parcial ser gravado.
                    return Rodada(tuple(execucoes), "Rodada interrompida pelo teclado (Ctrl+C).")
                except ErroLLM as erro:
                    infra = falha_de_infraestrutura(erro)
                    execucao = Execucao(
                        caso_id=caso.id,
                        variante=variante,
                        pergunta=pergunta,
                        repeticao=repeticao,
                        executada=not infra,
                        # Resposta vazia ou bloqueada é comportamento do modelo: conta como
                        # reprovação. Limite de uso, rede e chave ficam fora da conta.
                        passou=None if infra else False,
                        checagens={} if infra else dict.fromkeys(METRICAS),
                        chamadas=(),
                        resposta=None,
                        passos=None,
                        latencia_s=None,
                        erro=str(erro),
                    )
                    falhas_seguidas = falhas_seguidas + 1 if infra else 0
                else:
                    checagens = avaliar(caso, resposta, esperados, pergunta)
                    a_mais = (
                        len(resposta.chamadas) - len(caso.chamadas_esperadas)
                        if caso.chamadas_esperadas and checagens["ferramenta"]
                        else None
                    )
                    execucao = Execucao(
                        caso_id=caso.id,
                        variante=variante,
                        pergunta=pergunta,
                        repeticao=repeticao,
                        executada=True,
                        passou=aprovada(checagens, resposta.completa),
                        checagens=checagens,
                        chamadas=tuple(
                            {
                                "ferramenta": c.nome,
                                "argumentos": c.argumentos,
                                "resultado": c.resultado,
                                "erro": c.erro,
                            }
                            for c in resposta.chamadas
                        ),
                        resposta=resposta.texto,
                        passos=resposta.passos,
                        latencia_s=round(cliente.tempo_no_modelo - antes, 3),
                        erro=None,
                        chamadas_a_mais=a_mais,
                        respostas_barradas=resposta.barradas,
                    )
                    falhas_seguidas = 0
                execucoes.append(execucao)
                if ao_terminar is not None:
                    ao_terminar(execucao)
                if falhas_seguidas >= MAX_NAO_EXECUTADAS_SEGUIDAS:
                    motivo = (
                        f"{falhas_seguidas} execuções seguidas falharam ao falar com o modelo"
                        " (provável limite de uso)."
                    )
                    return Rodada(tuple(execucoes), motivo)
    return Rodada(tuple(execucoes), None)


def _taxa(acertos: int, total: int) -> dict[str, Any]:
    return {
        "acertos": acertos,
        "total": total,
        "taxa": round(acertos / total, 4) if total else None,
    }


def _percentil_90(valores: list[float]) -> float:
    ordenados = sorted(valores)
    return ordenados[math.ceil(0.9 * len(ordenados)) - 1]


def resumir(casos: Sequence[Caso], rodada: Rodada) -> dict[str, Any]:
    """Métricas da rodada. Só execuções válidas entram nos denominadores."""
    validas = [e for e in rodada.execucoes if e.executada]
    metricas: dict[str, Any] = {}
    for nome in METRICAS:
        definidas = [e.checagens[nome] for e in validas if e.checagens[nome] is not None]
        metricas[nome] = _taxa(sum(definidas), len(definidas))
    metricas["execucao_aprovada"] = _taxa(sum(bool(e.passou) for e in validas), len(validas))

    por_caso = []
    consistentes = com_variantes = 0
    for caso in casos:
        do_caso = [e for e in validas if e.caso_id == caso.id]
        if not do_caso:
            continue
        aprovadas = sum(bool(e.passou) for e in do_caso)
        por_caso.append(
            {
                "id": caso.id,
                "variantes": len(caso.perguntas),
                "aprovadas": aprovadas,
                "total": len(do_caso),
            }
        )
        # Só entra na consistência o caso em que todas as variantes foram de fato executadas.
        variantes_medidas = {e.variante for e in do_caso}
        if len(caso.perguntas) > 1 and len(variantes_medidas) == len(caso.perguntas):
            com_variantes += 1
            consistentes += aprovadas == len(do_caso)
    metricas["consistencia_entre_variantes"] = _taxa(consistentes, com_variantes)
    a_mais = [e.chamadas_a_mais for e in validas if e.chamadas_a_mais is not None]

    latencias = [e.latencia_s for e in validas if e.latencia_s is not None]
    passos = [e.passos for e in validas if e.passos is not None]
    return {
        "metricas": metricas,
        "casos": por_caso,
        "execucoes_validas": len(validas),
        "execucoes_nao_executadas": len(rodada.execucoes) - len(validas),
        "amostra_pequena": len(validas) < AMOSTRA_PEQUENA,
        "latencia_mediana_s": round(statistics.median(latencias), 3) if latencias else None,
        "latencia_p90_s": round(_percentil_90(latencias), 3) if latencias else None,
        "passos_medios": round(statistics.fmean(passos), 2) if passos else None,
        "chamadas_a_mais": sum(a_mais),
        # A fidelidade mede a resposta entregue, já depois da trava. Este número mostra quantas
        # execuções só ficaram fiéis porque a trava agiu: sem ele, a trava esconderia a falha.
        "execucoes_com_trava": sum(1 for e in validas if e.respostas_barradas),
        "esperado": {
            caso.id: [
                {"ferramenta": c.ferramenta, "argumentos": c.argumentos}
                for c in caso.chamadas_esperadas
            ]
            for caso in casos
            if caso.chamadas_esperadas is not None
        },
        "interrompida": rodada.interrompida,
    }
