"""Conexões com o SQLite.

Há dois tipos de conexão, de propósito:
- somente leitura, usada pelas ferramentas do agente: o próprio SQLite recusa qualquer
  escrita, então "nenhuma operação de escrita é possível" vale por construção e não só por
  convenção;
- escrita, usada apenas pelo gerador de dados sintéticos.
"""

import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _configurar(conn: sqlite3.Connection) -> sqlite3.Connection:
    """Ajustes comuns: linhas acessíveis por nome de coluna e chaves estrangeiras ativas.

    O SQLite não verifica chaves estrangeiras por padrão; é preciso ligar a cada conexão.
    """
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def abrir_somente_leitura(caminho: Path | str) -> sqlite3.Connection:
    """Abre um banco existente em modo somente leitura.

    Levanta FileNotFoundError se o arquivo não existir (o modo somente leitura não cria
    arquivo). Qualquer INSERT, UPDATE, DELETE ou DROP nessa conexão levanta
    sqlite3.OperationalError.
    """
    arquivo = Path(caminho)
    if not arquivo.is_file():
        raise FileNotFoundError(f"Banco de dados não encontrado: {arquivo}")
    uri = arquivo.resolve().as_uri() + "?mode=ro"
    conn = _configurar(sqlite3.connect(uri, uri=True))
    # Segunda barreira, além do mode=ro: a conexão recusa qualquer comando de escrita.
    conn.execute("PRAGMA query_only = ON")
    return conn


def abrir_para_escrita(caminho: Path | str) -> sqlite3.Connection:
    """Abre (ou cria) um banco em modo escrita. Uso restrito ao gerador de dados."""
    arquivo = Path(caminho)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    return _configurar(sqlite3.connect(arquivo))


def criar_schema(conn: sqlite3.Connection) -> None:
    """Cria as tabelas e índices definidos em schema.sql."""
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def criar_banco_em_memoria() -> sqlite3.Connection:
    """Banco vazio em memória, já com o esquema. Útil em testes."""
    conn = _configurar(sqlite3.connect(":memory:"))
    criar_schema(conn)
    return conn
