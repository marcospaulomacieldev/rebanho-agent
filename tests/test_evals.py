"""Testes das evals: casos, checagens, cliente com espera, executor, relatório e linha de comando.

Tudo com cliente falso: sem rede, sem chave e sem esperar de verdade.
"""

import json
import subprocess
from collections.abc import Callable, Iterator, Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.agente import MENSAGEM_SEM_CONFIRMACAO, ChamadaExecutada, RespostaAgente
from app.fidelidade import (
    interpretar_numero,
    litros_do_texto,
    litros_dos_resultados,
    litros_sem_origem,
    numeros_do_texto,
)
from app.llm.client import ChamadaFerramenta, ErroLLM, Mensagem, RespostaLLM
from evals import relatorio as rel
from evals.casos import Caso, Chamada, ErroDeCaso, carregar_casos
from evals.checagens import (
    aprovada,
    avaliar,
    normalizar_argumentos,
)
from evals.cliente import ClienteComEspera, TetoDeChamadas
from evals.executor import (
    Bancos,
    executar,
    resultados_das_chamadas_esperadas,
    resumir,
)
from evals.run import _versao_do_codigo, main

Roteiro = Callable[[Sequence[Mensagem]], RespostaLLM]


class ClienteRoteiro:
    """Cliente falso: uma função decide a resposta a partir das mensagens recebidas."""

    modelo = "modelo-falso"

    def __init__(self, roteiro: Roteiro) -> None:
        self._roteiro = roteiro
        self.chamadas = 0

    def gerar(
        self,
        instrucoes: str,
        mensagens: Sequence[Mensagem],
        ferramentas: Sequence[Mapping[str, Any]],
    ) -> RespostaLLM:
        self.chamadas += 1
        return self._roteiro(mensagens)


def pede(nome: str, **argumentos: Any) -> RespostaLLM:
    return RespostaLLM(None, (ChamadaFerramenta(nome, argumentos),))


def agente_certo(mensagens: Sequence[Mensagem]) -> RespostaLLM:
    """Responde certo a "produção da semana": chama a ferramenta e repete o total."""
    ultima = mensagens[-1]
    if ultima.papel == "usuario":
        return pede("producao_por_periodo", dias=7)
    total = ultima.resultados[0].conteudo["litros_total"]
    return RespostaLLM(f"O rebanho produziu {str(total).replace('.', ',')} litros.")


def agente_que_inventa(mensagens: Sequence[Mensagem]) -> RespostaLLM:
    if mensagens[-1].papel == "usuario":
        return pede("producao_por_periodo", dias=7)
    return RespostaLLM("O rebanho produziu cerca de 4.500 litros.")


def caso(**campos: Any) -> Caso:
    base: dict[str, Any] = {
        "id": "caso",
        "semente": 42,
        "perguntas": ("pergunta",),
        "chamadas_esperadas": None,
        "chamadas_proibidas": (),
        "valor_esperado": {},
        "numeros_na_resposta": (),
        "resposta_contem": (),
        "resposta_nao_contem": (),
        "sem_litros_na_resposta": False,
        "arquivo": "teste.json",
    }
    base.update(campos)
    return Caso(**base)


CASO_SEMANA = caso(
    id="semana",
    perguntas=("produção da semana", "quanto deu essa semana"),
    chamadas_esperadas=(Chamada("producao_por_periodo", {"dias": 7}),),
    valor_esperado={"litros_total": 4479.1},
    numeros_na_resposta=("litros_total",),
)


@pytest.fixture(scope="module")
def bancos() -> Iterator[Bancos]:
    with Bancos() as abertos:
        yield abertos


def sem_dormir(segundos: float) -> None:
    return None


def com_espera(roteiro: Roteiro, **opcoes: Any) -> ClienteComEspera:
    return ClienteComEspera(ClienteRoteiro(roteiro), dormir=sem_dormir, **opcoes)


# --- números em português ------------------------------------------------------------


@pytest.mark.parametrize(
    ("token", "esperado"),
    [
        ("4.479,1", {"4479.1"}),
        ("18,8", {"18.8"}),
        ("18,80", {"18.8"}),
        ("639,87", {"639.87"}),
        ("4479.1", {"4479.1"}),
        ("4,479.1", {"4479.1"}),
        ("19.639,6", {"19639.6"}),
        ("7", {"7"}),
        ("4.479", {"4479", "4.479"}),  # ambíguo: as duas leituras
        ("1.234.567", {"1234567"}),
        ("1.2.3", set()),
    ],
)
def test_interpretar_numero(token: str, esperado: set[str]) -> None:
    assert interpretar_numero(token) == {Decimal(v) for v in esperado}


def test_numeros_do_texto_em_uma_resposta_real() -> None:
    texto = "A Mimosa produziu 18,8 litros em 21/10/2026: 9,8 de manhã e 9,0 de tarde."
    numeros = numeros_do_texto(texto)
    assert {Decimal("18.8"), Decimal("9.8"), Decimal("9")} <= numeros
    assert Decimal("18.7") not in numeros


