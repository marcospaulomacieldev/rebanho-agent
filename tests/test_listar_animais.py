"""Testes da ferramenta listar_animais (e da consulta em app/db/animais.py).

Os testes principais usam um banco pequeno, escrito à mão. Outros conferem o comportamento
no banco do gerador (semente 42), onde estão os casos de nome ambíguo e de erro de digitação.
"""

import json
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.db.animais import LOTES_VALIDOS, STATUS_VALIDOS
from app.db.connection import (
    abrir_para_escrita,
    abrir_somente_leitura,
    criar_banco_em_memoria,
    criar_schema,
)
from app.db.seed import NOME_INSTRUCAO, gerar_dados, gravar_dados
from app.tools.animais import MAX_ANIMAIS, MAX_SUGESTOES, listar_animais, normalizar
from app.tools.erros import ErroDeFerramenta
from app.tools.registro import executar_ferramenta

RAIZ = Path(__file__).resolve().parents[1]
CASOS = RAIZ / "evals" / "casos"


def _animal(
    conn: sqlite3.Connection,
    animal_id: int,
    nome: str,
    status: str = "lactacao",
    lote: str = "alta_producao",
    sexo: str = "F",
    saida: str | None = None,
    motivo: str = "venda",
) -> None:
    conn.execute(
        "INSERT INTO animais (id, nome, sexo, raca, data_nascimento, status, lote, ativo,"
        " data_saida, motivo_saida) VALUES (?, ?, ?, 'holandesa', '2020-03-10', ?, ?, ?, ?, ?)",
        (animal_id, nome, sexo, status, lote, 0 if saida else 1, saida, motivo if saida else None),
    )


def _popular(conn: sqlite3.Connection) -> None:
    """Rebanho de teste (ids entre parênteses). Ordem alfabética sem acento dos ativos:
    Áurea (4), Bonita (5), Estrela (2), Estrelinha (3), Mimosa (1), Valente (8).

    Dois inativos: Pintada (6, vendida) e uma segunda Mimosa (7, morta), com o nome da ativa.
    """
    _animal(conn, 1, "Mimosa")
    _animal(conn, 2, "Estrela", status="novilha", lote="recria")
    _animal(conn, 3, "Estrelinha", lote="media_producao")
    _animal(conn, 4, "Áurea", status="seca", lote="pre_parto")
    _animal(conn, 5, "Bonita", status="novilha", lote="pasto")
    _animal(conn, 6, "Pintada", lote="media_producao", saida="2026-01-08")
    _animal(conn, 7, "Mimosa", saida="2026-01-05", motivo="morte")
    _animal(conn, 8, "Valente", status="corte", lote="pasto", sexo="M")


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    conexao = criar_banco_em_memoria()
    _popular(conexao)
    yield conexao
    conexao.close()


def ids(resultado: dict[str, Any]) -> list[int]:
    return [a["id"] for a in resultado["animais"]]


# --- normalização --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Mimosa", "mimosa"),
        ("ÁUREA", "aurea"),
        ("Açucena", "acucena"),
        ("Hortênsia", "hortensia"),
        ("  Maria   da  Luz ", "maria da luz"),
        ("Ilusão", "ilusao"),
    ],
)
def test_normalizar_tira_acento_caixa_e_espacos_extras(texto: str, esperado: str) -> None:
    assert normalizar(texto) == esperado


# --- sem filtros, por fase e por lote ------------------------------------------------


def test_sem_filtros_lista_so_os_ativos_em_ordem_alfabetica_sem_acento(
    conn: sqlite3.Connection,
) -> None:
    resultado = listar_animais(conn)
    # Áurea, Bonita, Estrela, Estrelinha, Mimosa, Valente
    assert ids(resultado) == [4, 5, 2, 3, 1, 8]
    assert resultado["total"] == 6
    assert resultado["sugestoes"] == []


def test_campos_de_cada_animal(conn: sqlite3.Connection) -> None:
    mimosa = next(a for a in listar_animais(conn)["animais"] if a["id"] == 1)
    assert mimosa == {
        "id": 1,
        "nome": "Mimosa",
        "sexo": "F",
        "raca": "holandesa",
        "data_nascimento": "2020-03-10",
        "status": "lactacao",
        "lote": "alta_producao",
        "ativo": True,
        "data_saida": None,
        "motivo_saida": None,
    }


