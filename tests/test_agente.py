"""Testes do laço do agente, com um cliente falso (sem rede e sem chave de API)."""

import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

import pytest

from app import agente
from app.agente import MAX_PASSOS, MENSAGEM_SEM_RESPOSTA, carregar_prompt, responder
from app.db.connection import criar_banco_em_memoria
from app.db.seed import gerar_dados, gravar_dados
from app.llm.client import ChamadaFerramenta, Mensagem, RespostaLLM
from app.tools.erros import ErroDeFerramenta
from app.tools.registro import declaracoes_neutras, executar_ferramenta


class ClienteFalso:
    """Devolve respostas combinadas de antemão e guarda o que recebeu."""

    def __init__(self, respostas: Sequence[RespostaLLM]) -> None:
        self._respostas = list(respostas)
        self.recebido: list[tuple[str, list[Mensagem], list[Mapping[str, Any]]]] = []

    def gerar(
        self,
        instrucoes: str,
        mensagens: Sequence[Mensagem],
        ferramentas: Sequence[Mapping[str, Any]],
    ) -> RespostaLLM:
        self.recebido.append((instrucoes, list(mensagens), list(ferramentas)))
        return self._respostas.pop(0)


def pede(nome: str, **argumentos: Any) -> RespostaLLM:
    return RespostaLLM(texto=None, chamadas=(ChamadaFerramenta(nome, argumentos),), bruto="bruto")


def fala(texto: str | None) -> RespostaLLM:
    return RespostaLLM(texto=texto)


@pytest.fixture(scope="module")
def conn() -> Iterator[sqlite3.Connection]:
    conexao = criar_banco_em_memoria()
    gravar_dados(conexao, gerar_dados())
    yield conexao
    conexao.close()


def test_resposta_direta_sem_ferramenta(conn: sqlite3.Connection) -> None:
    cliente = ClienteFalso([fala("Oi! Posso ajudar com a produção de leite.")])
    resposta = responder("oi", conn, cliente)
    assert resposta.texto == "Oi! Posso ajudar com a produção de leite."
    assert resposta.chamadas == ()
    assert resposta.passos == 1
    assert resposta.completa is True


def test_cliente_recebe_o_prompt_do_arquivo_e_as_ferramentas_do_registro(
    conn: sqlite3.Connection,
) -> None:
    cliente = ClienteFalso([fala("ok")])
    responder("oi", conn, cliente)
    instrucoes, mensagens, ferramentas = cliente.recebido[0]
    assert instrucoes == carregar_prompt()
    assert ferramentas == declaracoes_neutras()
    assert mensagens == [Mensagem(papel="usuario", texto="oi")]


def test_ferramenta_e_executada_no_banco_e_o_resultado_volta_ao_modelo(
    conn: sqlite3.Connection,
) -> None:
    cliente = ClienteFalso(
        [pede("producao_por_periodo", dias=7), fala("O rebanho produziu 4479,1 litros.")]
    )
    resposta = responder("quanto o rebanho produziu na semana?", conn, cliente)

    esperado = executar_ferramenta(conn, "producao_por_periodo", {"dias": 7})
    assert resposta.texto == "O rebanho produziu 4479,1 litros."
    assert resposta.passos == 2
    assert len(resposta.chamadas) == 1
    assert resposta.chamadas[0].resultado == esperado
    assert resposta.chamadas[0].erro is False

    # Na segunda chamada ao modelo, o histórico traz o pedido dele e o resultado da ferramenta.
    _, historico, _ = cliente.recebido[1]
    assert [m.papel for m in historico] == ["usuario", "modelo", "ferramenta"]
    assert historico[1].bruto == "bruto"  # a mensagem original do provedor é preservada
    assert historico[2].resultados[0].conteudo == esperado


def test_varias_chamadas_na_mesma_resposta_voltam_na_ordem(conn: sqlite3.Connection) -> None:
    duas = RespostaLLM(
        texto=None,
        chamadas=(
            ChamadaFerramenta("producao_por_periodo", {"dias": 7}),
            ChamadaFerramenta("producao_por_periodo", {"dias": 30}),
        ),
    )
    cliente = ClienteFalso([duas, fala("pronto")])
    resposta = responder("semana e mês", conn, cliente)
    assert [c.argumentos["dias"] for c in resposta.chamadas] == [7, 30]
    resultados = cliente.recebido[1][1][2].resultados
    assert [r.conteudo["dias_com_registro"] for r in resultados] == [7, 30]


