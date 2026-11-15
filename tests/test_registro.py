"""Testes do registro de ferramentas."""

import inspect
import json
import sqlite3
from collections.abc import Iterator

import pytest

from app.db.connection import criar_banco_em_memoria
from app.db.seed import gerar_dados, gravar_dados
from app.tools.producao import producao_por_periodo
from app.tools.registro import FERRAMENTAS, REGISTRO, declaracoes_neutras, executar_ferramenta


@pytest.fixture(scope="module")
def conn() -> Iterator[sqlite3.Connection]:
    conexao = criar_banco_em_memoria()
    gravar_dados(conexao, gerar_dados())
    yield conexao
    conexao.close()


def test_registro_tem_uma_entrada_por_ferramenta_com_nome_unico() -> None:
    nomes = [f.nome for f in FERRAMENTAS]
    assert len(nomes) == len(set(nomes))
    assert set(REGISTRO) == set(nomes)
    assert "producao_por_periodo" in REGISTRO


def test_declaracoes_neutras_sao_serializaveis_e_completas() -> None:
    declaracoes = declaracoes_neutras()
    json.dumps(declaracoes)  # não pode conter nada que não seja JSON
    for declaracao in declaracoes:
        assert set(declaracao) == {"name", "description", "parameters"}
        assert declaracao["parameters"]["type"] == "object"


def test_esquema_de_producao_por_periodo() -> None:
    parametros = REGISTRO["producao_por_periodo"].parametros
    assert parametros["required"] == ["dias"]
    assert set(parametros["properties"]) == {"dias", "animal_id"}


def test_esquema_nao_expoe_a_data_de_referencia_ao_modelo() -> None:
    # O modelo não escolhe a data de referência (ADR 0003): ela existe só para testes.
    texto = json.dumps(declaracoes_neutras())
    assert "data_referencia" not in texto


def test_esquema_acompanha_a_assinatura_da_funcao() -> None:
    # Se alguém mudar a função e esquecer o esquema (ou o contrário), este teste avisa.
    assinatura = inspect.signature(producao_por_periodo)
    do_modelo = {
        nome
        for nome, parametro in assinatura.parameters.items()
        if nome != "conn" and parametro.kind is not inspect.Parameter.KEYWORD_ONLY
    }
    assert do_modelo == set(REGISTRO["producao_por_periodo"].parametros["properties"])


def test_descricao_diz_quando_usar_e_quando_nao_usar() -> None:
    descricao = REGISTRO["producao_por_periodo"].descricao
    assert "USE" in descricao
    assert "NÃO USE" in descricao


def test_executar_ferramenta_devolve_o_resultado(conn: sqlite3.Connection) -> None:
    resultado = executar_ferramenta(conn, "producao_por_periodo", {"dias": 7})
    assert resultado["dias_com_registro"] == 7
    assert resultado["data_fim"] == "2026-11-15"


def test_executar_ferramenta_aceita_decimal_de_valor_inteiro(conn: sqlite3.Connection) -> None:
    assert executar_ferramenta(conn, "producao_por_periodo", {"dias": 7.0}) == (
        executar_ferramenta(conn, "producao_por_periodo", {"dias": 7})
    )


def test_ferramenta_desconhecida_e_erro_claro(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="Ferramenta desconhecida: apagar_tudo"):
        executar_ferramenta(conn, "apagar_tudo", {})


def test_argumento_desconhecido_e_erro_claro(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="não reconhecidos.*sql"):
        executar_ferramenta(conn, "producao_por_periodo", {"dias": 7, "sql": "DROP TABLE x"})


def test_argumento_obrigatorio_ausente_e_erro_claro(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="obrigatórios ausentes.*dias"):
        executar_ferramenta(conn, "producao_por_periodo", {})


def test_argumentos_nulos_valem_como_nenhum_argumento(conn: sqlite3.Connection) -> None:
    # Alguns provedores enviam a chamada sem objeto de argumentos; o erro esperado aqui é o
    # de argumento obrigatório ausente, e não um TypeError.
    with pytest.raises(ValueError, match="obrigatórios ausentes.*dias"):
        executar_ferramenta(conn, "producao_por_periodo", None)


@pytest.mark.parametrize("argumentos", [[7], "dias=7", 7, {1: 2}])
def test_argumentos_malformados_sao_erro_claro(
    conn: sqlite3.Connection, argumentos: object
) -> None:
    with pytest.raises(ValueError, match="argumentos"):
        executar_ferramenta(conn, "producao_por_periodo", argumentos)  # type: ignore[arg-type]


@pytest.mark.parametrize("nome", [None, 7, ["producao_por_periodo"]])
def test_nome_de_ferramenta_que_nao_e_texto_e_erro_claro(
    conn: sqlite3.Connection, nome: object
) -> None:
    with pytest.raises(ValueError, match="Ferramenta desconhecida"):
        executar_ferramenta(conn, nome, {"dias": 7})  # type: ignore[arg-type]


def test_animal_id_nulo_pelo_registro_vale_como_rebanho_inteiro(
    conn: sqlite3.Connection,
) -> None:
    com_nulo = executar_ferramenta(conn, "producao_por_periodo", {"dias": 7, "animal_id": None})
    assert com_nulo == executar_ferramenta(conn, "producao_por_periodo", {"dias": 7})


@pytest.mark.parametrize("animal_id", [10**30, 2**63, 1e300])
def test_erro_de_valor_pelo_registro_e_value_error_e_nao_overflow(
    conn: sqlite3.Connection, animal_id: object
) -> None:
    with pytest.raises(ValueError, match="animal_id"):
        executar_ferramenta(conn, "producao_por_periodo", {"dias": 7, "animal_id": animal_id})


def test_o_modelo_nao_consegue_passar_a_data_de_referencia(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="não reconhecidos.*data_referencia"):
        executar_ferramenta(
            conn, "producao_por_periodo", {"dias": 7, "data_referencia": "2020-01-01"}
        )