def test_litros_do_texto_so_pega_numero_seguido_de_litros() -> None:
    texto = "Foram 4.479,1 litros em 7 dias, de 09/11/2026 a 15/11/2026 (639,87 L por dia)."
    assert litros_do_texto(texto) == [{Decimal("4479.1")}, {Decimal("639.87")}]
    assert litros_do_texto("Sem registro em 21/10/2026.") == []


def test_litros_sem_origem_aponta_so_o_numero_que_nao_veio_de_ferramenta() -> None:
    resultados = [{"litros_total": 18.8, "litros_media_dia": 9.4}]
    assert litros_sem_origem("Foram 18,8 litros, média de 9,4 litros.", resultados) == []
    assert litros_sem_origem("Foram 20 litros.", resultados) == [{Decimal("20")}]
    assert litros_sem_origem("Foram 20 litros.", []) == [{Decimal("20")}]
    assert litros_sem_origem("Menos de 20 litros?", [], "quais dão menos de 20 litros") == []
    # O número da pergunta só vale se estiver colado a "litros": "7 dias" não autoriza "7 L".
    assert litros_sem_origem("Foram 7 litros.", [], "produção dos últimos 7 dias") == [
        {Decimal("7")}
    ]
    # Mesmo valor escrito de formas diferentes: 18,80 e 18.8 são o mesmo número.
    assert litros_sem_origem("Foram 18,80 litros.", resultados) == []
    # "4.479" é ambíguo (quatro mil ou quatro vírgula quatro); aceito se uma das leituras bate.
    assert litros_sem_origem("Foram 4.479 litros.", [{"litros_total": 4479}]) == []
    # O valor pode vir de um resultado aninhado (lista de dias dentro do resultado).
    aninhado = [{"dias": [{"data": "2026-11-15", "litros_dia": 31.2}]}]
    assert litros_sem_origem("No dia, 31,2 litros.", aninhado) == []
    assert litros_sem_origem("Sem registro em 21/10/2026.", []) == []


def test_litros_dos_resultados_ignora_campos_que_nao_sao_de_litros() -> None:
    resultados = [
        {"litros_total": 18.8, "litros_manha_total": None, "dias_com_registro": 0},
        {"animais": [{"id": 28}], "total": 1},
    ]
    assert litros_dos_resultados(resultados) == {Decimal("18.8")}


def test_normalizar_argumentos() -> None:
    bruto = {"dias": 7.0, "animal_id": None, "nome": " Açucena ", "data_fim": "", "x": False}
    assert normalizar_argumentos(bruto) == {"dias": 7, "nome": "acucena"}
    assert normalizar_argumentos({"incluir_inativos": True}) == {"incluir_inativos": True}


# --- avaliação de uma resposta -------------------------------------------------------

RESULTADO_SEMANA = {"litros_total": 4479.1, "litros_media_dia": 639.87, "dias_com_registro": 7}


def resposta(texto: str, *chamadas: ChamadaExecutada, completa: bool = True) -> RespostaAgente:
    return RespostaAgente(texto=texto, chamadas=chamadas, passos=2, completa=completa)


def feita(nome: str, argumentos: dict[str, Any], resultado: dict[str, Any]) -> ChamadaExecutada:
    return ChamadaExecutada(nome, argumentos, resultado, erro=False)


def test_resposta_certa_passa_em_tudo() -> None:
    dada = resposta(
        "O rebanho produziu 4.479,1 litros.",
        feita("producao_por_periodo", {"dias": 7, "animal_id": None}, RESULTADO_SEMANA),
    )
    checagens = avaliar(CASO_SEMANA, dada, [RESULTADO_SEMANA])
    assert checagens == {
        "ferramenta": True,
        "argumentos_identicos": True,
        "argumentos_equivalentes": True,
        "numeros": True,
        "fidelidade": True,
        "comportamento": None,
    }
    assert aprovada(checagens, completa=True)
    assert not aprovada(checagens, completa=False)


def test_numero_reescrito_reprova_numeros_e_fidelidade() -> None:
    dada = resposta(
        "O rebanho produziu cerca de 4.500 litros.",
        feita("producao_por_periodo", {"dias": 7}, RESULTADO_SEMANA),
    )
    checagens = avaliar(CASO_SEMANA, dada, [RESULTADO_SEMANA])
    assert checagens["ferramenta"] is True
    assert checagens["numeros"] is False
    assert checagens["fidelidade"] is False
    assert not aprovada(checagens, completa=True)


def test_argumentos_diferentes_com_o_mesmo_resultado_sao_equivalentes_mas_nao_identicos() -> None:
    por_datas = {"data_inicio": "2026-11-09", "data_fim": "2026-11-15"}
    dada = resposta(
        "Foram 4.479,1 litros.", feita("producao_por_periodo", por_datas, RESULTADO_SEMANA)
    )
    checagens = avaliar(CASO_SEMANA, dada, [RESULTADO_SEMANA])
    assert checagens["argumentos_identicos"] is False
    assert checagens["argumentos_equivalentes"] is True
    assert aprovada(checagens, completa=True)