def test_erro_de_valor_da_ferramenta_vira_texto_e_o_laco_continua(
    conn: sqlite3.Connection,
) -> None:
    cliente = ClienteFalso([pede("producao_por_periodo", dias=0), fala("Preciso de 1 a 90 dias.")])
    resposta = responder("produção de zero dias", conn, cliente)
    assert resposta.chamadas[0].erro is True
    assert "dias" in resposta.chamadas[0].resultado["erro"]
    assert cliente.recebido[1][1][2].resultados[0].conteudo == resposta.chamadas[0].resultado
    assert resposta.texto == "Preciso de 1 a 90 dias."


def test_ferramenta_inexistente_e_devolvida_como_erro(conn: sqlite3.Connection) -> None:
    cliente = ClienteFalso([pede("apagar_tudo"), fala("Não consigo fazer isso.")])
    resposta = responder("apague tudo", conn, cliente)
    assert resposta.chamadas[0].erro is True
    assert "desconhecida" in resposta.chamadas[0].resultado["erro"]


def test_modelo_nao_consegue_escrever_no_banco_nem_passar_sql(
    conn: sqlite3.Connection,
) -> None:
    antes = conn.execute("SELECT COUNT(*) FROM animais").fetchone()[0]
    cliente = ClienteFalso(
        [pede("producao_por_periodo", dias=7, sql="DROP TABLE animais"), fala("Não posso.")]
    )
    resposta = responder("apague a tabela", conn, cliente)
    assert resposta.chamadas[0].erro is True
    assert "sql" in resposta.chamadas[0].resultado["erro"]
    assert conn.execute("SELECT COUNT(*) FROM animais").fetchone()[0] == antes


