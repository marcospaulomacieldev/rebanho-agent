"""Checagens determinísticas de uma execução do agente (ADR 0007). Nenhum LLM é usado aqui."""

from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Any

from app.agente import ChamadaExecutada, RespostaAgente
from app.fidelidade import (  # as definições ficam em app/, que também as usa na trava
    litros_do_texto,
    litros_sem_origem,
    numeros_do_texto,
)
from app.tools.animais import normalizar
from evals.casos import Caso, Chamada


def normalizar_argumentos(argumentos: dict[str, Any]) -> dict[str, Any]:
    """Forma canônica dos argumentos: nulo, texto vazio e falso valem como omitidos; `7.0`
    vira `7`; textos perdem espaços e maiúsculas, e `nome` perde também os acentos."""
    normal: dict[str, Any] = {}
    for chave, valor in argumentos.items():
        if valor is None or valor is False or (isinstance(valor, str) and not valor.strip()):
            continue
        if isinstance(valor, float) and valor.is_integer():
            valor = int(valor)
        elif isinstance(valor, str):
            valor = normalizar(valor) if chave == "nome" else valor.strip().lower()
        normal[chave] = valor
    return normal


def _em_ordem(
    esperadas: Sequence[Chamada],
    feitas: Sequence[ChamadaExecutada],
    combina: Callable[[int, ChamadaExecutada], bool],
) -> bool:
    """As chamadas esperadas aparecem, na ordem, entre as feitas (pode haver outras no meio)."""
    proxima = 0
    for feita in feitas:
        if proxima < len(esperadas) and combina(proxima, feita):
            proxima += 1
    return proxima == len(esperadas)


def _contem(texto_normal: str, trecho: str) -> bool:
    return normalizar(trecho) in texto_normal


def avaliar(
    caso: Caso,
    resposta: RespostaAgente,
    resultados_esperados: Sequence[dict[str, Any]],
    pergunta: str = "",
) -> dict[str, bool | None]:
    """Aplica as checagens do caso a uma resposta do agente.

    `resultados_esperados` são os resultados das chamadas esperadas, executadas no mesmo
    banco (para a equivalência por resultado). Cada checagem devolve verdadeiro, falso ou
    None (o caso não define aquele critério).
    """
    feitas = resposta.chamadas
    esperadas = caso.chamadas_esperadas
    ferramenta: bool | None = None
    identicos: bool | None = None
    equivalentes: bool | None = None
    if esperadas is not None and not esperadas:
        ferramenta = not feitas  # o agente não devia chamar nada
    elif esperadas:

        def mesmo_nome(i: int, feita: ChamadaExecutada) -> bool:
            return feita.nome == esperadas[i].ferramenta

        def identica(i: int, feita: ChamadaExecutada) -> bool:
            return mesmo_nome(i, feita) and normalizar_argumentos(
                feita.argumentos
            ) == normalizar_argumentos(esperadas[i].argumentos)

        def equivalente(i: int, feita: ChamadaExecutada) -> bool:
            return identica(i, feita) or (
                mesmo_nome(i, feita) and feita.resultado == resultados_esperados[i]
            )

        ferramenta = _em_ordem(esperadas, feitas, mesmo_nome)
        identicos = _em_ordem(esperadas, feitas, identica)
        equivalentes = _em_ordem(esperadas, feitas, equivalente)

    texto = resposta.texto
    numeros: bool | None = None
    if caso.numeros_na_resposta:
        no_texto = numeros_do_texto(texto)
        numeros = all(
            Decimal(str(caso.valor_esperado[campo])) in no_texto
            for campo in caso.numeros_na_resposta
        )

    com_litros = litros_do_texto(texto)
    # Mesma definição da trava do agente (ADR 0008). Todo texto barrado já tinha, no momento em
    # que foi escrito, litros sem origem nos resultados disponíveis até ali; por isso ele conta
    # como falha direto. Recalcular contra todos os resultados da execução esconderia uma
    # invenção que, por coincidência, batesse com um valor consultado depois da correção.
    fidelidade = not resposta.barradas and not litros_sem_origem(
        texto, [c.resultado for c in feitas], pergunta
    )

    partes: list[bool] = []
    texto_normal = normalizar(texto)
    if caso.chamadas_proibidas:
        partes.append(not any(c.nome in caso.chamadas_proibidas for c in feitas))
    partes.extend(
        any(_contem(texto_normal, alternativa) for alternativa in alternativas)
        for alternativas in caso.resposta_contem
    )
    partes.extend(not _contem(texto_normal, trecho) for trecho in caso.resposta_nao_contem)
    if caso.sem_litros_na_resposta:
        partes.append(not com_litros)
    comportamento = all(partes) if partes else None

    return {
        "ferramenta": ferramenta,
        "argumentos_identicos": identicos,
        "argumentos_equivalentes": equivalentes,
        "numeros": numeros,
        "fidelidade": fidelidade,
        "comportamento": comportamento,
    }


def aprovada(checagens: dict[str, bool | None], completa: bool) -> bool:
    """Passa se o agente concluiu a resposta e nenhum critério definido falhou.

    `argumentos_identicos` é só informativo: o que conta é `argumentos_equivalentes`.
    """
    exigidas = ("ferramenta", "argumentos_equivalentes", "numeros", "fidelidade", "comportamento")
    return completa and all(checagens[nome] is not False for nome in exigidas)