def test_argumentos_errados_reprovam() -> None:
    outro = {**RESULTADO_SEMANA, "litros_total": 19639.6}
    dada = resposta("Foram 19.639,6 litros.", feita("producao_por_periodo", {"dias": 30}, outro))
    checagens = avaliar(CASO_SEMANA, dada, [RESULTADO_SEMANA])
    assert checagens["ferramenta"] is True
    assert checagens["argumentos_equivalentes"] is False
    assert checagens["numeros"] is False


def test_sequencia_aceita_chamadas_a_mais_mas_exige_a_ordem() -> None:
    dois_passos = caso(
        chamadas_esperadas=(
            Chamada("listar_animais", {"nome": "dona", "incluir_inativos": True}),
            Chamada("producao_por_periodo", {"dias": 7, "animal_id": 56}),
        )
    )
    lista, producao = {"total": 1}, {"litros_total": 10.0}
    busca_vazia = feita("listar_animais", {"nome": "Dona"}, {"total": 0})
    busca = feita("listar_animais", {"nome": "Dona", "incluir_inativos": True}, lista)
    consulta = feita("producao_por_periodo", {"dias": 7, "animal_id": 56}, producao)
    esperados = [lista, producao]

    na_ordem = avaliar(dois_passos, resposta("ok", busca_vazia, busca, consulta), esperados)
    assert na_ordem["ferramenta"] is True
    assert na_ordem["argumentos_identicos"] is True

    fora_de_ordem = avaliar(dois_passos, resposta("ok", consulta, busca), esperados)
    assert fora_de_ordem["ferramenta"] is False

    faltando = avaliar(dois_passos, resposta("ok", busca), esperados)
    assert faltando["ferramenta"] is False


def test_lista_vazia_de_chamadas_exige_que_o_agente_nao_chame_nada() -> None:
    recusa = caso(chamadas_esperadas=(), sem_litros_na_resposta=True)
    certa = avaliar(recusa, resposta("Esse não é o meu assunto."), [])
    assert certa["ferramenta"] is True
    assert certa["comportamento"] is True
    assert certa["argumentos_equivalentes"] is None

    chamou = resposta("ok", feita("producao_por_periodo", {"dias": 7}, RESULTADO_SEMANA))
    assert avaliar(recusa, chamou, [])["ferramenta"] is False


def test_sem_chamadas_esperadas_definidas_a_sequencia_nao_e_checada() -> None:
    livre = caso(resposta_contem=(("18/08/2026",),))
    chamou = resposta(
        "Só há registros a partir de 18/08/2026.",
        feita("listar_animais", {"nome": "mimosa"}, {"total": 1}),
    )
    checagens = avaliar(livre, chamou, [])
    assert checagens["ferramenta"] is None
    assert checagens["comportamento"] is True


def test_comportamento_pergunta_de_volta() -> None:
    ambiguo = caso(
        chamadas_esperadas=(Chamada("listar_animais", {"nome": "mel"}),),
        chamadas_proibidas=("producao_por_periodo",),
        resposta_contem=(("Mel",), ("Caramelo",), ("?",)),
        sem_litros_na_resposta=True,
    )
    lista = {"total": 2}
    busca = feita("listar_animais", {"nome": "mel"}, lista)
    perguntou = resposta("Qual delas: a MEL ou a caramelo?", busca)
    assert avaliar(ambiguo, perguntou, [lista])["comportamento"] is True

    escolheu = resposta(
        "A Mel produziu 20,5 litros.",
        busca,
        feita("producao_por_periodo", {"dias": 1, "animal_id": 10}, {"litros_total": 20.5}),
    )
    assert avaliar(ambiguo, escolheu, [lista])["comportamento"] is False


def test_resposta_contem_ignora_acento_e_aceita_alternativas() -> None:
    com_alternativas = caso(
        resposta_contem=(("sem registro", "não há registro"),),
        resposta_nao_contem=("6 milhões",),
    )
    assert avaliar(com_alternativas, resposta("Nao ha registro nesse dia."), [])["comportamento"]
    falhou = avaliar(com_alternativas, resposta("Foram 6 milhoes de litros."), [])
    assert falhou["comportamento"] is False
    assert falhou["fidelidade"] is True  # "6 milhões de litros" não é número colado em "litros"


def test_zero_litros_inventado_reprova_a_fidelidade() -> None:
    sem_registro = {"litros_total": None, "dias_com_registro": 0}
    dada = resposta(
        "A Açucena produziu 0 litros.", feita("producao_por_periodo", {"dias": 1}, sem_registro)
    )
    assert avaliar(caso(), dada, [])["fidelidade"] is False


# --- arquivos de caso ----------------------------------------------------------------


def escrever(pasta: Path, conteudo: object, nome: str = "casos.json") -> Path:
    pasta.mkdir(exist_ok=True)
    (pasta / nome).write_text(json.dumps(conteudo), encoding="utf-8")
    return pasta


