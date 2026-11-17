"""Laço do agente: pergunta -> modelo -> ferramentas -> resposta.

O modelo nunca toca no banco. Ele só *pede* uma ferramenta pelo nome; quem executa é este
código, pelo registro e com a conexão somente leitura que recebe. O resultado volta ao modelo
como dado, e o modelo redige a resposta final (ADR 0001).
"""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from app.db.producao import data_de_referencia, data_minima
from app.fidelidade import litros_sem_origem
from app.llm.client import (
    ChamadaFerramenta,
    ClienteLLM,
    Mensagem,
    ResultadoFerramenta,
)
from app.tools.erros import ErroDeFerramenta
from app.tools.registro import declaracoes_neutras, executar_ferramenta

logger = logging.getLogger(__name__)

PASTA_PROMPTS = Path(__file__).resolve().parents[1] / "prompts"
DIAS_DA_SEMANA = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)
MAX_PASSOS = 5
MAX_CHAMADAS_POR_PASSO = 10
MAX_CARACTERES_PERGUNTA = 1000
ERRO_CHAMADAS_DEMAIS = (
    f"Limite de {MAX_CHAMADAS_POR_PASSO} chamadas de uma vez. Faça as outras em uma próxima rodada."
)
MENSAGEM_SEM_RESPOSTA = "Não consegui chegar a uma resposta. Pode perguntar de outro jeito?"
ERRO_INTERNO = "Erro interno ao consultar os dados."
MAX_CORRECOES = 1
MENSAGEM_SEM_CONFIRMACAO = (
    "Não consegui confirmar esses números nos dados da fazenda, então prefiro não informar. "
    "Pode perguntar de novo?"
)


@dataclass(frozen=True)
class ChamadaExecutada:
    """Registro de uma ferramenta executada, útil para depurar e para as evals."""

    nome: str
    argumentos: dict[str, Any]
    resultado: dict[str, Any]
    erro: bool


@dataclass(frozen=True)
class RespostaAgente:
    texto: str
    chamadas: tuple[ChamadaExecutada, ...]
    passos: int
    completa: bool  # falso se o limite de passos acabou ou o modelo não escreveu resposta
    # Textos que a trava não entregou por trazerem litros sem origem (ADR 0008). Ficam aqui
    # para as evals mostrarem o que foi barrado: invenção, arredondamento ou falso positivo.
    barradas: tuple[str, ...] = ()


def carregar_prompt(nome: str = "sistema") -> str:
    """Lê um prompt de `prompts/<nome>.md` (os prompts nunca ficam embutidos no código).

    Devolve o modelo do prompt, com os marcadores `{{...}}` ainda por preencher. Para o
    texto final, que leva as datas do banco, use `montar_prompt`.
    """
    return (PASTA_PROMPTS / f"{nome}.md").read_text(encoding="utf-8")


def _dia_e_data(texto: str | None) -> tuple[str, str, str]:
    """(AAAA-MM-DD, dia/mês/ano, dia da semana) de uma data ISO; "sem registros" se nula."""
    if texto is None:
        return ("sem registros",) * 3
    data = date.fromisoformat(texto)
    return texto, data.strftime("%d/%m/%Y"), DIAS_DA_SEMANA[data.weekday()]


def _dia_anterior(texto: str | None, dias: int) -> tuple[str, str]:
    """(AAAA-MM-DD, dia/mês/ano) de `dias` antes de uma data ISO; "sem registros" se nula."""
    if texto is None:
        return ("sem registros",) * 2
    data = date.fromisoformat(texto) - timedelta(days=dias)
    return data.isoformat(), data.strftime("%d/%m/%Y")


def montar_prompt(conn: sqlite3.Connection, nome: str = "sistema") -> str:
    """Prompt final: o modelo de `prompts/<nome>.md` com as datas dos dados preenchidas.

    Os únicos valores que entram no texto são datas lidas do banco (a data de referência, o
    dia mais recente com registro, e o primeiro dia). Nada digitado pelo usuário nem devolvido
    por ferramenta é colocado no prompt de sistema (ADR 0005).
    """
    referencia = data_de_referencia(conn)  # ISO, ou None se não há produção
    ultimo, ultimo_br, dia_da_semana = _dia_e_data(referencia)
    _, primeiro_br, _ = _dia_e_data(data_minima(conn))
    # "Ontem" e "anteontem" já vão calculados: numa rodada das evals de 2026-11-17 o modelo
    # fez a conta e consultou o dia errado para "ontem" (devlog, "Rodada do nome exato").
    ontem, ontem_br = _dia_anterior(referencia, 1)
    anteontem, anteontem_br = _dia_anterior(referencia, 2)
    valores = {
        "ontem": ontem,
        "ontem_br": ontem_br,
        "anteontem": anteontem,
        "anteontem_br": anteontem_br,
        "ultimo_dia": ultimo,
        "ultimo_dia_br": ultimo_br,
        "dia_da_semana": dia_da_semana,
        "primeiro_dia_br": primeiro_br,
    }
    texto = carregar_prompt(nome)
    for chave, valor in valores.items():
        texto = texto.replace("{{" + chave + "}}", valor)
    return texto


