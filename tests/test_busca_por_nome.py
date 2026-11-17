"""Metas da busca por nome com erros de digitação (medição em `evals/busca_por_nome.py`).

Sem modelo de linguagem: só a ferramenta `listar_animais`. Os erros são gerados para todos os
animais (letra faltando, letras trocadas de lugar no meio e nas pontas, letra dobrada, troca de
som e h inicial), e há também nomes de vaca que não existem no rebanho. As metas protegem a
regra "uma sugestão: o agente segue com ela" (ADR 0005): uma sugestão errada leva à vaca errada.

Atenção: a regra foi escolhida olhando a semente 42, e os números das metas são os observados
nela. Por isso as duas metas de segurança também rodam em outras sementes (outros conjuntos de
nomes), que não foram usadas para escolher a regra.
"""

import sqlite3
from collections.abc import Iterator
from typing import Any

import pytest

from app.db.connection import criar_banco_em_memoria
from app.db.seed import NOME_INSTRUCAO, gerar_dados, gravar_dados
from app.tools.animais import _distancia, chave_de_som, listar_animais, semelhanca
from evals.busca_por_nome import erros_de_digitacao, medir, nomes_fora_do_rebanho


@pytest.fixture(scope="module")
def conn() -> Iterator[sqlite3.Connection]:
    conexao = criar_banco_em_memoria()
    gravar_dados(conexao, gerar_dados())
    yield conexao
    conexao.close()


@pytest.fixture(scope="module")
def medida(conn: sqlite3.Connection) -> dict[str, Any]:
    return medir(conn)


# --- peças da comparação -------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Cereja", "sereja"),
        ("Cereja", "serreja"),
        ("Chita", "xita"),
        ("Açucena", "assucena"),
        ("Hortênsia", "ortensia"),
        ("Gabriela", "gabriella"),
    ],
)
def test_chave_de_som_iguala_grafias_que_soam_igual(a: str, b: str) -> None:
    assert chave_de_som(a) == chave_de_som(b)


def test_m_e_n_no_fim_nao_sao_iguais_pelo_som_mas_ficam_a_uma_letra() -> None:
    # "Jasmim" e "jasmin" não têm a mesma chave de som; quem os aproxima é a regra de uma
    # letra de distância. (Antes, este par estava no teste acima, escondido por um "or".)
    assert chave_de_som("Jasmim") != chave_de_som("jasmin")
    assert _distancia(chave_de_som("Jasmim"), chave_de_som("jasmin")) == 1


def test_chave_de_som_separa_nomes_diferentes() -> None:
    assert chave_de_som("Mimosa") != chave_de_som("Malhada")
    assert chave_de_som("Mel") != chave_de_som("Lua")


@pytest.mark.parametrize(
    ("a", "b", "esperado"),
    [
        ("luna", "lnua", 1),  # letras vizinhas trocadas contam como um erro só
        ("mimosa", "mimoza", 1),
        ("mimosa", "mimosa", 0),
        ("mel", "", 3),
        ("rosa", "rosana", 2),
    ],
)
def test_distancia(a: str, b: str, esperado: int) -> None:
    assert _distancia(a, b) == esperado
    assert _distancia(b, a) == esperado


def test_semelhanca_fica_entre_zero_e_um() -> None:
    assert semelhanca("mimosa", "mimosa") == 1.0
    assert semelhanca("", "mimosa") == 0.0
    assert 0.8 < semelhanca("mimosa", "mimoza") < 1.0


def test_gerador_de_erros_produz_os_tipos_esperados() -> None:
    erros = erros_de_digitacao("Hortênsia")
    assert set(erros) >= {"falta letra", "letras trocadas", "letra dobrada", "sem h"}
    assert all(e != "hortensia" for e in erros.values())


# --- metas sobre erros de digitação de vacas que existem -----------------------------


def test_a_medicao_cobre_todos_os_animais(medida: dict[str, Any]) -> None:
    # 347 na semente 42 (a medição de 2026-11-17, com erros no meio e nas pontas da palavra).
    assert medida["erros_total"] >= 340