def test_formato_antigo_vira_sequencia_de_uma_chamada(tmp_path: Path) -> None:
    antigo = {
        "id": "a",
        "pergunta": "p",
        "semente": 7,
        "ferramenta_esperada": "producao_por_periodo",
        "argumentos_esperados": {"dias": 7},
        "valor_esperado": {"litros_total": 1.0},
    }
    (lido,) = carregar_casos(escrever(tmp_path, [antigo]))
    assert lido.chamadas_esperadas == (Chamada("producao_por_periodo", {"dias": 7}),)
    assert lido.perguntas == ("p",)
    assert lido.semente == 7


def test_formato_novo_com_variantes_e_alternativas(tmp_path: Path) -> None:
    novo = {
        "id": "n",
        "variantes": ["a", "b"],
        "chamadas_esperadas": [],
        "resposta_contem": ["x", ["y", "z"]],
        "sem_litros_na_resposta": True,
    }
    (lido,) = carregar_casos(escrever(tmp_path, [novo]))
    assert lido.perguntas == ("a", "b")
    assert lido.chamadas_esperadas == ()
    assert lido.resposta_contem == (("x",), ("y", "z"))
    assert lido.semente == 42


@pytest.mark.parametrize(
    ("campos", "trecho"),
    [
        ({"pergunta": "p", "variantes": ["a"]}, "um dos dois"),
        ({}, "um dos dois"),
        ({"pergunta": "p", "campo_novo": 1}, "campos desconhecidos"),
        ({"variantes": ["a", "a"]}, "repetidas"),
        ({"pergunta": "p", "ferramenta_esperada": "apagar_tudo"}, "ferramenta desconhecida"),
        (
            {"pergunta": "p", "chamadas_esperadas": [{"ferramenta": "x", "argumentos": {}}]},
            "ferramenta desconhecida",
        ),
        ({"pergunta": "p", "chamadas_proibidas": ["x"]}, "ferramenta desconhecida"),
        ({"pergunta": "p", "valor_esperado": {"litros_total": 1}}, "exige ao menos uma chamada"),
        (
            {
                "pergunta": "p",
                "ferramenta_esperada": "producao_por_periodo",
                "valor_esperado": {"litros_total": 1},
                "numeros_na_resposta": ["outro"],
            },
            "não é um número",
        ),
        ({"pergunta": "p" * 1001}, "longa demais"),
        ({"pergunta": "p", "semente": "42"}, "semente"),
        ({"pergunta": "p", "sem_litros_na_resposta": "sim"}, "verdadeiro ou falso"),
    ],
)
def test_caso_invalido_e_erro_claro(tmp_path: Path, campos: dict[str, Any], trecho: str) -> None:
    with pytest.raises(ErroDeCaso, match=trecho):
        carregar_casos(escrever(tmp_path, [{"id": "c", **campos}]))


def test_id_repetido_entre_arquivos_e_erro(tmp_path: Path) -> None:
    escrever(tmp_path, [{"id": "c", "pergunta": "p"}], "a.json")
    escrever(tmp_path, [{"id": "c", "pergunta": "q"}], "b.json")
    with pytest.raises(ErroDeCaso, match="repetido"):
        carregar_casos(tmp_path)


def test_json_invalido_e_erro_claro(tmp_path: Path) -> None:
    (tmp_path / "ruim.json").write_text("{", encoding="utf-8")
    with pytest.raises(ErroDeCaso, match="JSON inválido"):
        carregar_casos(tmp_path)


CASOS_DO_PROJETO = carregar_casos()


def test_casos_do_projeto_sao_validos_e_tem_variantes_e_recusas() -> None:
    assert len(CASOS_DO_PROJETO) >= 20
    assert any(len(c.perguntas) > 1 for c in CASOS_DO_PROJETO)
    assert any(c.chamadas_esperadas == () for c in CASOS_DO_PROJETO)
    assert any(c.chamadas_proibidas for c in CASOS_DO_PROJETO)


@pytest.mark.parametrize("do_projeto", CASOS_DO_PROJETO, ids=lambda c: c.id)
def test_valor_esperado_de_cada_caso_bate_com_o_banco(do_projeto: Caso, bancos: Bancos) -> None:
    if not do_projeto.chamadas_esperadas:
        pytest.skip("caso sem chamadas esperadas")
    resultados = resultados_das_chamadas_esperadas(bancos.abrir(do_projeto.semente), do_projeto)
    ultimo = resultados[-1]
    for campo, esperado in do_projeto.valor_esperado.items():
        if campo == "ids":
            assert [a["id"] for a in ultimo["animais"]] == esperado
        elif campo == "nomes":
            assert [a["nome"] for a in ultimo["animais"]] == esperado
        else:
            assert ultimo[campo] == esperado, campo
    # Nos casos de várias chamadas, o id usado na consulta tem de ser o que a busca devolve.
    for anterior, chamada in zip(resultados, do_projeto.chamadas_esperadas[1:], strict=False):
        if "animal_id" in chamada.argumentos and "animais" in anterior:
            assert chamada.argumentos["animal_id"] in [a["id"] for a in anterior["animais"]]


# --- cliente com espera --------------------------------------------------------------


