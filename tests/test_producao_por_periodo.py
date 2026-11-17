"""Testes da ferramenta producao_por_periodo (e da consulta em app/db/producao.py).

Os testes principais usam um banco pequeno, escrito à mão, com valores que dá para calcular
de cabeça. Um teste à parte cruza o resultado com um cálculo independente sobre os dados do
gerador.
"""

import json
import sqlite3
from collections import defaultdict
from collections.abc import Callable, Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.db.connection import (
    abrir_para_escrita,
    abrir_somente_leitura,
    criar_banco_em_memoria,
    criar_schema,
)
from app.db.seed import DATA_FIM, Producao, gerar_dados, gravar_dados
from app.tools.erros import ErroDeFerramenta
from app.tools.producao import producao_por_periodo
from app.tools.registro import executar_ferramenta

REF = date(2026, 1, 10)
CASOS = Path(__file__).resolve().parents[1] / "evals" / "casos"


def _animal(
    conn: sqlite3.Connection,
    animal_id: int,
    nome: str,
    status: str = "lactacao",
    lote: str = "alta_producao",
    saida: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO animais (id, nome, sexo, raca, data_nascimento, status, lote, ativo,"
        " data_saida, motivo_saida) VALUES (?, ?, 'F', 'holandesa', '2020-03-10', ?, ?, ?, ?, ?)",
        (
            animal_id,
            nome,
            status,
            lote,
            0 if saida else 1,
            saida,
            "venda" if saida else None,
        ),
    )


def _producao(
    conn: sqlite3.Connection, animal_id: int, dia: int, manha: float, tarde: float
) -> None:
    conn.execute(
        "INSERT INTO producao_leite (animal_id, data, litros_manha, litros_tarde)"
        " VALUES (?, ?, ?, ?)",
        (animal_id, f"2026-01-{dia:02d}", manha, tarde),
    )


def _popular(conn: sqlite3.Connection) -> None:
    """Rebanho de teste. Litros de manhã e de tarde de cada dia, entre parênteses.

    1 Mimosa (ativa):   05 (5+5), 08 (10+8), 09 (12+9), 10 (11+9)
    2 Estrela (ativa):  09 (6+4), 10 (7+5)
    3 Bonita (novilha): sem produção
    4 Dona (vendida em 2026-01-08): 06 (8+6), 07 (9+6)
    A data de referência (maior data com produção) é 2026-01-10; o primeiro registro é de 05.
    """
    _animal(conn, 1, "Mimosa")
    _animal(conn, 2, "Estrela", lote="media_producao")
    _animal(conn, 3, "Bonita", status="novilha", lote="recria")
    _animal(conn, 4, "Dona", saida="2026-01-08")
    for animal_id, dia, manha, tarde in [
        (1, 5, 5, 5),
        (1, 8, 10, 8),
        (1, 9, 12, 9),
        (1, 10, 11, 9),
        (2, 9, 6, 4),
        (2, 10, 7, 5),
        (4, 6, 8, 6),
        (4, 7, 9, 6),
    ]:
        _producao(conn, animal_id, dia, manha, tarde)


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    conexao = criar_banco_em_memoria()
    _popular(conexao)
    yield conexao
    conexao.close()


# --- rebanho, por dias ---------------------------------------------------------------


def test_rebanho_em_3_dias(conn: sqlite3.Connection) -> None:
    # 08: 18  | 09: 21 + 10 = 31  | 10: 20 + 12 = 32  -> 81 em 3 dias (46 de manhã, 35 de tarde)
    assert producao_por_periodo(conn, 3) == {
        "litros_total": 81.0,
        "litros_manha_total": 46.0,
        "litros_tarde_total": 35.0,
        "litros_media_dia": 27.0,
        "dias_com_registro": 3,
        "data_inicio": "2026-01-08",
        "data_fim": "2026-01-10",
    }


def test_rebanho_em_1_dia_e_so_a_data_de_referencia(conn: sqlite3.Connection) -> None:
    resultado = producao_por_periodo(conn, 1)
    assert resultado["litros_total"] == 32.0
    assert resultado["litros_manha_total"] == 18.0
    assert resultado["litros_tarde_total"] == 14.0
    assert resultado["dias_com_registro"] == 1
    assert resultado["data_inicio"] == resultado["data_fim"] == "2026-01-10"


def test_rebanho_inclui_o_historico_de_animal_que_saiu(conn: sqlite3.Connection) -> None:
    # Janela 07 a 10: 07 (15, da Dona, vendida em 08) + 81 = 96 em 4 dias.
    resultado = producao_por_periodo(conn, 4)
    assert resultado["litros_total"] == 96.0
    assert resultado["litros_manha_total"] == 55.0
    assert resultado["litros_tarde_total"] == 41.0
    assert resultado["dias_com_registro"] == 4
    assert resultado["litros_media_dia"] == 24.0


def test_janela_maior_que_o_historico_conta_so_dias_com_registro(
    conn: sqlite3.Connection,
) -> None:
    # 10 dias: 01 a 10, mas só há registro em 6 datas (05, 06, 07, 08, 09, 10): total 120.
    resultado = producao_por_periodo(conn, 10)
    assert resultado["litros_total"] == 120.0
    assert resultado["litros_manha_total"] == 68.0
    assert resultado["litros_tarde_total"] == 52.0
    assert resultado["dias_com_registro"] == 6
    assert resultado["litros_media_dia"] == 20.0
    assert resultado["data_inicio"] == "2026-01-01"


def test_data_de_referencia_pode_ser_fixada_em_testes(conn: sqlite3.Connection) -> None:
    resultado = producao_por_periodo(conn, 2, data_referencia=date(2026, 1, 9))
    # 08: 18 | 09: 21 + 10 -> 49 em 2 dias
    assert resultado["litros_total"] == 49.0
    assert resultado["litros_media_dia"] == 24.5
    assert (resultado["data_inicio"], resultado["data_fim"]) == ("2026-01-08", "2026-01-09")


# --- um animal, por dias -------------------------------------------------------------


def test_animal_em_3_dias(conn: sqlite3.Connection) -> None:
    resultado = producao_por_periodo(conn, 3, animal_id=1)
    assert resultado["litros_total"] == 59.0
    assert resultado["litros_manha_total"] == 33.0
    assert resultado["litros_tarde_total"] == 26.0
    assert resultado["dias_com_registro"] == 3
    assert resultado["litros_media_dia"] == pytest.approx(19.67)


def test_dia_sem_registro_nao_entra_na_media_do_animal(conn: sqlite3.Connection) -> None:
    # A Estrela só tem registro em 09 e 10: 22 litros em 2 dias dentro de uma janela de 3.
    resultado = producao_por_periodo(conn, 3, animal_id=2)
    assert resultado["litros_total"] == 22.0
    assert resultado["dias_com_registro"] == 2
    assert resultado["litros_media_dia"] == 11.0


def test_fronteira_da_janela_e_inclusiva_no_primeiro_dia(conn: sqlite3.Connection) -> None:
    # dias=5 vai de 06 a 10 (exclui o dia 05); dias=6 vai de 05 a 10 (inclui o dia 05).
    assert producao_por_periodo(conn, 5, animal_id=1)["litros_total"] == 59.0
    seis = producao_por_periodo(conn, 6, animal_id=1)
    assert seis["litros_total"] == 69.0
    assert seis["dias_com_registro"] == 4


def test_animal_sem_producao_no_periodo_retorna_nulo_e_nao_zero(
    conn: sqlite3.Connection,
) -> None:
    resultado = producao_por_periodo(conn, 7, animal_id=3)
    assert resultado == {
        "litros_total": None,
        "litros_manha_total": None,
        "litros_tarde_total": None,
        "litros_media_dia": None,
        "dias_com_registro": 0,
        "data_inicio": "2026-01-04",
        "data_fim": "2026-01-10",
    }


def test_animal_inativo_pode_ser_consultado_por_id(conn: sqlite3.Connection) -> None:
    resultado = producao_por_periodo(conn, 10, animal_id=4)
    assert resultado["litros_total"] == 29.0
    assert resultado["dias_com_registro"] == 2
    assert resultado["litros_media_dia"] == 14.5


# --- por datas (ADR 0005) ------------------------------------------------------------


def test_um_dia_de_um_animal(conn: sqlite3.Connection) -> None:
    resultado = producao_por_periodo(
        conn, data_inicio="2026-01-09", data_fim="2026-01-09", animal_id=1
    )
    assert resultado == {
        "litros_total": 21.0,
        "litros_manha_total": 12.0,
        "litros_tarde_total": 9.0,
        "litros_media_dia": 21.0,
        "dias_com_registro": 1,
        "data_inicio": "2026-01-09",
        "data_fim": "2026-01-09",
    }


def test_intervalo_do_rebanho_com_historico_de_quem_saiu(conn: sqlite3.Connection) -> None:
    # 06: 14 (Dona) | 07: 15 (Dona) | 08: 18 (Mimosa) -> 47 em 3 dias (27 de manhã, 20 de tarde)
    resultado = producao_por_periodo(conn, data_inicio="2026-01-06", data_fim="2026-01-08")
    assert resultado["litros_total"] == 47.0
    assert resultado["litros_manha_total"] == 27.0
    assert resultado["litros_tarde_total"] == 20.0
    assert resultado["dias_com_registro"] == 3
    assert resultado["litros_media_dia"] == pytest.approx(15.67)


def test_dia_do_intervalo_sem_registro_do_animal_e_sem_registro_e_nao_zero(
    conn: sqlite3.Connection,
) -> None:
    # A Estrela não tem registro no dia 08, que está dentro do intervalo do banco.
    resultado = producao_por_periodo(
        conn, data_inicio="2026-01-08", data_fim="2026-01-08", animal_id=2
    )
    assert resultado["litros_total"] is None
    assert resultado["litros_manha_total"] is None
    assert resultado["dias_com_registro"] == 0
    assert resultado["data_inicio"] == resultado["data_fim"] == "2026-01-08"


def test_periodo_so_parcialmente_dentro_do_banco_conta_os_dias_com_registro(
    conn: sqlite3.Connection,
) -> None:
    # 01 a 06: só 05 (Mimosa, 10) e 06 (Dona, 14) têm registro.
    resultado = producao_por_periodo(conn, data_inicio="2026-01-01", data_fim="2026-01-06")
    assert resultado["litros_total"] == 24.0
    assert resultado["litros_manha_total"] == 13.0
    assert resultado["litros_tarde_total"] == 11.0
    assert resultado["dias_com_registro"] == 2
    assert (resultado["data_inicio"], resultado["data_fim"]) == ("2026-01-01", "2026-01-06")


def test_intervalo_de_datas_nao_tem_o_limite_de_90_dias(conn: sqlite3.Connection) -> None:
    resultado = producao_por_periodo(conn, data_inicio="2025-01-01", data_fim="2026-01-10")
    assert resultado["litros_total"] == 120.0
    assert resultado["dias_com_registro"] == 6


def test_animal_inativo_por_data(conn: sqlite3.Connection) -> None:
    resultado = producao_por_periodo(
        conn, data_inicio="2026-01-06", data_fim="2026-01-06", animal_id=4
    )
    assert resultado["litros_total"] == 14.0


def test_datas_e_dias_equivalentes_dao_o_mesmo_resultado(conn: sqlite3.Connection) -> None:
    por_datas = producao_por_periodo(conn, data_inicio="2026-01-08", data_fim="2026-01-10")
    assert por_datas == producao_por_periodo(conn, 3)


def test_texto_vazio_nos_parametros_de_data_equivale_a_omitido(conn: sqlite3.Connection) -> None:
    com_vazios = producao_por_periodo(conn, 3, data_inicio="", data_fim="  ")
    assert com_vazios == producao_por_periodo(conn, 3)
    so_datas = producao_por_periodo(
        conn, dias=None, data_inicio="2026-01-08", data_fim="2026-01-10"
    )
    assert so_datas == producao_por_periodo(conn, 3)


@pytest.mark.parametrize(
    ("argumentos", "trecho"),
    [
        ({"dias": 7, "data_inicio": "2026-01-08", "data_fim": "2026-01-10"}, "nunca os dois"),
        ({"dias": 7, "data_inicio": "2026-01-08"}, "nunca os dois"),
        ({"data_inicio": "2026-01-08"}, "juntas"),
        ({"data_fim": "2026-01-08"}, "juntas"),
        ({}, "Informe `dias`"),
        ({"data_inicio": "2026-01-09", "data_fim": "2026-01-08"}, "depois de `data_fim`"),
        ({"data_inicio": "2026-01-08", "data_fim": "2026-01-11"}, "O banco tem registros de"),
        ({"data_inicio": "2026-01-01", "data_fim": "2026-01-04"}, "2026-01-05 a 2026-01-10"),
    ],
)
def test_periodo_invalido_e_erro_claro(
    conn: sqlite3.Connection, argumentos: dict[str, Any], trecho: str
) -> None:
    with pytest.raises(ErroDeFerramenta, match=trecho):
        producao_por_periodo(conn, **argumentos)


@pytest.mark.parametrize(
    "data",
    ["10/01/2026", "2026-1-9", "20260109", "2026-02-30", "2026-13-01", "ontem", 20260109, 9.5],
)
def test_data_em_formato_invalido_e_erro_claro(conn: sqlite3.Connection, data: object) -> None:
    with pytest.raises(ErroDeFerramenta, match="data_inicio"):
        producao_por_periodo(conn, data_inicio=data, data_fim="2026-01-10")  # type: ignore[arg-type]


def test_data_final_depois_da_data_de_referencia_fixada_e_erro(conn: sqlite3.Connection) -> None:
    with pytest.raises(ErroDeFerramenta, match="depois do último dia"):
        producao_por_periodo(
            conn,
            data_inicio="2026-01-08",
            data_fim="2026-01-10",
            data_referencia=date(2026, 1, 9),
        )


# --- entradas inválidas --------------------------------------------------------------


@pytest.mark.parametrize(
    "chamada",
    [
        lambda c: producao_por_periodo(c, 0),
        lambda c: producao_por_periodo(c, "7"),  # type: ignore[arg-type]
        lambda c: producao_por_periodo(c, 7, animal_id=999),
        lambda c: producao_por_periodo(c, 7, animal_id=10**30),
        lambda c: producao_por_periodo(c, data_inicio="ontem", data_fim="hoje"),
        lambda c: producao_por_periodo(c),
    ],
)
def test_erros_previstos_sao_erro_de_ferramenta(
    conn: sqlite3.Connection, chamada: Callable[[sqlite3.Connection], object]
) -> None:
    # É esse tipo de erro que o laço do agente devolve ao modelo, com a mensagem original.
    with pytest.raises(ErroDeFerramenta):
        chamada(conn)


def test_animal_inexistente_e_erro_claro(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="Não existe animal com id 999"):
        producao_por_periodo(conn, 7, animal_id=999)


@pytest.mark.parametrize("dias", [0, -1, 91, 7.5, "7", True])
def test_dias_invalido_e_erro_claro(conn: sqlite3.Connection, dias: object) -> None:
    with pytest.raises(ValueError, match="dias"):
        producao_por_periodo(conn, dias)  # type: ignore[arg-type]


@pytest.mark.parametrize("animal_id", ["1", 1.5, True, [1]])
def test_animal_id_invalido_e_erro_claro(conn: sqlite3.Connection, animal_id: object) -> None:
    with pytest.raises(ValueError, match="animal_id"):
        producao_por_periodo(conn, 7, animal_id=animal_id)  # type: ignore[arg-type]


@pytest.mark.parametrize("animal_id", [10**30, 2**63, -(2**63) - 1, 1e300])
def test_animal_id_gigante_e_erro_claro_e_nao_overflow(
    conn: sqlite3.Connection, animal_id: object
) -> None:
    with pytest.raises(ValueError, match="animal_id"):
        producao_por_periodo(conn, 7, animal_id=animal_id)  # type: ignore[arg-type]


@pytest.mark.parametrize("dias", [10**30, 1e300, float("nan"), float("inf"), -float("inf")])
def test_dias_gigante_ou_nao_finito_e_erro_claro(
    conn: sqlite3.Connection, dias: object
) -> None:
    with pytest.raises(ValueError, match="dias"):
        producao_por_periodo(conn, dias)  # type: ignore[arg-type]


def test_maior_inteiro_do_sqlite_chega_ao_banco_e_vira_animal_inexistente(
    conn: sqlite3.Connection,
) -> None:
    with pytest.raises(ValueError, match="Não existe animal"):
        producao_por_periodo(conn, 7, animal_id=2**63 - 1)


def test_animal_id_nulo_equivale_a_omitido(conn: sqlite3.Connection) -> None:
    assert producao_por_periodo(conn, 3, animal_id=None) == producao_por_periodo(conn, 3)


def test_aceita_decimal_de_valor_inteiro_como_o_modelo_costuma_enviar(
    conn: sqlite3.Connection,
) -> None:
    assert producao_por_periodo(conn, 3.0, animal_id=1.0) == producao_por_periodo(
        conn, 3, animal_id=1
    )


def test_limites_de_dias_sao_aceitos(conn: sqlite3.Connection) -> None:
    assert producao_por_periodo(conn, 1)["dias_com_registro"] == 1
    assert producao_por_periodo(conn, 90)["data_inicio"] == "2025-10-13"


# --- banco sem produção --------------------------------------------------------------


def test_banco_sem_producao_retorna_vazio_e_nao_quebra() -> None:
    vazio = criar_banco_em_memoria()
    _animal(vazio, 1, "Mimosa")
    try:
        esperado = {
            "litros_total": None,
            "litros_manha_total": None,
            "litros_tarde_total": None,
            "litros_media_dia": None,
            "dias_com_registro": 0,
            "data_inicio": None,
            "data_fim": None,
        }
        assert producao_por_periodo(vazio, 7) == esperado
        assert producao_por_periodo(vazio, 7, animal_id=1) == esperado
        assert (
            producao_por_periodo(vazio, data_inicio="2026-01-01", data_fim="2026-01-02")
            == esperado
        )
        with pytest.raises(ValueError, match="Não existe animal"):
            producao_por_periodo(vazio, 7, animal_id=2)
        with pytest.raises(ErroDeFerramenta, match="nunca os dois"):  # valida mesmo sem dados
            producao_por_periodo(vazio, 7, data_inicio="2026-01-01", data_fim="2026-01-02")
    finally:
        vazio.close()


# --- somente leitura -----------------------------------------------------------------


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
        assert producao_por_periodo(leitura, 3)["litros_total"] == 81.0
        assert producao_por_periodo(leitura, 3, animal_id=1)["litros_total"] == 59.0
        por_data = producao_por_periodo(leitura, data_inicio="2026-01-09", data_fim="2026-01-09")
        assert por_data["litros_total"] == 31.0
    finally:
        leitura.close()
    assert caminho.read_bytes() == bytes_antes


# --- cruzamento com os dados do gerador ----------------------------------------------


def _resultado_independente(
    dados_producao: tuple[Producao, ...], animal_id: int | None, dias: int
) -> dict[str, float]:
    """Calcula o resultado em Python puro, sem SQL.

    A referência é o último dia do período do gerador. A média é a média dos totais diários
    (para um animal, é a média dos seus próprios dias), calculada agrupando por data.
    """
    inicio = (DATA_FIM - timedelta(days=dias - 1)).isoformat()
    totais_por_dia: dict[str, float] = defaultdict(float)
    manha = tarde = 0.0
    for p in dados_producao:
        if inicio <= p.data <= DATA_FIM.isoformat() and (
            animal_id is None or p.animal_id == animal_id
        ):
            totais_por_dia[p.data] += p.litros_manha + p.litros_tarde
            manha += p.litros_manha
            tarde += p.litros_tarde
    total = sum(totais_por_dia.values())
    return {
        "total": total,
        "dias": len(totais_por_dia),
        "media": total / len(totais_por_dia),
        "manha": manha,
        "tarde": tarde,
    }


@pytest.mark.parametrize(
    ("animal_id", "dias"), [(None, 7), (None, 30), (None, 90), (1, 7), (28, 30)]
)
def test_resultado_confere_com_calculo_independente_sobre_o_gerador(
    animal_id: int | None, dias: int
) -> None:
    dados = gerar_dados()
    conexao = criar_banco_em_memoria()
    try:
        gravar_dados(conexao, dados)
        resultado = producao_por_periodo(conexao, dias, animal_id=animal_id)
        por_datas = producao_por_periodo(
            conexao,
            data_inicio=(DATA_FIM - timedelta(days=dias - 1)).isoformat(),
            data_fim=DATA_FIM.isoformat(),
            animal_id=animal_id,
        )
    finally:
        conexao.close()
    esperado = _resultado_independente(dados.producao, animal_id, dias)
    assert resultado["litros_total"] == pytest.approx(esperado["total"], abs=0.05)
    assert resultado["litros_manha_total"] == pytest.approx(esperado["manha"], abs=0.05)
    assert resultado["litros_tarde_total"] == pytest.approx(esperado["tarde"], abs=0.05)
    assert resultado["dias_com_registro"] == esperado["dias"]
    assert resultado["litros_media_dia"] == pytest.approx(esperado["media"], abs=0.01)
    assert resultado["data_fim"] == DATA_FIM.isoformat()
    assert por_datas == resultado  # os dois modos de período dão o mesmo resultado


# --- casos de eval -------------------------------------------------------------------


def _casos_de_eval() -> list[dict[str, Any]]:
    casos: list[dict[str, Any]] = []
    for arquivo in sorted(CASOS.glob("producao_por_periodo*.json")):
        casos.extend(json.loads(arquivo.read_text(encoding="utf-8")))
    return casos


def test_ha_casos_de_eval_para_a_ferramenta() -> None:
    assert len(_casos_de_eval()) >= 4


@pytest.mark.parametrize("caso", _casos_de_eval(), ids=lambda c: c["id"])
def test_valor_esperado_de_cada_eval_ainda_bate_com_o_banco(caso: dict[str, Any]) -> None:
    if "ferramenta_esperada" not in caso:
        pytest.skip("caso com várias chamadas: coberto pelo executor das evals")
    conexao = criar_banco_em_memoria()
    try:
        gravar_dados(conexao, gerar_dados(caso["semente"]))
        resultado = executar_ferramenta(
            conexao, caso["ferramenta_esperada"], caso["argumentos_esperados"]
        )
    finally:
        conexao.close()
    for campo, esperado in caso["valor_esperado"].items():
        assert resultado[campo] == pytest.approx(esperado), f"campo {campo}"
