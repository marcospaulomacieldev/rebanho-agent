"""Consultas de produção de leite. Somente SELECT, sempre com parâmetros vinculados (`?`).

Este é o único lugar das ferramentas de produção onde existe SQL (regra do projeto).
Nenhum texto vindo do modelo é colocado dentro do SQL: ele só entra como parâmetro.
"""

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class ProducaoAgregada:
    """Soma de litros de cada turno e quantidade de dias distintos com registro."""

    litros_manha: float
    litros_tarde: float
    dias_com_registro: int

    @property
    def litros_total(self) -> float:
        return self.litros_manha + self.litros_tarde


def data_de_referencia(conn: sqlite3.Connection) -> str | None:
    """Maior data com produção registrada (a "hoje" das consultas, ADR 0003), ou None."""
    return conn.execute("SELECT MAX(data) FROM producao_leite").fetchone()[0]


def data_minima(conn: sqlite3.Connection) -> str | None:
    """Menor data com produção registrada, ou None se não houver nenhuma."""
    return conn.execute("SELECT MIN(data) FROM producao_leite").fetchone()[0]


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
    foi produzido). Período sem registro devolve somas 0 e 0 dias; quem chama decide como
    apresentar isso ("sem registro", e não zero litros).
    """
    if animal_id is None:
        linha = conn.execute(
            "SELECT COALESCE(SUM(litros_manha), 0.0), COALESCE(SUM(litros_tarde), 0.0),"
            " COUNT(DISTINCT data) FROM producao_leite WHERE data BETWEEN ? AND ?",
            (data_inicio, data_fim),
        ).fetchone()
    else:
        linha = conn.execute(
            "SELECT COALESCE(SUM(litros_manha), 0.0), COALESCE(SUM(litros_tarde), 0.0),"
            " COUNT(DISTINCT data) FROM producao_leite"
            " WHERE animal_id = ? AND data BETWEEN ? AND ?",
            (animal_id, data_inicio, data_fim),
        ).fetchone()
    return ProducaoAgregada(
        litros_manha=float(linha[0]),
        litros_tarde=float(linha[1]),
        dias_com_registro=int(linha[2]),
    )