class ClienteComFalhas:
    modelo = "modelo-falso"

    def __init__(self, erros: Sequence[Exception]) -> None:
        self._erros = list(erros)
        self.chamadas = 0

    def gerar(self, *args: object) -> RespostaLLM:
        self.chamadas += 1
        if self._erros:
            raise self._erros.pop(0)
        return RespostaLLM("ok")


def limite() -> ErroLLM:
    return ErroLLM("O provedor recusou a chamada (código 429).", codigo=429)


def test_erro_429_espera_e_tenta_de_novo() -> None:
    esperas: list[float] = []
    interno = ClienteComFalhas([limite(), ErroLLM("sobrecarga", codigo=503)])
    cliente = ClienteComEspera(interno, esperas=(15, 30, 60), dormir=esperas.append)
    assert cliente.gerar("p", [], []).texto == "ok"
    assert esperas == [15, 30]
    assert cliente.novas_tentativas == 2
    assert cliente.chamadas == 3


def test_tentativas_esgotadas_repassam_o_erro() -> None:
    esperas: list[float] = []
    interno = ClienteComFalhas([limite(), limite(), limite()])
    cliente = ClienteComEspera(interno, esperas=(1, 2), dormir=esperas.append)
    with pytest.raises(ErroLLM) as info:
        cliente.gerar("p", [], [])
    assert info.value.codigo == 429
    assert esperas == [1, 2]
    assert interno.chamadas == 3


def test_erro_que_nao_e_de_limite_nao_tem_nova_tentativa() -> None:
    esperas: list[float] = []
    interno = ClienteComFalhas([ErroLLM("chave inválida", codigo=400)])
    cliente = ClienteComEspera(interno, dormir=esperas.append)
    with pytest.raises(ErroLLM):
        cliente.gerar("p", [], [])
    assert esperas == []
    assert interno.chamadas == 1


def test_intervalo_entre_chamadas_mas_nao_antes_da_primeira() -> None:
    esperas: list[float] = []
    cliente = ClienteComEspera(ClienteComFalhas([]), intervalo=4, dormir=esperas.append)
    cliente.gerar("p", [], [])
    assert esperas == []
    cliente.gerar("p", [], [])
    cliente.gerar("p", [], [])
    assert esperas == [4, 4]


def test_teto_de_chamadas() -> None:
    cliente = ClienteComEspera(ClienteComFalhas([]), max_chamadas=2, dormir=sem_dormir)
    cliente.gerar("p", [], [])
    cliente.gerar("p", [], [])
    with pytest.raises(TetoDeChamadas):
        cliente.gerar("p", [], [])


def test_tempo_no_modelo_nao_conta_as_esperas() -> None:
    instantes = iter([0.0, 2.0, 10.0, 13.0])
    cliente = ClienteComEspera(
        ClienteComFalhas([]), intervalo=100, dormir=sem_dormir, relogio=lambda: next(instantes)
    )
    cliente.gerar("p", [], [])
    cliente.gerar("p", [], [])
    assert cliente.tempo_no_modelo == 5.0
    assert cliente.modelo == "modelo-falso"


# --- executor ------------------------------------------------------------------------


def test_rodada_com_agente_certo_aprova_tudo(bancos: Bancos) -> None:
    rodada = executar([CASO_SEMANA], com_espera(agente_certo), bancos, repeticoes=2)
    assert len(rodada.execucoes) == 4  # 2 variantes x 2 repetições
    assert all(e.executada and e.passou for e in rodada.execucoes)
    assert rodada.interrompida is None
    primeira = rodada.execucoes[0]
    assert (primeira.variante, primeira.repeticao, primeira.passos) == (1, 1, 2)
    assert primeira.chamadas[0]["ferramenta"] == "producao_por_periodo"
    assert primeira.chamadas[0]["resultado"]["litros_total"] == 4479.1
    assert "4479,1" in (primeira.resposta or "")

    resumo = resumir([CASO_SEMANA], rodada)
    assert resumo["metricas"]["ferramenta"] == {"acertos": 4, "total": 4, "taxa": 1.0}
    assert resumo["metricas"]["numeros"]["taxa"] == 1.0
    assert resumo["metricas"]["comportamento"] == {"acertos": 0, "total": 0, "taxa": None}
    assert resumo["metricas"]["consistencia_entre_variantes"]["acertos"] == 1
    assert resumo["casos"] == [{"id": "semana", "variantes": 2, "aprovadas": 4, "total": 4}]
    assert resumo["amostra_pequena"] is True
    assert resumo["execucoes_nao_executadas"] == 0


