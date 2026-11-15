"""Consultas de produção de leite. Somente SELECT, sempre com parâmetros vinculados (`?`).

Este é o único lugar das ferramentas de produção onde existe SQL (regra do projeto).
Nenhum texto vindo do modelo é colocado dentro do SQL: ele só entra como parâmetro.
"""

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class ProducaoAgregada:
    """Soma de litros (manhã + tarde) e quantidade de dias distintos com registro."""

    litros_total: float
    dias_com_registro: int


def data_de_referencia(conn: sqlite3.Connection) -> str | None:
    """Maior data com produção registrada (a "hoje" das consultas, ADR 0003), ou None."""
    return conn.execute("SELECT MAX(data) FROM producao_leite").fetchone()[0]


def animal_existe(conn: sqlite3.Connection, animal_id: int) -> bool:
    """Verdadeiro se existe um animal com esse id, ativo ou não."""
    return conn.execute("SELECT 1 FROM animais WHERE id = ?", (animal_id,)).fetchone() is not None


def producao_no_periodo(
    conn: sqlite3.Connection,
    data_inicio: str,
    data_fim: str,
    animal_id: int | None = None,
) -> ProducaoAgregada:
    """Produção entre duas datas ISO (inclusive), de um animal ou do rebanho inteiro.

    Sem `animal_id`, soma todos os animais, inclusive os que saíram da fazenda (o leite
    foi produzido). Período sem registro devolve total 0 e 0 dias.
    """
    if animal_id is None:
        linha = conn.execute(
            "SELECT COALESCE(SUM(litros_manha + litros_tarde), 0.0), COUNT(DISTINCT data)"
            " FROM producao_leite WHERE data BETWEEN ? AND ?",
            (data_inicio, data_fim),
        ).fetchone()
    else:
        linha = conn.execute(
            "SELECT COALESCE(SUM(litros_manha + litros_tarde), 0.0), COUNT(DISTINCT data)"
            " FROM producao_leite WHERE animal_id = ? AND data BETWEEN ? AND ?",
            (animal_id, data_inicio, data_fim),
        ).fetchone()
    return ProducaoAgregada(litros_total=float(linha[0]), dias_com_registro=int(linha[1]))
