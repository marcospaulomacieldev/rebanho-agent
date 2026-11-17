"""Resolve o período de uma consulta de produção (ADR 0005).

As ferramentas de produção aceitam UM de dois modos, nunca os dois:
1. `dias`: os últimos N dias, terminando na data de referência (inclusive);
2. `data_inicio` e `data_fim`: um intervalo de datas (inclusive); um dia = as duas iguais.

A data de referência ("hoje") é a maior data com produção no banco (ADR 0003).
"""

import re
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

from app.db.producao import data_de_referencia, data_minima
from app.tools.erros import ErroDeFerramenta
from app.tools.validacao import como_inteiro

DIAS_MINIMO = 1
DIAS_MAXIMO = 90
# Estrito (date.fromisoformat aceita mais) e só com dígitos ASCII.
_FORMATO_DATA = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


@dataclass(frozen=True)
class Periodo:
    data_inicio: date
    data_fim: date


def _sem_vazio(valor: object) -> object:
    """Texto vazio num parâmetro opcional equivale a omitido (alguns modelos enviam "")."""
    if isinstance(valor, str) and not valor.strip():
        return None
    return valor


def _ler_data(valor: object, nome: str) -> date:
    texto = valor.strip() if isinstance(valor, str) else ""
    if not _FORMATO_DATA.fullmatch(texto):
        raise ErroDeFerramenta(
            f"`{nome}` deve ser uma data no formato AAAA-MM-DD, como 2026-10-21."
        )
    try:
        return date.fromisoformat(texto)
    except ValueError as erro:
        raise ErroDeFerramenta(
            f"`{nome}` ({texto}) não é uma data que existe no calendário."
        ) from erro


def resolver_periodo(
    conn: sqlite3.Connection,
    dias: object = None,
    data_inicio: object = None,
    data_fim: object = None,
    *,
    dias_padrao: int | None = None,
    data_referencia: date | None = None,
) -> Periodo | None:
    """Valida os argumentos de período e devolve as datas de início e fim.

    `dias_padrao` é usado quando nenhum modo é informado (por exemplo, 7 no resumo do
    rebanho). Devolve None se o banco não tem nenhuma produção (não há data de referência),
    depois de validar os argumentos. `data_referencia` existe só para testes.

    Levanta ErroDeFerramenta (mensagem em português, pensada para o modelo ler) se os modos
    forem misturados ou incompletos, se uma data for inválida, se `data_inicio` for depois
    de `data_fim`, se `data_fim` for depois do último dia com registro ou se o período
    estiver todo antes do primeiro registro. Período só parcialmente dentro do intervalo
    com registros é aceito.
    """
    dias, data_inicio, data_fim = _sem_vazio(dias), _sem_vazio(data_inicio), _sem_vazio(data_fim)
    tem_datas = data_inicio is not None or data_fim is not None

    if dias is not None and tem_datas:
        raise ErroDeFerramenta(
            "Use `dias` OU `data_inicio` e `data_fim`, nunca os dois ao mesmo tempo."
        )
    if tem_datas and (data_inicio is None or data_fim is None):
        raise ErroDeFerramenta(
            "Informe `data_inicio` e `data_fim` juntas. Para um dia só, use a mesma data nas duas."
        )
    if dias is None and not tem_datas:
        if dias_padrao is None:
            raise ErroDeFerramenta(
                "Informe `dias` (de 1 a 90) ou `data_inicio` e `data_fim`."
            )
        dias = dias_padrao

    if dias is not None:
        quantidade = como_inteiro(dias, "dias")
        if not DIAS_MINIMO <= quantidade <= DIAS_MAXIMO:
            raise ErroDeFerramenta(f"`dias` deve estar entre {DIAS_MINIMO} e {DIAS_MAXIMO}.")
        inicio_pedido: date | None = None
        fim_pedido: date | None = None
    else:
        inicio_pedido = _ler_data(data_inicio, "data_inicio")
        fim_pedido = _ler_data(data_fim, "data_fim")
        if inicio_pedido > fim_pedido:
            raise ErroDeFerramenta("`data_inicio` não pode ser depois de `data_fim`.")

    if data_referencia is None:
        texto = data_de_referencia(conn)
        if texto is None:  # banco sem nenhuma produção
            return None
        data_referencia = date.fromisoformat(texto)

    if dias is not None:
        return Periodo(data_referencia - timedelta(days=quantidade - 1), data_referencia)

    assert inicio_pedido is not None and fim_pedido is not None
    primeiro = data_minima(conn)
    intervalo = (
        f" O banco tem registros de {primeiro} a {data_referencia.isoformat()}." if primeiro else ""
    )
    if fim_pedido > data_referencia:
        raise ErroDeFerramenta(
            f"A data final ({fim_pedido.isoformat()}) é depois do último dia com registro."
            f"{intervalo}"
        )
    if primeiro is not None and fim_pedido < date.fromisoformat(primeiro):
        raise ErroDeFerramenta(f"Não há registros nesse período.{intervalo}")
    return Periodo(inicio_pedido, fim_pedido)
