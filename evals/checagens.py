"""Checagens determinísticas de uma execução do agente (ADR 0007). Nenhum LLM é usado aqui."""

import re
from collections.abc import Callable, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from app.agente import ChamadaExecutada, RespostaAgente
from app.tools.animais import normalizar
from evals.casos import Caso, Chamada

_NUMERO = r"\d[\d.,]*\d|\d"
_TOKEN = re.compile(_NUMERO)
_COM_LITROS = re.compile(rf"({_NUMERO})\s*(?:litros?|l)\b", re.IGNORECASE)
_MILHAR_COM_PONTO = re.compile(r"\d{1,3}(?:\.\d{3})+")
_DATA = re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b")


def interpretar_numero(token: str) -> set[Decimal]:
    """Valores possíveis de um número escrito em texto.

    Aceita o formato brasileiro (`4.479,1`, `18,8`) e o de ponto decimal (`4479.1`). Quando o
    texto é ambíguo (`4.479` pode ser quatro mil ou quatro vírgula quatro), devolve os dois.
    """
    candidatos: list[str] = []
    tem_ponto, tem_virgula = "." in token, "," in token
    if tem_ponto and tem_virgula:
        if token.rfind(",") > token.rfind("."):  # 4.479,1
            candidatos.append(token.replace(".", "").replace(",", "."))
        else:  # 4,479.1
            candidatos.append(token.replace(",", ""))
    elif tem_virgula:
        candidatos.append(
            token.replace(",", ".") if token.count(",") == 1 else token.replace(",", "")
        )
    elif tem_ponto:
        if _MILHAR_COM_PONTO.fullmatch(token):
            candidatos.append(token.replace(".", ""))
        if token.count(".") == 1:
            candidatos.append(token)
    else:
        candidatos.append(token)
    valores: set[Decimal] = set()
    for candidato in candidatos:
        try:
            valores.add(Decimal(candidato))
        except InvalidOperation:
            pass
    return valores


def numeros_do_texto(texto: str) -> set[Decimal]:
    """Os números que aparecem no texto (em qualquer interpretação), fora os de datas.

    Datas como `17/11/2026` são retiradas antes: sem isso, o "17" da data poderia passar
    por um valor esperado de 17 litros.
    """
    valores: set[Decimal] = set()
    for token in _TOKEN.findall(_DATA.sub(" ", texto)):
        valores |= interpretar_numero(token)
    return valores


def litros_do_texto(texto: str) -> list[set[Decimal]]:
    """Números seguidos de "litro(s)" ou "L": uma entrada por número, com suas interpretações.

    Limite conhecido: só vê o número colado à unidade. "4 mil litros" e "litros: 18,8" escapam.
    """
    return [interpretar_numero(token) for token in _COM_LITROS.findall(texto)]


def litros_dos_resultados(resultados: Sequence[object]) -> set[Decimal]:
    """Valores numéricos dos campos `litros_*` de resultados de ferramentas (em qualquer nível)."""
    valores: set[Decimal] = set()

    def visitar(item: object) -> None:
        if isinstance(item, dict):
            for chave, valor in item.items():
                numero = isinstance(valor, int | float) and not isinstance(valor, bool)
                if isinstance(chave, str) and chave.startswith("litros") and numero:
                    valores.add(Decimal(str(valor)))
                else:
                    visitar(valor)
        elif isinstance(item, list | tuple):
            for valor in item:
                visitar(valor)

    visitar(list(resultados))
    return valores


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
    caso: Caso, resposta: RespostaAgente, resultados_esperados: Sequence[dict[str, Any]]
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
    das_ferramentas = litros_dos_resultados([c.resultado for c in feitas])
    fidelidade = all(candidatos & das_ferramentas for candidatos in com_litros)

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
