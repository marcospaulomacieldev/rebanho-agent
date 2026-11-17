"""Consultas de animais. Somente SELECT, sempre com parâmetros vinculados (`?`).

Nenhum texto vindo do modelo é colocado dentro do SQL: ele só entra como parâmetro. A busca
por nome (sem acento e sem diferenciar maiúsculas) é feita em Python, na ferramenta, porque o
SQLite não ignora acentos.
"""

import sqlite3
from typing import Any

# Valores das listas fechadas do `schema.sql`. Um teste confere que continuam iguais.
STATUS_VALIDOS = ("lactacao", "seca", "novilha", "corte")
LOTES_VALIDOS = (
    "alta_producao",
    "media_producao",
    "pre_parto",
    "seca",
    "recria",
    "pasto",
    "confinamento_inicial",
    "confinamento_final",
)


def listar(
    conn: sqlite3.Connection,
    status: str | None,
    lote: str | None,
    incluir_inativos: bool,
) -> list[dict[str, Any]]:
    """Animais filtrados por status e lote (`None` = sem filtro). Só os ativos, a menos que
    `incluir_inativos` seja verdadeiro. Ordenados por id; quem chama ordena como precisar."""
    linhas = conn.execute(
        "SELECT id, nome, sexo, raca, data_nascimento, status, lote, ativo, data_saida,"
        " motivo_saida FROM animais"
        " WHERE (? IS NULL OR status = ?) AND (? IS NULL OR lote = ?) AND (? = 1 OR ativo = 1)"
        " ORDER BY id",
        (status, status, lote, lote, 1 if incluir_inativos else 0),
    ).fetchall()
    return [dict(linha) for linha in linhas]