def _executar(conn: sqlite3.Connection, chamada: ChamadaFerramenta) -> tuple[dict[str, Any], bool]:
    """Executa uma chamada do modelo. Devolve (resultado, houve_erro). Nunca levanta."""
    try:
        return executar_ferramenta(conn, chamada.nome, chamada.argumentos), False
    except ErroDeFerramenta as erro:  # erro previsto: a mensagem é escrita para o modelo ler
        return {"erro": str(erro)}, True
    except Exception:  # qualquer outro erro (até ValueError de biblioteca): só vai para o log
        logger.exception("Falha inesperada na ferramenta %s", chamada.nome)
        return {"erro": ERRO_INTERNO}, True


def responder(
    pergunta: str,
    conn: sqlite3.Connection,
    cliente: ClienteLLM,
    *,
    prompt: str | None = None,
    max_passos: int = MAX_PASSOS,
) -> RespostaAgente:
    """Responde a uma pergunta em linguagem natural usando as ferramentas.

    `conn` deve ser a conexão somente leitura (`abrir_somente_leitura`); o laço não confere
    isso, e é essa conexão que garante que nada seja escrito. Levanta ValueError se a pergunta
    for vazia ou longa demais, e ErroLLM (do cliente) se o modelo falhar. Em cada passo, só as
    primeiras `MAX_CHAMADAS_POR_PASSO` chamadas pedidas pelo modelo são executadas.

    Trava de fidelidade (ADR 0008): uma resposta com um número de litros que não veio de
    nenhuma ferramenta desta pergunta não é entregue. Na primeira vez, o modelo recebe um
    pedido de correção (`prompts/correcao_litros.md`) e tenta de novo; se insistir, a pessoa
    recebe `MENSAGEM_SEM_CONFIRMACAO`, sem números, e `completa` fica falso.
    """
    pergunta = pergunta.strip()
    if not pergunta:
        raise ValueError("A pergunta está vazia.")
    if len(pergunta) > MAX_CARACTERES_PERGUNTA:
        raise ValueError(f"A pergunta é longa demais (máximo de {MAX_CARACTERES_PERGUNTA} letras).")

    instrucoes = prompt if prompt is not None else montar_prompt(conn)
    ferramentas = declaracoes_neutras()
    mensagens = [Mensagem(papel="usuario", texto=pergunta)]
    executadas: list[ChamadaExecutada] = []
    barradas: list[str] = []

    for passo in range(1, max_passos + 1):
        resposta = cliente.gerar(instrucoes, mensagens, ferramentas)
        mensagens.append(
            Mensagem(
                papel="modelo",
                texto=resposta.texto,
                chamadas=resposta.chamadas,
                bruto=resposta.bruto,
            )
        )
        if not resposta.chamadas:
            texto = (resposta.texto or "").strip()
            if litros_sem_origem(texto, [c.resultado for c in executadas], pergunta):
                logger.warning("Resposta com litros que não vieram de ferramenta (passo %d)", passo)
                barradas.append(texto)
                if len(barradas) > MAX_CORRECOES:
                    return RespostaAgente(
                        texto=MENSAGEM_SEM_CONFIRMACAO,
                        chamadas=tuple(executadas),
                        passos=passo,
                        completa=False,
                        barradas=tuple(barradas),
                    )
                mensagens.append(
                    Mensagem(papel="usuario", texto=carregar_prompt("correcao_litros"))
                )
                continue
            return RespostaAgente(
                texto=texto or MENSAGEM_SEM_RESPOSTA,
                chamadas=tuple(executadas),
                passos=passo,
                completa=bool(texto),
                barradas=tuple(barradas),
            )

        resultados = []
        for indice, chamada in enumerate(resposta.chamadas):
            if indice >= MAX_CHAMADAS_POR_PASSO:
                # O provedor exige uma resposta para cada chamada pedida; as extras recebem erro.
                conteudo, houve_erro = {"erro": ERRO_CHAMADAS_DEMAIS}, True
            else:
                conteudo, houve_erro = _executar(conn, chamada)
            executadas.append(
                ChamadaExecutada(chamada.nome, chamada.argumentos, conteudo, houve_erro)
            )
            resultados.append(ResultadoFerramenta(chamada.nome, conteudo))
        mensagens.append(Mensagem(papel="ferramenta", resultados=tuple(resultados)))

    return RespostaAgente(
        texto=MENSAGEM_SEM_RESPOSTA,
        chamadas=tuple(executadas),
        passos=max_passos,
        completa=False,
        barradas=tuple(barradas),
    )
