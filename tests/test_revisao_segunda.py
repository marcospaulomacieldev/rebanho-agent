"""Testes dos ajustes pedidos na revisão dos blocos de período, animais, interface e evals."""

import json
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import errors

from app.db.connection import criar_banco_em_memoria
from app.db.seed import gerar_dados, gravar_dados
from app.llm.client import (
    ChamadaFerramenta,
    ClienteGemini,
    ErroDeConexao,
    ErroLLM,
    Mensagem,
    RespostaLLM,
)
from app.tools.animais import listar_animais
from app.tools.erros import ErroDeFerramenta
from app.tools.periodo import resolver_periodo
from app.tools.producao import producao_por_periodo
from evals.casos import Caso, Chamada
from evals.checagens import numeros_do_texto
from evals.cliente import ClienteComEspera
from evals.executor import Bancos, executar, falha_de_infraestrutura, resumir
from evals.run import main


@pytest.fixture(scope="module")
def conn() -> Iterator[sqlite3.Connection]:
    conexao = criar_banco_em_memoria()
    gravar_dados(conexao, gerar_dados())
    yield conexao
    conexao.close()


@pytest.fixture(scope="module")
def bancos() -> Iterator[Bancos]:
    with Bancos() as abertos:
        yield abertos


# --- cliente: código do erro e erro de conexão ---------------------------------------


def _sdk_que_falha(erro: Exception) -> SimpleNamespace:
    def gerar_conteudo(**kwargs: Any) -> Any:
        raise erro

    return SimpleNamespace(models=SimpleNamespace(generate_content=gerar_conteudo))


def test_erro_da_api_leva_o_codigo_para_o_erro_llm() -> None:
    corpo = {"error": {"code": 429, "message": "cota", "status": "RESOURCE_EXHAUSTED"}}
    cliente = ClienteGemini(sdk=_sdk_que_falha(errors.ClientError(429, corpo)))
    with pytest.raises(ErroLLM) as info:
        cliente.gerar("x", [Mensagem(papel="usuario", texto="oi")], [])
    assert info.value.codigo == 429
    assert not isinstance(info.value, ErroDeConexao)


def test_falha_de_rede_e_erro_de_conexao_sem_codigo() -> None:
    cliente = ClienteGemini(sdk=_sdk_que_falha(ConnectionError("sem rede")))
    with pytest.raises(ErroDeConexao) as info:
        cliente.gerar("x", [Mensagem(papel="usuario", texto="oi")], [])
    assert info.value.codigo is None


@pytest.mark.parametrize(
    ("erro", "infra"),
    [
        (ErroDeConexao("sem rede"), True),
        (ErroLLM("limite", codigo=429), True),
        (ErroLLM("sobrecarga", codigo=503), True),
        (ErroLLM("chave recusada", codigo=403), True),
        (ErroLLM("pedido inválido", codigo=400), False),
        (ErroLLM("O modelo não devolveu resposta (pode ter sido bloqueada)."), False),
    ],
)
def test_classificacao_de_falha_de_infraestrutura(erro: ErroLLM, infra: bool) -> None:
    assert falha_de_infraestrutura(erro) is infra


# --- período -------------------------------------------------------------------------


def test_data_com_espacos_nas_pontas_e_aceita(conn: sqlite3.Connection) -> None:
    com_espaco = producao_por_periodo(conn, data_inicio=" 2026-11-10 ", data_fim="2026-11-10\n")
    assert com_espaco == producao_por_periodo(conn, data_inicio="2026-11-10", data_fim="2026-11-10")


def test_data_com_digitos_que_nao_sao_ascii_pede_o_formato(conn: sqlite3.Connection) -> None:
    with pytest.raises(ErroDeFerramenta, match="formato AAAA-MM-DD"):
        producao_por_periodo(conn, data_inicio="٢٠٢٦-١٠-٢١", data_fim="2026-10-21")


def test_dias_padrao_vale_quando_nenhum_modo_e_informado(conn: sqlite3.Connection) -> None:
    periodo = resolver_periodo(conn, dias_padrao=7)
    assert periodo is not None
    assert (periodo.data_inicio.isoformat(), periodo.data_fim.isoformat()) == (
        "2026-11-09",
        "2026-11-15",
    )
    assert resolver_periodo(conn, dias=3, dias_padrao=7) == resolver_periodo(conn, dias=3)


# --- listar_animais ------------------------------------------------------------------