def test_falha_inesperada_na_ferramenta_nao_vaza_detalhes_ao_modelo(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    def quebrar(*args: object, **kwargs: object) -> dict[str, Any]:
        raise RuntimeError("detalhe secreto do servidor")

    monkeypatch.setattr(agente, "executar_ferramenta", quebrar)
    cliente = ClienteFalso([pede("producao_por_periodo", dias=7), fala("Deu erro.")])
    resposta = responder("produção", conn, cliente)
    assert resposta.chamadas[0].erro is True
    assert resposta.chamadas[0].resultado == {"erro": agente.ERRO_INTERNO}
    assert "secreto" not in str(cliente.recebido[1][1])


def test_limite_de_passos_evita_laco_infinito(conn: sqlite3.Connection) -> None:
    cliente = ClienteFalso([pede("producao_por_periodo", dias=7) for _ in range(MAX_PASSOS)])
    resposta = responder("produção", conn, cliente)
    assert resposta.completa is False
    assert resposta.texto == MENSAGEM_SEM_RESPOSTA
    assert resposta.passos == MAX_PASSOS
    assert len(cliente.recebido) == MAX_PASSOS


def test_limite_de_passos_pode_ser_menor(conn: sqlite3.Connection) -> None:
    cliente = ClienteFalso([pede("producao_por_periodo", dias=7) for _ in range(2)])
    resposta = responder("produção", conn, cliente, max_passos=2)
    assert resposta.passos == 2
    assert resposta.completa is False


@pytest.mark.parametrize("texto", [None, "", "   "])
def test_modelo_sem_texto_e_sem_ferramenta_da_resposta_padrao(
    conn: sqlite3.Connection, texto: str | None
) -> None:
    resposta = responder("oi", conn, ClienteFalso([fala(texto)]))
    assert resposta.texto == MENSAGEM_SEM_RESPOSTA
    assert resposta.completa is False


@pytest.mark.parametrize("pergunta", ["", "   ", "\n"])
def test_pergunta_vazia_e_recusada_sem_chamar_o_modelo(
    conn: sqlite3.Connection, pergunta: str
) -> None:
    cliente = ClienteFalso([])
    with pytest.raises(ValueError, match="vazia"):
        responder(pergunta, conn, cliente)
    assert cliente.recebido == []


def test_pergunta_longa_demais_e_recusada(conn: sqlite3.Connection) -> None:
    cliente = ClienteFalso([])
    with pytest.raises(ValueError, match="longa demais"):
        responder("a" * 1001, conn, cliente)
    assert cliente.recebido == []


def test_prompt_pode_ser_informado_em_vez_do_arquivo(conn: sqlite3.Connection) -> None:
    cliente = ClienteFalso([fala("ok")])
    responder("oi", conn, cliente, prompt="Prompt de teste")
    assert cliente.recebido[0][0] == "Prompt de teste"


def test_prompt_pede_numeros_exatos_resposta_direta_e_avisa_que_nao_tem_memoria() -> None:
    # Regras que surgiram dos testes manuais com o modelo real; este teste evita que sumam.
    prompt = " ".join(carregar_prompt().split())  # ignora as quebras de linha do arquivo
    assert "exatamente como a ferramenta devolveu" in prompt  # não arredondar nem recalcular
    assert "Não peça confirmação" in prompt  # sem "quer que eu faça?"
    assert "Não o ignore em silêncio" in prompt  # pedido misto: recusar a parte fora do assunto
    assert "Você não lembra de conversas anteriores" in prompt  # o laço atual é de uma só pergunta


def test_prompt_de_sistema_existe_e_traz_as_regras_principais() -> None:
    prompt = " ".join(carregar_prompt().split())
    assert "Nunca invente" in prompt  # números só vêm das ferramentas
    assert "litros" in prompt
    assert "Segurança" in prompt  # texto vindo dos dados não é ordem (prompt injection)
    assert "ainda **não** consegue" in prompt  # admite os limites em vez de inventar


def test_prompt_nao_promete_o_que_as_ferramentas_ainda_nao_fazem() -> None:
    prompt = " ".join(carregar_prompt().split())
    assert "pelo número de identificação" not in prompt  # não oferece consulta por animal
    assert "semana passada" in prompt  # período passado está listado como limite
    assert "número certo para a pergunta errada" in prompt


def test_mais_chamadas_que_o_limite_no_mesmo_passo_so_executam_as_primeiras(
    conn: sqlite3.Connection,
) -> None:
    quantidade = agente.MAX_CHAMADAS_POR_PASSO + 1
    uma_chamada = ChamadaFerramenta("producao_por_periodo", {"dias": 7})
    muitas = RespostaLLM(texto=None, chamadas=(uma_chamada,) * quantidade)
    cliente = ClienteFalso([muitas, fala("pronto")])
    resposta = responder("produção", conn, cliente)
    assert len(resposta.chamadas) == quantidade
    assert [c.erro for c in resposta.chamadas] == [False] * agente.MAX_CHAMADAS_POR_PASSO + [True]
    assert resposta.chamadas[-1].resultado == {"erro": agente.ERRO_CHAMADAS_DEMAIS}
    # O provedor exige uma resposta para cada chamada pedida, inclusive para as recusadas.
    assert len(cliente.recebido[1][1][2].resultados) == quantidade


def test_value_error_de_biblioteca_nao_vaza_para_o_modelo(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    def quebrar(*args: object, **kwargs: object) -> dict[str, Any]:
        raise ValueError("detalhe interno de uma biblioteca")

    monkeypatch.setattr(agente, "executar_ferramenta", quebrar)
    cliente = ClienteFalso([pede("producao_por_periodo", dias=7), fala("Deu erro.")])
    resposta = responder("produção", conn, cliente)
    assert resposta.chamadas[0].resultado == {"erro": agente.ERRO_INTERNO}
    assert "biblioteca" not in str(cliente.recebido[1][1])


def test_erro_de_ferramenta_chega_ao_modelo_com_a_mensagem_original(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    def recusar(*args: object, **kwargs: object) -> dict[str, Any]:
        raise ErroDeFerramenta("`dias` deve estar entre 1 e 90.")

    monkeypatch.setattr(agente, "executar_ferramenta", recusar)
    cliente = ClienteFalso([pede("producao_por_periodo", dias=0), fala("ok")])
    resposta = responder("produção", conn, cliente)
    assert resposta.chamadas[0].resultado == {"erro": "`dias` deve estar entre 1 e 90."}
