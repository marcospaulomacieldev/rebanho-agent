"""Testes do esquema (regras no banco) e das conexões do SQLite."""

import sqlite3
from collections.abc import Iterator
from itertools import product
from pathlib import Path

import pytest

from app.db.connection import (
    abrir_para_escrita,
    abrir_somente_leitura,
    criar_banco_em_memoria,
    criar_schema,
)

STATUS = ["lactacao", "seca", "novilha", "corte"]
LOTES = [
    "alta_producao",
    "media_producao",
    "pre_parto",
    "seca",
    "recria",
    "pasto",
    "confinamento_inicial",
    "confinamento_final",
]
COMBINACOES_VALIDAS = {
    ("lactacao", "alta_producao"),
    ("lactacao", "media_producao"),
    ("seca", "pre_parto"),
    ("seca", "seca"),
    ("seca", "pasto"),
    ("novilha", "recria"),
    ("novilha", "pasto"),
    ("corte", "pasto"),
    ("corte", "confinamento_inicial"),
    ("corte", "confinamento_final"),
}


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    conexao = criar_banco_em_memoria()
    yield conexao
    conexao.close()


def _inserir(conn: sqlite3.Connection, tabela: str, valores: dict[str, object]) -> int:
    colunas = ", ".join(valores)
    marcas = ", ".join("?" for _ in valores)
    cursor = conn.execute(
        f"INSERT INTO {tabela} ({colunas}) VALUES ({marcas})", tuple(valores.values())
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def inserir_animal(conn: sqlite3.Connection, **campos: object) -> int:
    """Insere um animal válido (vaca em lactação) e permite sobrescrever campos."""
    valores: dict[str, object] = {
        "nome": "Mimosa",
        "sexo": "F",
        "raca": "holandesa",
        "data_nascimento": "2020-03-10",
        "status": "lactacao",
        "lote": "alta_producao",
        "ativo": 1,
        "data_saida": None,
        "motivo_saida": None,
    }
    valores.update(campos)
    return _inserir(conn, "animais", valores)


def inserir_producao(conn: sqlite3.Connection, animal_id: int, **campos: object) -> int:
    valores: dict[str, object] = {
        "animal_id": animal_id,
        "data": "2026-11-01",
        "litros_manha": 10.0,
        "litros_tarde": 8.0,
    }
    valores.update(campos)
    return _inserir(conn, "producao_leite", valores)


def inserir_condicoes(conn: sqlite3.Connection, **campos: object) -> int:
    valores: dict[str, object] = {
        "data": "2026-11-01",
        "hora_ordenha_manha": "05:30",
        "hora_ordenha_tarde": "15:30",
        "chuva_manha": 0,
        "chuva_tarde": 1,
        "temp_min_c": 17.0,
        "temp_max_c": 29.5,
    }
    valores.update(campos)
    return _inserir(conn, "condicoes_dia", valores)


def inserir_parto(conn: sqlite3.Connection, animal_id: int, **campos: object) -> int:
    valores: dict[str, object] = {"animal_id": animal_id, "data_parto": "2026-08-01"}
    valores.update(campos)
    return _inserir(conn, "partos", valores)


def test_sqlite_suporta_tabelas_strict() -> None:
    # STRICT exige SQLite 3.37+. Se este teste falhar, o problema é a versão do SQLite
    # do Python, e não o esquema.
    assert sqlite3.sqlite_version_info >= (3, 37, 0)


# --- animais -------------------------------------------------------------------------


def test_animal_valido_e_aceito(conn: sqlite3.Connection) -> None:
    animal_id = inserir_animal(conn)
    nome = conn.execute("SELECT nome FROM animais WHERE id = ?", (animal_id,)).fetchone()["nome"]
    assert nome == "Mimosa"


@pytest.mark.parametrize(
    "campos",
    [
        {"status": "descartada"},
        {"raca": "jersey"},
        {"sexo": "X"},
        {"lote": "qualquer"},
        {"nome": "   "},
        {"nome": ""},
        {"nome": "Mimosa "},
        {"nome": " Mimosa"},
        {"data_nascimento": "2020-02-30"},
        {"data_nascimento": "10/03/2020"},
    ],
)
def test_valores_fora_das_regras_sao_recusados(
    conn: sqlite3.Connection, campos: dict[str, object]
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        inserir_animal(conn, **campos)


@pytest.mark.parametrize(("status", "lote"), list(product(STATUS, LOTES)))
def test_matriz_completa_de_status_e_lote(
    conn: sqlite3.Connection, status: str, lote: str
) -> None:
    if (status, lote) in COMBINACOES_VALIDAS:
        inserir_animal(conn, status=status, lote=lote)
    else:
        with pytest.raises(sqlite3.IntegrityError):
            inserir_animal(conn, status=status, lote=lote)


def test_matriz_tem_32_combinacoes_e_10_validas() -> None:
    assert len(list(product(STATUS, LOTES))) == 32
    assert len(COMBINACOES_VALIDAS) == 10


def test_corte_pode_ser_macho(conn: sqlite3.Connection) -> None:
    inserir_animal(conn, nome="Touro1", sexo="M", status="corte", lote="pasto")


@pytest.mark.parametrize(
    ("status", "lote"),
    [("lactacao", "alta_producao"), ("seca", "pre_parto"), ("novilha", "recria")],
)
def test_macho_fora_de_corte_e_recusado(
    conn: sqlite3.Connection, status: str, lote: str
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        inserir_animal(conn, sexo="M", status=status, lote=lote)


def test_animal_inativo_valido_e_aceito(conn: sqlite3.Connection) -> None:
    inserir_animal(conn, ativo=0, data_saida="2026-10-01", motivo_saida="venda")


@pytest.mark.parametrize(
    "campos",
    [
        {"ativo": 0},  # inativo sem data e motivo
        {"ativo": 0, "data_saida": "2026-10-01"},  # inativo só com data
        {"ativo": 0, "motivo_saida": "venda"},  # inativo só com motivo
        {"ativo": 1, "data_saida": "2026-10-01", "motivo_saida": "venda"},  # ativo com saída
        {"ativo": 1, "motivo_saida": "venda"},  # ativo só com motivo
        {"ativo": 1, "data_saida": "2026-10-01"},  # ativo só com data
        {"ativo": 2},
        {"ativo": 0, "data_saida": "2026-10-01", "motivo_saida": "roubo"},
        {"ativo": 0, "data_saida": "2026-13-01", "motivo_saida": "venda"},
        # saída antes do nascimento (data_nascimento padrão: 2020-03-10)
        {"ativo": 0, "data_saida": "2019-01-01", "motivo_saida": "venda"},
    ],
)
def test_exclusao_logica_incoerente_e_recusada(
    conn: sqlite3.Connection, campos: dict[str, object]
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        inserir_animal(conn, **campos)


def test_nome_unico_apenas_entre_ativos(conn: sqlite3.Connection) -> None:
    inserir_animal(conn, nome="Mimosa")
    with pytest.raises(sqlite3.IntegrityError):
        inserir_animal(conn, nome="Mimosa")
    with pytest.raises(sqlite3.IntegrityError):  # maiúsculas e minúsculas não diferenciam
        inserir_animal(conn, nome="mimosa")


def test_nome_pode_ser_reaproveitado_depois_da_saida(conn: sqlite3.Connection) -> None:
    inserir_animal(conn, nome="Mimosa", ativo=0, data_saida="2026-10-01", motivo_saida="venda")
    inserir_animal(conn, nome="Mimosa")  # nova vaca com o mesmo nome


def test_inativo_pode_ter_o_mesmo_nome_de_um_ativo(conn: sqlite3.Connection) -> None:
    inserir_animal(conn, nome="Mimosa")
    inserir_animal(conn, nome="Mimosa", ativo=0, data_saida="2026-10-01", motivo_saida="morte")


def test_exclusao_logica_por_update_libera_o_nome(conn: sqlite3.Connection) -> None:
    antigo = inserir_animal(conn, nome="Mimosa")
    conn.execute(
        "UPDATE animais SET ativo = 0, data_saida = ?, motivo_saida = ? WHERE id = ?",
        ("2026-10-01", "venda", antigo),
    )
    novo = inserir_animal(conn, nome="Mimosa")
    assert novo != antigo
    # O registro antigo continua no banco.
    assert conn.execute("SELECT COUNT(*) FROM animais").fetchone()[0] == 2


def test_reativar_animal_com_nome_de_outro_ativo_e_recusado(conn: sqlite3.Connection) -> None:
    antigo = inserir_animal(
        conn, nome="Mimosa", ativo=0, data_saida="2026-10-01", motivo_saida="venda"
    )
    inserir_animal(conn, nome="Mimosa")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE animais SET ativo = 1, data_saida = NULL, motivo_saida = NULL WHERE id = ?",
            (antigo,),
        )


# --- producao_leite ------------------------------------------------------------------


def test_producao_valida_e_aceita(conn: sqlite3.Connection) -> None:
    inserir_producao(conn, inserir_animal(conn))


def test_producao_com_litros_zero_e_aceita(conn: sqlite3.Connection) -> None:
    inserir_producao(conn, inserir_animal(conn), litros_manha=0, litros_tarde=0.0)


def test_producao_repetida_para_o_mesmo_animal_e_data_e_recusada(
    conn: sqlite3.Connection,
) -> None:
    animal_id = inserir_animal(conn)
    inserir_producao(conn, animal_id)
    with pytest.raises(sqlite3.IntegrityError):
        inserir_producao(conn, animal_id)


def test_producao_de_animal_inexistente_e_recusada(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        inserir_producao(conn, animal_id=999)


@pytest.mark.parametrize(
    "campos",
    [
        {"litros_manha": -1.0},
        {"litros_tarde": -0.5},
        {"litros_manha": None},  # os dois turnos são obrigatórios
        {"litros_tarde": None},
        {"litros_manha": "abc"},  # tipo errado
        {"litros_tarde": "muito"},
        {"data": "2026-02-30"},
        {"data": "ontem"},
    ],
)
def test_producao_com_valores_invalidos_e_recusada(
    conn: sqlite3.Connection, campos: dict[str, object]
) -> None:
    animal_id = inserir_animal(conn)
    with pytest.raises(sqlite3.IntegrityError):
        inserir_producao(conn, animal_id, **campos)


# --- condicoes_dia e partos ----------------------------------------------------------


def test_condicoes_validas_sao_aceitas(conn: sqlite3.Connection) -> None:
    inserir_condicoes(conn)


@pytest.mark.parametrize(
    "campos",
    [
        {"chuva_manha": 2},
        {"chuva_tarde": -1},
        {"temp_min_c": 30.0, "temp_max_c": 20.0},
        {"temp_min_c": "frio"},
        {"temp_max_c": None},
        {"hora_ordenha_manha": "25:00"},
        {"hora_ordenha_tarde": "tarde"},
        {"data": "ontem"},
    ],
)
def test_condicoes_invalidas_sao_recusadas(
    conn: sqlite3.Connection, campos: dict[str, object]
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        inserir_condicoes(conn, **campos)


def test_condicoes_uma_linha_por_dia(conn: sqlite3.Connection) -> None:
    inserir_condicoes(conn)
    with pytest.raises(sqlite3.IntegrityError):
        inserir_condicoes(conn)


def test_parto_valido_e_aceito(conn: sqlite3.Connection) -> None:
    inserir_parto(conn, inserir_animal(conn))


def test_parto_exige_animal_existente(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        inserir_parto(conn, animal_id=999)


def test_parto_com_data_invalida_e_recusado(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        inserir_parto(conn, inserir_animal(conn), data_parto="2026-02-30")


def test_parto_repetido_para_o_mesmo_animal_e_data_e_recusado(conn: sqlite3.Connection) -> None:
    animal_id = inserir_animal(conn)
    inserir_parto(conn, animal_id)
    with pytest.raises(sqlite3.IntegrityError):
        inserir_parto(conn, animal_id)
    inserir_parto(conn, animal_id, data_parto="2025-07-01")  # outro parto é aceito


# --- conexões ------------------------------------------------------------------------


@pytest.fixture
def banco_em_arquivo(tmp_path: Path) -> Path:
    caminho = tmp_path / "rebanho.db"
    escrita = abrir_para_escrita(caminho)
    criar_schema(escrita)
    inserir_animal(escrita)
    escrita.commit()
    escrita.close()
    return caminho


def test_conexao_somente_leitura_consegue_consultar(banco_em_arquivo: Path) -> None:
    leitura = abrir_somente_leitura(banco_em_arquivo)
    try:
        assert leitura.execute("SELECT COUNT(*) AS n FROM animais").fetchone()["n"] == 1
    finally:
        leitura.close()


@pytest.mark.parametrize(
    "comando",
    [
        "INSERT INTO partos (animal_id, data_parto) VALUES (1, '2026-08-01')",
        "UPDATE animais SET nome = 'Outra'",
        "DELETE FROM animais",
        "DROP TABLE animais",
    ],
)
def test_conexao_somente_leitura_recusa_escrita(banco_em_arquivo: Path, comando: str) -> None:
    leitura = abrir_somente_leitura(banco_em_arquivo)
    try:
        with pytest.raises(sqlite3.OperationalError):
            leitura.execute(comando)
    finally:
        leitura.close()


def test_barreira_mode_ro_funciona_sozinha(banco_em_arquivo: Path) -> None:
    # Documenta por que existem duas barreiras: cada uma, sozinha, já impede a escrita.
    conexao = sqlite3.connect(banco_em_arquivo.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conexao.execute("DELETE FROM animais")
    finally:
        conexao.close()


def test_barreira_query_only_funciona_sozinha(banco_em_arquivo: Path) -> None:
    conexao = abrir_para_escrita(banco_em_arquivo)
    try:
        conexao.execute("PRAGMA query_only = ON")
        with pytest.raises(sqlite3.OperationalError):
            conexao.execute("DELETE FROM animais")
    finally:
        conexao.close()


def test_somente_leitura_nao_cria_arquivo_inexistente(tmp_path: Path) -> None:
    caminho = tmp_path / "nao_existe.db"
    with pytest.raises(FileNotFoundError):
        abrir_somente_leitura(caminho)
    assert not caminho.exists()


def test_chaves_estrangeiras_estao_ativas(conn: sqlite3.Connection) -> None:
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