def test_inativo_mostra_data_e_motivo_de_saida(conn: sqlite3.Connection) -> None:
    todos = listar_animais(conn, incluir_inativos=True)["animais"]
    pintada = next(a for a in todos if a["id"] == 6)
    assert pintada["ativo"] is False
    assert pintada["data_saida"] == "2026-01-08"
    assert pintada["motivo_saida"] == "venda"


def test_inativos_so_aparecem_quando_pedidos(conn: sqlite3.Connection) -> None:
    assert 6 not in ids(listar_animais(conn))
    assert 6 in ids(listar_animais(conn, incluir_inativos=True))
    assert listar_animais(conn, incluir_inativos=True)["total"] == 8


def test_filtro_por_status(conn: sqlite3.Connection) -> None:
    assert ids(listar_animais(conn, status="novilha")) == [5, 2]  # Bonita, Estrela
    assert ids(listar_animais(conn, status="corte")) == [8]


def test_filtro_por_lote_nao_traz_o_inativo(conn: sqlite3.Connection) -> None:
    assert ids(listar_animais(conn, lote="media_producao")) == [3]
    assert ids(listar_animais(conn, lote="media_producao", incluir_inativos=True)) == [3, 6]


def test_combinacao_valida_mas_impossivel_devolve_lista_vazia(conn: sqlite3.Connection) -> None:
    resultado = listar_animais(conn, status="lactacao", lote="recria")
    assert resultado == {
        "animais": [],
        "total": 0,
        "sugestoes": [],
        "encontrados_entre_inativos": 0,
    }


def test_status_e_lote_ignoram_caixa_e_espacos_e_vazio_vale_como_omitido(
    conn: sqlite3.Connection,
) -> None:
    assert ids(listar_animais(conn, status=" SECA ")) == [4]
    assert listar_animais(conn, status="", lote="  ") == listar_animais(conn)


def test_status_invalido_e_erro_claro_com_os_valores_validos(conn: sqlite3.Connection) -> None:
    with pytest.raises(ErroDeFerramenta, match="`status` inválido.*lactacao, seca, novilha, corte"):
        listar_animais(conn, status="descartada")


def test_lote_invalido_e_erro_claro(conn: sqlite3.Connection) -> None:
    with pytest.raises(ErroDeFerramenta, match="`lote` inválido.*alta_producao"):
        listar_animais(conn, lote="curral")


@pytest.mark.parametrize("campo", ["status", "lote", "nome"])
def test_filtro_que_nao_e_texto_e_erro_claro(conn: sqlite3.Connection, campo: str) -> None:
    with pytest.raises(ErroDeFerramenta, match=campo):
        listar_animais(conn, **{campo: 123})  # type: ignore[arg-type]


@pytest.mark.parametrize("valor", ["sim", 1, 0, "true", [True]])
def test_incluir_inativos_que_nao_e_booleano_e_erro_claro(
    conn: sqlite3.Connection, valor: object
) -> None:
    with pytest.raises(ErroDeFerramenta, match="incluir_inativos"):
        listar_animais(conn, incluir_inativos=valor)  # type: ignore[arg-type]


def test_incluir_inativos_nulo_vale_como_falso(conn: sqlite3.Connection) -> None:
    assert listar_animais(conn, incluir_inativos=None) == listar_animais(conn)


# --- busca por nome ------------------------------------------------------------------


def test_busca_por_trecho_acha_mais_de_um(conn: sqlite3.Connection) -> None:
    resultado = listar_animais(conn, nome="estrel")
    assert ids(resultado) == [2, 3]
    assert resultado["total"] == 2


def test_nome_completo_nao_casa_com_nome_mais_longo_que_nao_o_contem(
    conn: sqlite3.Connection,
) -> None:
    # "estrela" não está dentro de "estrelinha" (há um "i" depois do "l").
    assert ids(listar_animais(conn, nome="estrela")) == [2]


@pytest.mark.parametrize("nome", ["aurea", "AUREA", "áurea", "Áurea", "  aurea  ", "urea"])
def test_busca_ignora_acento_caixa_e_espacos_nas_pontas(
    conn: sqlite3.Connection, nome: str
) -> None:
    assert ids(listar_animais(conn, nome=nome)) == [4]


def test_nome_repetido_entre_ativo_e_inativo(conn: sqlite3.Connection) -> None:
    assert ids(listar_animais(conn, nome="mimosa")) == [1]
    assert ids(listar_animais(conn, nome="mimosa", incluir_inativos=True)) == [1, 7]