def test_nenhuma_sugestao_unica_errada(medida: dict[str, Any]) -> None:
    # A regra mais importante: com uma só sugestão o agente segue com ela.
    assert medida["erros"]["1 sugestão errada"] == 0, medida["exemplos"].get("1 sugestão errada")
    assert medida["erros"]["várias, sem a certa"] == 0


def test_quase_todo_erro_chega_ao_animal_certo(medida: dict[str, Any]) -> None:
    certo = sum(
        medida["erros"][categoria]
        for categoria in ("achou direto", "1 sugestão certa", "várias, com a certa")
    )
    assert certo / medida["erros_total"] >= 0.95
    assert medida["erros"]["nada"] <= 5, medida["exemplos"].get("nada")


@pytest.mark.parametrize(
    "tipo", ["falta letra", "letras trocadas", "letra dobrada", "troca de som"]
)
def test_cada_tipo_de_erro_e_coberto(medida: dict[str, Any], tipo: str) -> None:
    contagem = medida["por_tipo"][tipo]
    total = sum(contagem.values())
    assert total >= 30
    assert (contagem["1 sugestão certa"] + contagem["várias, com a certa"]) / total >= 0.9


# --- metas sobre nomes que não existem no rebanho ------------------------------------


def test_nomes_fora_do_rebanho_raramente_viram_outra_vaca(medida: dict[str, Any]) -> None:
    # Pela semelhança, "Caramela" e "Caramelo" são indistinguíveis de um erro de digitação; o
    # agente avisa "considerei a Caramelo". A meta impede que isso piore. Ela está na borda: dá
    # exatamente 4 nas sementes 42, 7 e 2024, e 5 na semente 3, que não está nos testes
    # (registrado no ADR 0005). Um nome novo no gerador pode quebrá-la.
    assert medida["fora_total"] >= 35
    assert len(medida["fora_assumidos"]) <= 4, medida["fora_assumidos"]


def test_nome_curto_que_nao_existe_nao_vira_outra_vaca_na_semente_42(
    conn: sqlite3.Connection,
) -> None:
    # Vale só para a semente 42. Em outras, isso acontece: "Luna" vira Lua (semente 3), "Dita"
    # vira Chita (7), "Rosa" vira Romã (2024). É o risco aceito no ADR 0005, protegido pelo aviso
    # na resposta; a meta geral é a de no máximo 4 nomes inexistentes assumidos.
    curtos = [n for n in nomes_fora_do_rebanho(conn) if len(n) <= 4]
    assert len(curtos) >= 8
    for nome in curtos:
        # Várias sugestões são aceitáveis (o agente pergunta). Uma só vira `nome_considerado`,
        # e o agente assumiria a vaca. (Antes da revisão, este teste olhava `sugestoes`, que
        # nunca tem um nome só no contrato novo, e passava sem testar nada.)
        resultado = listar_animais(conn, nome=nome)
        assert resultado["nome_considerado"] is None, (
            f"{nome} viraria {resultado['nome_considerado']}"
        )
        # (Achar por trecho é outra coisa: "Ana" está dentro de "Cigana" e volta como achado
        # direto, como "mel" em "Caramelo"; isso é medido em "achou outro".)


@pytest.mark.parametrize("semente", [1, 7, 2024])
def test_metas_de_seguranca_valem_em_sementes_nao_usadas_para_escolher_a_regra(
    semente: int,
) -> None:
    conexao = criar_banco_em_memoria()
    try:
        gravar_dados(conexao, gerar_dados(semente))
        outra = medir(conexao)
    finally:
        conexao.close()
    assert outra["erros"]["1 sugestão errada"] == 0, outra["exemplos"].get("1 sugestão errada")
    assert outra["erros"]["várias, sem a certa"] == 0
    assert len(outra["fora_assumidos"]) <= 4, outra["fora_assumidos"]


def test_animal_de_nome_instrucao_nunca_e_sugerido(conn: sqlite3.Connection) -> None:
    for nome in nomes_fora_do_rebanho(conn):
        resultado = listar_animais(conn, nome=nome)
        assert NOME_INSTRUCAO not in resultado["sugestoes"]
        assert resultado["nome_considerado"] != NOME_INSTRUCAO
        assert all(a["nome"] != NOME_INSTRUCAO for a in resultado["animais"])