def test_animal_inativo_nao_gera_sugestao_enganosa(conn: sqlite3.Connection) -> None:
    # A Dona foi vendida. Antes, a busca só entre ativos sugeria "Onça" e "Bonita".
    resultado = listar_animais(conn, nome="dona")
    assert resultado["total"] == 0
    assert resultado["sugestoes"] == []
    assert resultado["encontrados_entre_inativos"] == 1
    com_inativos = listar_animais(conn, nome="dona", incluir_inativos=True)
    assert com_inativos["total"] == 1
    assert com_inativos["encontrados_entre_inativos"] == 0


def test_erro_de_digitacao_continua_sugerindo_quando_nao_ha_inativo(
    conn: sqlite3.Connection,
) -> None:
    resultado = listar_animais(conn, nome="mimoza")
    assert resultado["sugestoes"] == ["Mimosa"]
    assert resultado["encontrados_entre_inativos"] == 0


def test_mensagem_de_filtro_invalido_tem_tamanho_limitado(conn: sqlite3.Connection) -> None:
    with pytest.raises(ErroDeFerramenta) as info:
        listar_animais(conn, status="x" * 100_000)
    assert len(str(info.value)) < 300


# --- checagens -----------------------------------------------------------------------


def test_numero_de_data_nao_conta_como_valor() -> None:
    numeros = numeros_do_texto("Em 17/11/2026 e em 09/11 foram 18,8 litros.")
    assert Decimal("18.8") in numeros
    assert not {Decimal("17"), Decimal("11"), Decimal("2026"), Decimal("9")} & numeros


# --- executor ------------------------------------------------------------------------


class ClienteRoteiro:
    modelo = "modelo-falso"

    def __init__(self, roteiro: Any) -> None:
        self._roteiro = roteiro

    def gerar(
        self,
        instrucoes: str,
        mensagens: Sequence[Mensagem],
        ferramentas: Sequence[Mapping[str, Any]],
    ) -> RespostaLLM:
        return self._roteiro(mensagens)


def agente_certo(mensagens: Sequence[Mensagem]) -> RespostaLLM:
    ultima = mensagens[-1]
    if ultima.papel == "usuario":
        return RespostaLLM(None, (ChamadaFerramenta("producao_por_periodo", {"dias": 7}),))
    total = ultima.resultados[0].conteudo["litros_total"]
    return RespostaLLM(f"O rebanho produziu {str(total).replace('.', ',')} litros.")


CASO = Caso(
    id="semana",
    semente=42,
    perguntas=("produção da semana", "quanto deu essa semana"),
    chamadas_esperadas=(Chamada("producao_por_periodo", {"dias": 7}),),
    chamadas_proibidas=(),
    valor_esperado={"litros_total": 4479.1},
    numeros_na_resposta=("litros_total",),
    resposta_contem=(),
    resposta_nao_contem=(),
    sem_litros_na_resposta=False,
    arquivo="teste.json",
)


def com_espera(roteiro: Any, **opcoes: Any) -> ClienteComEspera:
    return ClienteComEspera(ClienteRoteiro(roteiro), dormir=lambda s: None, **opcoes)


def test_resposta_bloqueada_conta_como_reprovacao_e_nao_some_das_taxas(bancos: Bancos) -> None:
    def roteiro(mensagens: Sequence[Mensagem]) -> RespostaLLM:
        raise ErroLLM("O modelo não devolveu resposta (pode ter sido bloqueada).")

    rodada = executar([CASO], com_espera(roteiro), bancos, repeticoes=2)
    assert len(rodada.execucoes) == 4  # não interrompe: não é falha de infraestrutura
    assert rodada.interrompida is None
    assert all(e.executada and e.passou is False for e in rodada.execucoes)
    resumo = resumir([CASO], rodada)
    assert resumo["execucoes_nao_executadas"] == 0
    assert resumo["metricas"]["execucao_aprovada"] == {"acertos": 0, "total": 4, "taxa": 0.0}
    assert resumo["metricas"]["ferramenta"]["total"] == 0  # nada foi checado nessas execuções