@pytest.mark.parametrize("nome", ["%", "_", "%%", "a%a", "'; DROP TABLE animais; --", "\\"])
def test_curingas_e_texto_de_ataque_sao_so_texto_comum(
    conn: sqlite3.Connection, nome: str
) -> None:
    assert listar_animais(conn, nome=nome)["total"] == 0
    assert conn.execute("SELECT COUNT(*) FROM animais").fetchone()[0] == 8  # nada foi alterado


def test_nome_vazio_ou_so_com_espacos_equivale_a_omitido(conn: sqlite3.Connection) -> None:
    assert listar_animais(conn, nome="") == listar_animais(conn)
    assert listar_animais(conn, nome="   ") == listar_animais(conn)
    assert listar_animais(conn, nome=None) == listar_animais(conn)


def test_nome_longo_demais_e_erro_claro(conn: sqlite3.Connection) -> None:
    with pytest.raises(ErroDeFerramenta, match="longo demais"):
        listar_animais(conn, nome="a" * 101)


def test_nome_combina_com_os_outros_filtros(conn: sqlite3.Connection) -> None:
    assert ids(listar_animais(conn, nome="estrel", status="novilha")) == [2]
    assert ids(listar_animais(conn, nome="estrel", status="corte")) == []


# --- sugestões para erro de digitação ------------------------------------------------


def test_erro_de_digitacao_sugere_o_nome_parecido(conn: sqlite3.Connection) -> None:
    resultado = listar_animais(conn, nome="mimoza")
    assert resultado["animais"] == []
    assert resultado["total"] == 0
    assert resultado["sugestoes"] == ["Mimosa"]  # um nome só, mesmo com a Mimosa inativa


def test_sugestoes_vem_do_mais_parecido_ao_menos_parecido(conn: sqlite3.Connection) -> None:
    assert listar_animais(conn, nome="estrella")["sugestoes"] == ["Estrela", "Estrelinha"]


def test_nome_sem_parecido_nao_traz_sugestao(conn: sqlite3.Connection) -> None:
    assert listar_animais(conn, nome="xyzxyz")["sugestoes"] == []


def test_com_resultado_nao_ha_sugestao(conn: sqlite3.Connection) -> None:
    assert listar_animais(conn, nome="mimosa")["sugestoes"] == []


def test_sugestao_respeita_o_filtro_de_inativos(conn: sqlite3.Connection) -> None:
    assert listar_animais(conn, nome="pintda")["sugestoes"] == []  # a Pintada está inativa
    assert listar_animais(conn, nome="pintda", incluir_inativos=True)["sugestoes"] == ["Pintada"]


def test_no_maximo_tres_sugestoes() -> None:
    banco = criar_banco_em_memoria()
    try:
        for numero, nome in enumerate(["Mimosa1", "Mimosa2", "Mimosa3", "Mimosa4", "Mimosa5"], 1):
            _animal(banco, numero, nome)
        assert len(listar_animais(banco, nome="mimosz")["sugestoes"]) == MAX_SUGESTOES
    finally:
        banco.close()


# --- limite --------------------------------------------------------------------------


def test_lista_tem_limite_mas_o_total_conta_todos() -> None:
    banco = criar_banco_em_memoria()
    try:
        for numero in range(1, 121):
            _animal(banco, numero, f"Vaca{numero:03d}")
        resultado = listar_animais(banco)
        assert len(resultado["animais"]) == MAX_ANIMAIS == 100
        assert resultado["total"] == 120
        assert resultado["animais"][0]["nome"] == "Vaca001"  # a lista é a dos primeiros por nome
    finally:
        banco.close()


# --- pelo registro, como o modelo chama ----------------------------------------------


def test_chamada_pelo_registro_com_nulos_nos_parametros_omitidos(conn: sqlite3.Connection) -> None:
    argumentos = {"status": None, "lote": None, "nome": "mimosa", "incluir_inativos": None}
    resultado = executar_ferramenta(conn, "listar_animais", argumentos)
    assert ids(resultado) == [1]


def test_funciona_na_conexao_somente_leitura_e_nao_altera_o_banco(tmp_path: Path) -> None:
    caminho = tmp_path / "rebanho.db"
    escrita = abrir_para_escrita(caminho)
    criar_schema(escrita)
    _popular(escrita)
    escrita.commit()
    escrita.close()
    bytes_antes = caminho.read_bytes()
    leitura = abrir_somente_leitura(caminho)
    try:
        assert ids(listar_animais(leitura, nome="estrel")) == [2, 3]
    finally:
        leitura.close()
    assert caminho.read_bytes() == bytes_antes


