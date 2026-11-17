"""Fidelidade numérica: todo número de litros da resposta tem de vir de uma ferramenta (ADR 0008).

Estas funções são usadas em dois lugares: na trava do laço do agente (`app/agente.py`), que
impede a entrega de litros inventados, e nas evals (`evals/checagens.py`), que medem a mesma
coisa. Uma definição só, para as duas nunca divergirem. Nenhum LLM é usado aqui.
"""

import re
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation

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


def litros_sem_origem(
    texto: str, resultados: Sequence[object], pergunta: str = ""
) -> list[set[Decimal]]:
    """Os números de litros do texto que não vieram de nenhuma ferramenta.

    Lista vazia quer dizer que a resposta é fiel. Uma quantidade de litros que a própria pessoa
    escreveu na `pergunta` também é aceita: repetir "menos de 10 litros" não é inventar um dado.
    Só valem os números colados a "litros" na pergunta: o "7" de "últimos 7 dias" não autoriza
    a resposta a dizer "7 litros".
    """
    aceitos = litros_dos_resultados(resultados) | {
        valor for candidatos in litros_do_texto(pergunta) for valor in candidatos
    }
    return [candidatos for candidatos in litros_do_texto(texto) if not candidatos & aceitos]
