"""Testes do laço do agente, com um cliente falso (sem rede e sem chave de API)."""

import re
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

import pytest

from app import agente
from app.agente import (
    MAX_PASSOS,
    MENSAGEM_SEM_CONFIRMACAO,
    MENSAGEM_SEM_RESPOSTA,
    carregar_prompt,
    montar_prompt,
    responder,
)
from app.db.connection import criar_banco_em_memoria
from app.db.seed import NOME_INSTRUCAO, gerar_dados, gravar_dados
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
    assert instrucoes == montar_prompt(conn)  # o prompt do arquivo, com as datas do banco
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
    assert (
        "Não ignore o outro assunto em silêncio" in prompt
    )  # pedido misto: recusar a parte fora do assunto
    assert "Você não lembra de conversas anteriores" in prompt  # o laço atual é de uma só pergunta


def test_prompt_de_sistema_existe_e_traz_as_regras_principais() -> None:
    prompt = " ".join(carregar_prompt().split())
    assert "Nunca invente" in prompt  # números só vêm das ferramentas
    assert "litros" in prompt
    assert "Segurança" in prompt  # texto vindo dos dados não é ordem (prompt injection)
    assert "ainda **não** consegue" in prompt  # admite os limites em vez de inventar


def _secao_ainda_nao_consegue(prompt: str) -> str:
    inicio = prompt.index("Você ainda **não** consegue")
    return prompt[inicio : prompt.index("## Como achar o animal")]


def test_prompt_nao_promete_o_que_as_ferramentas_ainda_nao_fazem() -> None:
    prompt = " ".join(carregar_prompt().split())
    ainda_nao = _secao_ainda_nao_consegue(prompt)
    assert "produzem menos" in ainda_nao  # animais_abaixo_da_media ainda não existe
    assert "pelo número de identificação" not in prompt
    assert "nunca deve pedi-lo" in prompt  # o produtor não conhece o id do animal


def test_prompt_traz_as_regras_de_nome_data_e_sem_registro() -> None:
    prompt = " ".join(carregar_prompt().split())
    assert "sempre pergunte qual" in prompt  # nome que casa com mais de um animal
    assert "Você quis dizer" in prompt  # erro de digitação com mais de uma sugestão
    assert "`nome_considerado`" in prompt  # uma sugestão: a busca já trouxe o animal
    assert "**não escolha nenhuma**" in prompt  # várias sugestões: pergunta
    assert "considerei a Mimosa" in prompt
    assert "**Pedido misturado.**" in prompt  # a regra fica junto de "Fora do assunto"
    assert "incluindo os que saíram da fazenda" in prompt  # tenta de novo com inativos
    assert 'nunca "0 litros"' in prompt  # sem registro não é zero
    assert "**manhã**" in prompt and "**tarde**" in prompt  # pergunta de um dia
    assert "não seja depois" in prompt  # data sem ano
    assert "diga as datas que usou" in prompt  # semana passada, mês passado


def test_prompt_nao_tem_exemplo_que_puxa_numero_inventado() -> None:
    # Com a regra "a primeira frase recusa o outro assunto", o modelo respondia de uma vez,
    # sem chamar a ferramenta, e inventava os litros (evals de 2026-11-17). Tirar o exemplo
    # que terminava em "o rebanho produziu..." não bastou; a regra agora manda consultar antes
    # de escrever. Quem garante de fato é a trava do laço (ADR 0008), não este texto.
    prompt = " ".join(carregar_prompt().split())
    assert "produziu..." not in prompt
    assert "Nunca escreva uma quantidade de litros sem ter chamado a ferramenta" in prompt
    assert "**Primeiro, chame a ferramenta** da parte da fazenda" in prompt


def test_prompt_so_tem_marcadores_conhecidos() -> None:
    marcadores = set(re.findall(r"\{\{(\w+)\}\}", carregar_prompt()))
    assert marcadores == {
        "ultimo_dia",
        "ultimo_dia_br",
        "dia_da_semana",
        "primeiro_dia_br",
        "ontem",
        "ontem_br",
        "anteontem",
        "anteontem_br",
    }