def test_rodada_com_agente_que_inventa_reprova_numeros_e_consistencia(bancos: Bancos) -> None:
    rodada = executar([CASO_SEMANA], com_espera(agente_que_inventa), bancos, repeticoes=1)
    assert [e.passou for e in rodada.execucoes] == [False, False]
    resumo = resumir([CASO_SEMANA], rodada)
    assert resumo["metricas"]["ferramenta"]["taxa"] == 1.0
    assert resumo["metricas"]["numeros"]["taxa"] == 0.0
    # A trava do agente (ADR 0008) barra o número inventado e a resposta entregue não tem
    # litros. Mesmo assim a fidelidade reprova: ela olha também o texto barrado, porque quem
    # inventou foi o modelo (revisão de 2026-11-17; antes, a métrica dava 100% aqui).
    assert resumo["metricas"]["fidelidade"]["taxa"] == 0.0
    assert resumo["execucoes_com_trava"] == 2
    # Barrada, pedido de correção, barrada de novo: dois textos guardados por execução.
    assert [len(e.respostas_barradas) for e in rodada.execucoes] == [2, 2]
    assert all(e.resposta == MENSAGEM_SEM_CONFIRMACAO for e in rodada.execucoes)
    assert resumo["metricas"]["execucao_aprovada"]["acertos"] == 0
    assert resumo["metricas"]["consistencia_entre_variantes"] == {
        "acertos": 0,
        "total": 1,
        "taxa": 0.0,
    }


def test_uma_variante_que_falha_quebra_a_consistencia_do_caso(bancos: Bancos) -> None:
    def roteiro(mensagens: Sequence[Mensagem]) -> RespostaLLM:
        errou = "quanto deu" in (mensagens[0].texto or "")
        return (agente_que_inventa if errou else agente_certo)(mensagens)

    rodada = executar([CASO_SEMANA], com_espera(roteiro), bancos, repeticoes=1)
    resumo = resumir([CASO_SEMANA], rodada)
    assert resumo["metricas"]["execucao_aprovada"] == {"acertos": 1, "total": 2, "taxa": 0.5}
    assert resumo["metricas"]["consistencia_entre_variantes"]["acertos"] == 0


def test_falha_do_modelo_vira_nao_executada_e_fica_fora_das_taxas(bancos: Bancos) -> None:
    contador = {"n": 0}

    def roteiro(mensagens: Sequence[Mensagem]) -> RespostaLLM:
        if mensagens[-1].papel == "usuario":
            contador["n"] += 1
            if contador["n"] == 1:
                raise ErroLLM("O provedor recusou a chamada (código 500).", codigo=500)
        return agente_certo(mensagens)

    rodada = executar([CASO_SEMANA], com_espera(roteiro), bancos, repeticoes=1)
    primeira, segunda = rodada.execucoes
    assert primeira.executada is False
    assert primeira.passou is None
    assert "500" in (primeira.erro or "")
    assert segunda.passou is True
    resumo = resumir([CASO_SEMANA], rodada)
    assert resumo["execucoes_validas"] == 1
    assert resumo["execucoes_nao_executadas"] == 1
    assert resumo["metricas"]["execucao_aprovada"] == {"acertos": 1, "total": 1, "taxa": 1.0}


def test_tres_falhas_seguidas_interrompem_a_rodada(bancos: Bancos) -> None:
    def roteiro(mensagens: Sequence[Mensagem]) -> RespostaLLM:
        raise limite()

    cliente = com_espera(roteiro, esperas=())
    rodada = executar([CASO_SEMANA], cliente, bancos, repeticoes=5)
    assert len(rodada.execucoes) == 3
    assert rodada.interrompida is not None
    assert "limite de uso" in rodada.interrompida
    resumo = resumir([CASO_SEMANA], rodada)
    assert resumo["execucoes_validas"] == 0
    assert resumo["metricas"]["ferramenta"]["taxa"] is None
    assert resumo["latencia_mediana_s"] is None


def test_teto_de_chamadas_interrompe_e_devolve_o_que_ja_foi_medido(bancos: Bancos) -> None:
    cliente = com_espera(agente_certo, max_chamadas=3)  # cada pergunta usa 2 chamadas
    rodada = executar([CASO_SEMANA], cliente, bancos, repeticoes=2)
    assert len(rodada.execucoes) == 1
    assert "Teto de 3" in (rodada.interrompida or "")


def test_repeticoes_invalidas(bancos: Bancos) -> None:
    with pytest.raises(ValueError, match="repeticoes"):
        executar([CASO_SEMANA], com_espera(agente_certo), bancos, repeticoes=0)


def test_erro_previsto_na_chamada_esperada_vira_o_mesmo_erro_que_o_agente_recebe(
    bancos: Bancos,
) -> None:
    fora = caso(
        chamadas_esperadas=(
            Chamada(
                "producao_por_periodo", {"data_inicio": "2026-04-21", "data_fim": "2026-04-21"}
            ),
        )
    )
    (resultado,) = resultados_das_chamadas_esperadas(bancos.abrir(42), fora)
    assert "2026-08-18 a 2026-11-15" in resultado["erro"]


def test_banco_das_evals_e_somente_leitura(bancos: Bancos) -> None:
    import sqlite3

    with pytest.raises(sqlite3.OperationalError):
        bancos.abrir(42).execute("DELETE FROM animais")


# --- relatório e linha de comando ----------------------------------------------------