def test_variante_nao_executada_tira_o_caso_da_consistencia(bancos: Bancos) -> None:
    def roteiro(mensagens: Sequence[Mensagem]) -> RespostaLLM:
        if "quanto deu" in (mensagens[0].texto or ""):
            raise ErroLLM("limite", codigo=429)
        return agente_certo(mensagens)

    rodada = executar([CASO], com_espera(roteiro, esperas=()), bancos, repeticoes=1)
    resumo = resumir([CASO], rodada)
    assert resumo["execucoes_validas"] == 1
    assert resumo["metricas"]["consistencia_entre_variantes"]["total"] == 0


def test_ctrl_c_devolve_o_que_ja_foi_medido(bancos: Bancos) -> None:
    perguntas = {"n": 0}

    def roteiro(mensagens: Sequence[Mensagem]) -> RespostaLLM:
        if mensagens[-1].papel == "usuario":
            perguntas["n"] += 1
            if perguntas["n"] == 2:
                raise KeyboardInterrupt
        return agente_certo(mensagens)

    rodada = executar([CASO], com_espera(roteiro), bancos, repeticoes=2)
    assert len(rodada.execucoes) == 1
    assert "Ctrl+C" in (rodada.interrompida or "")


def test_chamadas_a_mais_sao_contadas(bancos: Bancos) -> None:
    def roteiro(mensagens: Sequence[Mensagem]) -> RespostaLLM:
        if mensagens[-1].papel == "usuario":
            return RespostaLLM(None, (ChamadaFerramenta("listar_animais", {"nome": "mimosa"}),))
        if len(mensagens) == 3:
            return RespostaLLM(None, (ChamadaFerramenta("producao_por_periodo", {"dias": 7}),))
        return RespostaLLM("O rebanho produziu 4.479,1 litros.")

    rodada = executar([CASO], com_espera(roteiro), bancos, repeticoes=1)
    assert [e.chamadas_a_mais for e in rodada.execucoes] == [1, 1]
    resumo = resumir([CASO], rodada)
    assert resumo["chamadas_a_mais"] == 2
    assert resumo["esperado"]["semana"] == [
        {"ferramenta": "producao_por_periodo", "argumentos": {"dias": 7}}
    ]


# --- linha de comando das evals ------------------------------------------------------

CASO_EM_ARQUIVO = {
    "id": "semana",
    "pergunta": "produção da semana",
    "chamadas_esperadas": [{"ferramenta": "producao_por_periodo", "argumentos": {"dias": 7}}],
    "valor_esperado": {"litros_total": 4479.1},
    "numeros_na_resposta": ["litros_total"],
}


def rodar(tmp_path: Path, roteiro: Any, *extras: str) -> int:
    pasta = tmp_path / "casos"
    pasta.mkdir(exist_ok=True)
    (pasta / "casos.json").write_text(json.dumps([CASO_EM_ARQUIVO]), encoding="utf-8")
    argumentos = ["--pasta-casos", str(pasta), "--saida", str(tmp_path / "saida"), *extras]
    return main(argumentos, cliente=ClienteRoteiro(roteiro), dormir=lambda s: None)


@pytest.mark.parametrize("valor", ["90", "-0.1", "1.5"])
def test_exigir_fora_de_zero_a_um_sai_com_2(tmp_path: Path, valor: str) -> None:
    assert rodar(tmp_path, agente_certo, "--exigir", valor) == 2


def test_rodada_interrompida_sai_com_1_e_grava_o_parcial(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Cada pergunta usa 2 chamadas: com teto de 3, a segunda repetição não termina.
    assert rodar(tmp_path, agente_certo, "--repeticoes", "2", "--max-chamadas", "3") == 1
    saida = capsys.readouterr().out
    assert "RODADA INTERROMPIDA" in saida
    (arquivo,) = (tmp_path / "saida").glob("*.json")
    gravado = json.loads(arquivo.read_text(encoding="utf-8"))
    assert gravado["resumo"]["execucoes_validas"] == 1
    assert gravado["metadados"]["provedor"] == "ClienteRoteiro"


def test_falha_mostra_o_que_era_esperado(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def errado(mensagens: Sequence[Mensagem]) -> RespostaLLM:
        if mensagens[-1].papel == "usuario":
            return RespostaLLM(None, (ChamadaFerramenta("producao_por_periodo", {"dias": 30}),))
        return RespostaLLM("O rebanho produziu 19.639,6 litros.")

    assert rodar(tmp_path, errado, "--repeticoes", "1") == 0
    saida = capsys.readouterr().out
    assert "esperado: producao_por_periodo({'dias': 7})" in saida
    assert "chamadas: producao_por_periodo({'dias': 30})" in saida
