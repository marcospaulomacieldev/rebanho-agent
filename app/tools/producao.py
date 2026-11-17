"""Ferramentas de produção de leite do agente. Todas somente leitura."""

import sqlite3
from datetime import date
from typing import Any

from app.db.producao import animal_existe, producao_no_periodo
from app.tools.erros import ErroDeFerramenta
from app.tools.periodo import resolver_periodo
from app.tools.validacao import como_inteiro


def _resultado_vazio(inicio: str | None, fim: str | None) -> dict[str, Any]:
    """Sem nenhum registro: nulo (e não zero) nos litros, porque zero seria uma medição."""
    return {
        "litros_total": None,
        "litros_manha_total": None,
        "litros_tarde_total": None,
        "litros_media_dia": None,
        "dias_com_registro": 0,
        "data_inicio": inicio,
        "data_fim": fim,
    }


def producao_por_periodo(
    conn: sqlite3.Connection,
    dias: int | None = None,
    data_inicio: str | None = None,
    data_fim: str | None = None,
    animal_id: int | None = None,
    *,
    data_referencia: date | None = None,
) -> dict[str, Any]:
    """Produção de leite (manhã e tarde, em litros) de um período.

    O período é dado de UM destes jeitos (ADR 0005): `dias` (os últimos N dias, de 1 a 90,
    terminando na data de referência, inclusive) ou `data_inicio` e `data_fim` (AAAA-MM-DD,
    inclusive; um dia = as duas iguais). Sem `animal_id`, soma o rebanho inteiro (inclusive
    animais que saíram dentro do período). A data de referência é a maior data com produção
    no banco (ADR 0003); o parâmetro `data_referencia` existe só para testes e não aparece no
    esquema mostrado ao modelo.

    Retorna `litros_total`, `litros_manha_total`, `litros_tarde_total` (1 casa decimal),
    `litros_media_dia` (2 casas), `dias_com_registro`, `data_inicio` e `data_fim`. Para um
    animal, a média é `litros_total / dias_com_registro`; para o rebanho, é a média dos
    totais diários. Sem nenhum registro no período, os litros e a média vêm nulos e
    `dias_com_registro` é 0 ("sem registro", e não zero litros).

    `animal_id` nulo equivale a omitido (rebanho inteiro). Levanta ErroDeFerramenta (um
    ValueError) se os argumentos de período forem inválidos (ver `resolver_periodo`), se
    `animal_id` não for inteiro (ou for grande demais para o SQLite) ou se o animal não existir.
    """
    periodo = resolver_periodo(conn, dias, data_inicio, data_fim, data_referencia=data_referencia)
    if animal_id is not None:
        animal_id = como_inteiro(animal_id, "animal_id")
        if not animal_existe(conn, animal_id):
            raise ErroDeFerramenta(f"Não existe animal com id {animal_id}.")
    if periodo is None:  # banco sem nenhuma produção: não há data de referência
        return _resultado_vazio(None, None)

    inicio, fim = periodo.data_inicio.isoformat(), periodo.data_fim.isoformat()
    agregada = producao_no_periodo(conn, inicio, fim, animal_id)
    if agregada.dias_com_registro == 0:
        return _resultado_vazio(inicio, fim)
    return {
        "litros_total": round(agregada.litros_total, 1),
        "litros_manha_total": round(agregada.litros_manha, 1),
        "litros_tarde_total": round(agregada.litros_tarde, 1),
        "litros_media_dia": round(agregada.litros_total / agregada.dias_com_registro, 2),
        "dias_com_registro": agregada.dias_com_registro,
        "data_inicio": inicio,
        "data_fim": fim,
    }