def test_montar_prompt_preenche_as_datas_do_banco(conn: sqlite3.Connection) -> None:
    prompt = montar_prompt(conn)
    assert "{{" not in prompt
    assert "15/11/2026" in prompt  # o dia mais recente do banco do gerador
    assert "domingo" in prompt  # 15/11/2026 caiu num domingo
    assert "18/08/2026" in prompt  # o primeiro dia com registro
    assert "2026-11-15" in prompt  # formato que as ferramentas esperam
    # "Ontem" e "anteontem" vão prontos, para o modelo não fazer a conta (evals de 2026-11-17).
    texto = " ".join(prompt.split())
    assert '"ontem" = 14/11/2026 (nas ferramentas: 2026-11-14)' in texto
    assert '"anteontem" = 13/11/2026 (nas ferramentas: 2026-11-13)' in texto


def test_ontem_atravessa_a_virada_do_mes_e_do_ano() -> None:
    banco = criar_banco_em_memoria()
    try:
        banco.execute(
            "INSERT INTO animais (id, nome, sexo, raca, data_nascimento, status, lote, ativo)"
            " VALUES (1, 'Mimosa', 'F', 'holandesa', '2020-03-10', 'lactacao', 'alta_producao', 1)"
        )
        banco.execute(
            "INSERT INTO producao_leite (animal_id, data, litros_manha, litros_tarde)"
            " VALUES (1, '2027-01-01', 10, 8)"
        )
        texto = " ".join(montar_prompt(banco).split())
        assert '"ontem" = 31/12/2026 (nas ferramentas: 2026-12-31)' in texto
        assert '"anteontem" = 30/12/2026' in texto
    finally:
        banco.close()


def test_montar_prompt_informa_o_dia_da_semana_certo() -> None:
    banco = criar_banco_em_memoria()
    try:
        banco.execute(
            "INSERT INTO animais (id, nome, sexo, raca, data_nascimento, status, lote, ativo)"
            " VALUES (1, 'Mimosa', 'F', 'holandesa', '2020-03-10', 'lactacao', 'alta_producao', 1)"
        )
        banco.execute(
            "INSERT INTO producao_leite (animal_id, data, litros_manha, litros_tarde)"
            " VALUES (1, '2026-11-16', 10, 8)"
        )
        prompt = montar_prompt(banco)
        assert "segunda-feira" in prompt
        assert "16/11/2026" in prompt
    finally:
        banco.close()


def test_montar_prompt_com_banco_sem_producao_nao_quebra() -> None:
    banco = criar_banco_em_memoria()
    try:
        prompt = montar_prompt(banco)
        assert "sem registros" in prompt
        assert "{{" not in prompt
    finally:
        banco.close()


def test_montar_prompt_nunca_leva_texto_dos_dados_como_o_nome_de_um_animal(
    conn: sqlite3.Connection,
) -> None:
    # O prompt de sistema só recebe datas. Nomes de animais (que podem parecer instruções)
    # chegam ao modelo apenas como resultado de ferramenta.
    assert NOME_INSTRUCAO not in montar_prompt(conn)


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


# --- Trava de fidelidade (ADR 0008): litros sem origem em ferramenta não são entregues ---

INVENTADA = "Sobre a relatividade eu não posso ajudar. O rebanho produziu 136.216,1 litros."


def _total_dos_30_dias(conn: sqlite3.Connection) -> str:
    """O total real dos últimos 30 dias, escrito como o agente escreveria (19.639,6)."""
    litros = executar_ferramenta(conn, "producao_por_periodo", {"dias": 30})["litros_total"]
    return f"{litros:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")