def test_relatorio_em_texto_mostra_taxas_falhas_e_aviso_de_amostra(bancos: Bancos) -> None:
    rodada = executar([CASO_SEMANA], com_espera(agente_que_inventa), bancos, repeticoes=1)
    metadados = {
        "modelo": "modelo-falso",
        "repeticoes": 1,
        "commit": "abc1234",
        "arvore_suja": True,
    }
    relatorio = rel.montar(metadados, resumir([CASO_SEMANA], rodada), rodada)
    texto = rel.formatar(relatorio)
    assert "Ferramenta correta" in texto and "2/2 (100,0%)" in texto
    assert "0/2 (0,0%)" in texto
    assert "não medido" in texto  # comportamento não foi definido neste caso
    assert "amostra pequena" in texto
    assert "mudanças não commitadas" in texto
    assert "reprovou em: numeros" in texto
    assert "resposta: O rebanho produziu cerca" not in texto  # o inventado não foi entregue
    assert f"entregue: {MENSAGEM_SEM_CONFIRMACAO}" in texto
    assert "Execuções em que a trava de litros barrou uma resposta: 2" in texto
    assert "barrada: O rebanho produziu cerca de 4.500 litros." in texto
    json.dumps(relatorio)  # o relatório inteiro é serializável


def test_abaixo_do_exigido_considera_o_que_nao_foi_medido(bancos: Bancos) -> None:
    rodada = executar([CASO_SEMANA], com_espera(agente_certo), bancos, repeticoes=1)
    assert rel.abaixo_do_exigido(resumir([CASO_SEMANA], rodada), 0.9) == []
    ruim = executar([CASO_SEMANA], com_espera(agente_que_inventa), bancos, repeticoes=1)
    reprovadas = rel.abaixo_do_exigido(resumir([CASO_SEMANA], ruim), 0.9)
    assert reprovadas == ["Números corretos na resposta", "Consistência entre variantes (casos)"]


CASO_EM_ARQUIVO = {
    "id": "semana",
    "variantes": ["produção da semana", "quanto deu essa semana"],
    "chamadas_esperadas": [{"ferramenta": "producao_por_periodo", "argumentos": {"dias": 7}}],
    "valor_esperado": {"litros_total": 4479.1},
    "numeros_na_resposta": ["litros_total"],
}


def rodar(tmp_path: Path, roteiro: Roteiro, *extras: str) -> int:
    casos = escrever(tmp_path / "casos", [CASO_EM_ARQUIVO, {"id": "outro", "pergunta": "oi"}])
    argumentos = ["--pasta-casos", str(casos), "--saida", str(tmp_path / "saida"), *extras]
    return main(argumentos, cliente=ClienteRoteiro(roteiro), dormir=sem_dormir)


def test_linha_de_comando_roda_grava_o_json_e_imprime_o_resumo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert rodar(tmp_path, agente_certo, "--casos", "semana", "--repeticoes", "2") == 0
    saida = capsys.readouterr()
    assert "4/4 (100,0%)" in saida.out
    assert "[semana v1 r1] ok" in saida.err
    (arquivo,) = (tmp_path / "saida").glob("*.json")
    assert "modelo-falso" in arquivo.name
    gravado = json.loads(arquivo.read_text(encoding="utf-8"))
    assert gravado["versao_do_formato"] == 1
    assert gravado["metadados"]["modelo"] == "modelo-falso"
    assert gravado["metadados"]["chamadas_ao_modelo"] == 8
    assert len(gravado["metadados"]["prompt_sha256"]) == 64
    assert gravado["metadados"]["codigo_mudou_durante_a_rodada"] is False
    assert len(gravado["execucoes"]) == 4
    assert gravado["resumo"]["metricas"]["numeros"]["taxa"] == 1.0


def test_exigir_sai_com_1_quando_a_taxa_fica_abaixo(tmp_path: Path) -> None:
    assert rodar(tmp_path, agente_certo, "--casos", "semana", "--exigir", "0.9") == 0
    assert rodar(tmp_path, agente_que_inventa, "--casos", "semana", "--exigir", "0.9") == 1
    assert rodar(tmp_path, agente_que_inventa, "--casos", "semana") == 0  # sem --exigir, só mede


def test_listar_nao_chama_o_modelo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def proibido(mensagens: Sequence[Mensagem]) -> RespostaLLM:
        raise AssertionError("o modelo não devia ser chamado")

    assert rodar(tmp_path, proibido, "--listar") == 0
    saida = capsys.readouterr().out
    assert "semana (2 pergunta(s)" in saida
    assert "2 casos, 3 perguntas." in saida
    assert not (tmp_path / "saida").exists()