# --- as listas do código batem com as do banco ---------------------------------------


def _valores_do_schema(coluna: str) -> tuple[str, ...]:
    schema = (RAIZ / "app" / "db" / "schema.sql").read_text(encoding="utf-8")
    trecho = re.search(rf"\b{coluna}\s+TEXT\s+NOT NULL CHECK \(\s*{coluna} IN \(([^)]*)\)", schema)
    assert trecho, f"não achei a lista fechada de {coluna} no schema.sql"
    return tuple(re.findall(r"'([a-z_]+)'", trecho.group(1)))


def test_listas_fechadas_do_codigo_sao_as_do_schema() -> None:
    assert STATUS_VALIDOS == _valores_do_schema("status")
    assert LOTES_VALIDOS == _valores_do_schema("lote")


# --- banco do gerador (semente 42) ---------------------------------------------------


@pytest.fixture(scope="module")
def conn_gerador() -> Iterator[sqlite3.Connection]:
    conexao = criar_banco_em_memoria()
    gravar_dados(conexao, gerar_dados())
    yield conexao
    conexao.close()


def test_gerador_tem_55_animais_ativos_e_5_inativos(conn_gerador: sqlite3.Connection) -> None:
    assert listar_animais(conn_gerador)["total"] == 55
    assert listar_animais(conn_gerador, incluir_inativos=True)["total"] == 60


def test_gerador_estrel_acha_estrela_e_estrelinha_mas_estrela_so_uma(
    conn_gerador: sqlite3.Connection,
) -> None:
    assert ids(listar_animais(conn_gerador, nome="estrel")) == [44, 29]
    assert ids(listar_animais(conn_gerador, nome="estrela")) == [44]


def test_gerador_mel_e_ambiguo_com_caramelo(conn_gerador: sqlite3.Connection) -> None:
    resultado = listar_animais(conn_gerador, nome="mel")
    assert [a["nome"] for a in resultado["animais"]] == ["Caramelo", "Mel"]
    assert resultado["total"] == 2


def test_gerador_mimoza_sugere_mimosa(conn_gerador: sqlite3.Connection) -> None:
    assert listar_animais(conn_gerador, nome="mimoza")["sugestoes"] == ["Mimosa"]


def test_gerador_nome_de_instrucao_chega_como_dado(conn_gerador: sqlite3.Connection) -> None:
    resultado = listar_animais(conn_gerador, nome="ignore")
    assert [a["nome"] for a in resultado["animais"]] == [NOME_INSTRUCAO]


def test_gerador_contagens_por_status(conn_gerador: sqlite3.Connection) -> None:
    assert listar_animais(conn_gerador, status="lactacao")["total"] == 32
    assert listar_animais(conn_gerador, status="seca")["total"] == 8
    assert listar_animais(conn_gerador, status="corte")["total"] == 6
    assert listar_animais(conn_gerador, status="corte", incluir_inativos=True)["total"] == 7


# --- casos de eval -------------------------------------------------------------------


def _casos_de_eval() -> list[dict[str, Any]]:
    casos: list[dict[str, Any]] = []
    for arquivo in sorted(CASOS.glob("listar_animais*.json")):
        casos.extend(json.loads(arquivo.read_text(encoding="utf-8")))
    return casos


def test_ha_casos_de_eval_para_a_ferramenta() -> None:
    assert len(_casos_de_eval()) >= 7


@pytest.mark.parametrize("caso", _casos_de_eval(), ids=lambda c: c["id"])
def test_valor_esperado_de_cada_eval_ainda_bate_com_o_banco(
    caso: dict[str, Any], conn_gerador: sqlite3.Connection
) -> None:
    resultado = executar_ferramenta(
        conn_gerador, caso["ferramenta_esperada"], caso["argumentos_esperados"]
    )
    esperado = caso["valor_esperado"]
    if "total" in esperado:
        assert resultado["total"] == esperado["total"]
    if "ids" in esperado:
        assert ids(resultado) == esperado["ids"]
    if "nomes" in esperado:
        assert [a["nome"] for a in resultado["animais"]] == esperado["nomes"]
    if "sugestoes" in esperado:
        assert resultado["sugestoes"] == esperado["sugestoes"]