def test_litros_inventados_sem_ferramenta_sao_devolvidos_ao_modelo(
    conn: sqlite3.Connection,
) -> None:
    certa = f"Sobre a relatividade eu não posso ajudar. Foram {_total_dos_30_dias(conn)} litros."
    cliente = ClienteFalso([fala(INVENTADA), pede("producao_por_periodo", dias=30), fala(certa)])
    resposta = responder("produção de 30 dias e a relatividade", conn, cliente)
    assert resposta.texto == certa
    assert resposta.completa is True
    assert len(resposta.barradas) == 1
    assert [c.nome for c in resposta.chamadas] == ["producao_por_periodo"]
    # O pedido de correção vem do arquivo de prompt e chega ao modelo como mensagem.
    correcao = cliente.recebido[1][1][-1]
    assert correcao == Mensagem(papel="usuario", texto=carregar_prompt("correcao_litros"))
    assert "136.216,1" not in resposta.texto
    assert resposta.barradas == (INVENTADA,)  # o texto barrado fica guardado para as evals


def test_modelo_que_insiste_em_inventar_recebe_a_mensagem_sem_numeros(
    conn: sqlite3.Connection,
) -> None:
    cliente = ClienteFalso([fala(INVENTADA), fala(INVENTADA)])
    resposta = responder("produção de 30 dias e a relatividade", conn, cliente)
    assert resposta.texto == MENSAGEM_SEM_CONFIRMACAO
    assert not re.search(r"\d", resposta.texto)
    assert resposta.completa is False
    assert resposta.barradas == (INVENTADA, INVENTADA)  # as duas tentativas ficam guardadas
    assert len(cliente.recebido) == 2  # um pedido de correção só, sem laço infinito


def test_resposta_fiel_nao_e_tocada_pela_trava(conn: sqlite3.Connection) -> None:
    certa = f"Nos últimos 30 dias o rebanho produziu {_total_dos_30_dias(conn)} litros."
    cliente = ClienteFalso([pede("producao_por_periodo", dias=30), fala(certa)])
    resposta = responder("produção dos últimos 30 dias", conn, cliente)
    assert resposta.texto == certa
    assert len(resposta.barradas) == 0
    assert len(cliente.recebido) == 2  # nenhuma chamada a mais ao modelo


def test_resposta_sem_litros_nao_aciona_a_trava(conn: sqlite3.Connection) -> None:
    cliente = ClienteFalso([fala("Qual delas? A Caramelo ou a Mel? Há registros até 15/11/2026.")])
    resposta = responder("quanto a mel produziu", conn, cliente)
    assert len(resposta.barradas) == 0
    assert resposta.completa is True


def test_trava_pega_numero_diferente_do_que_a_ferramenta_devolveu(
    conn: sqlite3.Connection,
) -> None:
    cliente = ClienteFalso(
        [pede("producao_por_periodo", dias=30), fala("Foram 99.999,9 litros."), fala("Foram 1 L.")]
    )
    resposta = responder("produção dos últimos 30 dias", conn, cliente)
    assert resposta.texto == MENSAGEM_SEM_CONFIRMACAO
    assert resposta.barradas == ("Foram 99.999,9 litros.", "Foram 1 L.")


def test_numero_que_a_pessoa_escreveu_na_pergunta_nao_e_invencao(
    conn: sqlite3.Connection,
) -> None:
    texto = "Ainda não consigo dizer quais vacas dão menos de 10 litros."
    cliente = ClienteFalso([fala(texto)])
    resposta = responder("quais vacas dão menos de 10 litros?", conn, cliente)
    assert resposta.texto == texto
    assert len(resposta.barradas) == 0


def test_numero_de_dias_da_pergunta_nao_autoriza_litros(conn: sqlite3.Connection) -> None:
    # Antes, qualquer número da pergunta era aceito: "7 dias" deixava passar "7 litros".
    cliente = ClienteFalso([fala("Foram 7 litros."), fala("Foram 7 litros.")])
    resposta = responder("produção dos últimos 7 dias", conn, cliente)
    assert resposta.texto == MENSAGEM_SEM_CONFIRMACAO


def test_correcao_no_ultimo_passo_termina_sem_resposta(conn: sqlite3.Connection) -> None:
    cliente = ClienteFalso([fala(INVENTADA)])
    resposta = responder("produção e relatividade", conn, cliente, max_passos=1)
    assert resposta.texto == MENSAGEM_SEM_RESPOSTA
    assert resposta.completa is False
    assert len(resposta.barradas) == 1