def test_limite_escolhe_os_primeiros_casos(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert rodar(tmp_path, agente_certo, "--limite", "1", "--listar") == 0
    assert "1 casos" in capsys.readouterr().out


@pytest.mark.parametrize(
    "extras", [("--casos", "nao-existe"), ("--repeticoes", "0"), ("--limite", "0")]
)
def test_uso_incorreto_sai_com_2(tmp_path: Path, extras: tuple[str, ...]) -> None:
    assert rodar(tmp_path, agente_certo, *extras) == 2


def test_caso_invalido_na_pasta_sai_com_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    casos = escrever(tmp_path / "casos", [{"id": "c"}])
    codigo = main(["--pasta-casos", str(casos)], cliente=ClienteRoteiro(agente_certo))
    assert codigo == 2
    assert "Erro nos casos" in capsys.readouterr().err


def test_rodada_sem_nenhuma_execucao_valida_sai_com_1(tmp_path: Path) -> None:
    def roteiro(mensagens: Sequence[Mensagem]) -> RespostaLLM:
        raise ErroLLM("chave recusada", codigo=403)

    assert rodar(tmp_path, roteiro, "--casos", "semana") == 1
    (arquivo,) = (tmp_path / "saida").glob("*.json")  # o relatório parcial é gravado mesmo assim
    gravado = json.loads(arquivo.read_text(encoding="utf-8"))
    assert gravado["resumo"]["interrompida"]
    assert gravado["resumo"]["execucoes_validas"] == 0


def test_relatorio_avisa_quando_o_codigo_mudou_durante_a_rodada(bancos: Bancos) -> None:
    # Em 2026-11-17 uma rodada começou com o código antigo e terminou com o novo, e o relatório
    # atribuiu tudo à versão nova. Agora a versão é lida antes e conferida depois.
    rodada = executar([CASO_SEMANA], com_espera(agente_certo), bancos, repeticoes=1)
    metadados = {"modelo": "m", "repeticoes": 1, "commit": "abc", "arvore_suja": True}
    sem_mudanca = rel.formatar(rel.montar(metadados, resumir([CASO_SEMANA], rodada), rodada))
    assert "mudou durante a rodada" not in sem_mudanca
    metadados["codigo_mudou_durante_a_rodada"] = True
    com_mudanca = rel.formatar(rel.montar(metadados, resumir([CASO_SEMANA], rodada), rodada))
    assert "o código ou o prompt mudou durante a rodada" in com_mudanca


def _repositorio_git(pasta: Path) -> Path | None:
    """Um repositório git de verdade numa pasta temporária, ou None se não houver git."""
    try:
        for comando in (
            ["init", "-q"],
            ["config", "user.email", "teste@exemplo.invalid"],
            ["config", "user.name", "Teste"],
        ):
            subprocess.run(["git", *comando], cwd=pasta, check=True, capture_output=True)
        (pasta / "a.md").write_text("início\n", encoding="utf-8")
        subprocess.run(["git", "add", "a.md"], cwd=pasta, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "c"], cwd=pasta, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return pasta


def test_versao_do_codigo_aguenta_diff_com_acento_e_aspas_curvas(tmp_path: Path) -> None:
    # Em cp1252 (o padrão do Windows), os bytes UTF-8 de "Á", "Í" e "”" não existem, e a leitura
    # da saída do git quebrava a rodada inteira. Achado da revisão de 2026-11-17.
    raiz = _repositorio_git(tmp_path)
    if raiz is None:
        pytest.skip("git indisponível")
    limpa = _versao_do_codigo(raiz)
    assert limpa["git_status"] == ""
    assert limpa["commit"]
    (raiz / "a.md").write_text("ÁREA de produção, “Íris”\n", encoding="utf-8")
    suja = _versao_do_codigo(raiz)
    assert suja["git_status"]
    assert suja["conteudo_sha256"] != limpa["conteudo_sha256"]


def test_versao_do_codigo_muda_com_segunda_edicao_e_com_arquivo_novo(tmp_path: Path) -> None:
    raiz = _repositorio_git(tmp_path)
    if raiz is None:
        pytest.skip("git indisponível")
    (raiz / "a.md").write_text("primeira edição\n", encoding="utf-8")
    primeira = _versao_do_codigo(raiz)
    (raiz / "a.md").write_text("segunda edição\n", encoding="utf-8")
    segunda = _versao_do_codigo(raiz)
    # O status (" M a.md") é igual nas duas; só o hash do conteúdo pega a segunda edição.
    assert primeira["git_status"] == segunda["git_status"]
    assert primeira["conteudo_sha256"] != segunda["conteudo_sha256"]
    assert _versao_do_codigo(raiz) == segunda  # sem mudança, a versão é estável
    (raiz / "novo.py").write_bytes(b"x = 1\n")
    assert _versao_do_codigo(raiz)["conteudo_sha256"] != segunda["conteudo_sha256"]


def test_versao_do_codigo_inclui_arquivo_novo_com_acento_no_nome(tmp_path: Path) -> None:
    # Sem `ls-files -z`, o git põe o nome entre aspas com escapes, e o arquivo ficava fora do
    # hash sem aviso (achado da segunda revisão de 2026-11-17).
    raiz = _repositorio_git(tmp_path)
    if raiz is None:
        pytest.skip("git indisponível")
    (raiz / "ração.py").write_bytes(b"x = 1\n")
    antes = _versao_do_codigo(raiz)
    (raiz / "ração.py").write_bytes(b"x = 2\n")
    assert _versao_do_codigo(raiz)["conteudo_sha256"] != antes["conteudo_sha256"]


def test_versao_do_codigo_sem_git_tem_hash_nulo(tmp_path: Path) -> None:
    # Uma pasta que não é repositório: o git falha, e o hash fica nulo em vez de um hash de
    # texto vazio, que seria igual em estados diferentes.
    assert _versao_do_codigo(tmp_path)["conteudo_sha256"] is None
