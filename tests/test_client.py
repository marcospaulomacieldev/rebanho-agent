"""Testes do cliente do LLM. Sem rede: a biblioteca do Gemini é trocada por uma falsa."""

import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import errors, types

from app.llm.client import (
    MODELO_PADRAO,
    TIMEOUT_MS,
    ChamadaFerramenta,
    ClienteGemini,
    ErroLLM,
    Mensagem,
    ResultadoFerramenta,
    _conteudo,
    _declaracao,
    cliente_do_ambiente,
)
from app.tools.registro import declaracoes_neutras

RAIZ = Path(__file__).resolve().parents[1]


def sdk_falso(resposta: Any = None, erro: Exception | None = None) -> SimpleNamespace:
    """Biblioteca falsa: guarda o que recebeu em `.chamadas` e devolve `resposta` (ou erra)."""
    chamadas: list[dict[str, Any]] = []

    def gerar_conteudo(**kwargs: Any) -> Any:
        chamadas.append(kwargs)
        if erro is not None:
            raise erro
        return resposta

    modelos = SimpleNamespace(generate_content=gerar_conteudo)
    return SimpleNamespace(models=modelos, chamadas=chamadas)


def resposta_com(*partes: types.Part) -> types.GenerateContentResponse:
    conteudo = types.Content(role="model", parts=list(partes))
    return types.GenerateContentResponse(candidates=[types.Candidate(content=conteudo)])


# --- conversão de mensagens e ferramentas --------------------------------------------


def test_declaracao_usa_o_esquema_json_da_ferramenta() -> None:
    definicao = declaracoes_neutras()[0]
    declaracao = _declaracao(definicao)
    assert declaracao.name == definicao["name"]
    assert declaracao.description == definicao["description"]
    assert declaracao.parameters_json_schema == definicao["parameters"]


def test_mensagem_do_usuario_vira_conteudo_user() -> None:
    conteudo = _conteudo(Mensagem(papel="usuario", texto="oi"))
    assert conteudo.role == "user"
    assert conteudo.parts[0].text == "oi"


def test_resultado_de_ferramenta_vira_function_response_do_usuario() -> None:
    mensagem = Mensagem(
        papel="ferramenta",
        resultados=(ResultadoFerramenta("producao_por_periodo", {"litros_total": 10.0}),),
    )
    conteudo = _conteudo(mensagem)
    assert conteudo.role == "user"
    resposta = conteudo.parts[0].function_response
    assert resposta.name == "producao_por_periodo"
    assert resposta.response == {"litros_total": 10.0}


def test_turno_do_modelo_com_bruto_e_devolvido_exatamente_como_veio() -> None:
    original = types.Content(role="model", parts=[types.Part(text="x", thought_signature=b"sig")])
    mensagem = Mensagem(papel="modelo", texto="x", bruto=original)
    assert _conteudo(mensagem) is original  # preserva as assinaturas de raciocínio


def test_turno_do_modelo_sem_bruto_e_reconstruido() -> None:
    mensagem = Mensagem(
        papel="modelo",
        texto="vou consultar",
        chamadas=(ChamadaFerramenta("producao_por_periodo", {"dias": 7}),),
    )
    conteudo = _conteudo(mensagem)
    assert conteudo.role == "model"
    assert conteudo.parts[0].text == "vou consultar"
    assert conteudo.parts[1].function_call.name == "producao_por_periodo"
    assert conteudo.parts[1].function_call.args == {"dias": 7}


# --- ClienteGemini.gerar -------------------------------------------------------------


def test_gerar_configura_chamada_manual_de_ferramentas_e_envia_prompt_e_historico() -> None:
    sdk = sdk_falso(resposta_com(types.Part.from_text(text="Olá!")))
    cliente = ClienteGemini(modelo="modelo-x", sdk=sdk)
    cliente.gerar("Seja simples.", [Mensagem(papel="usuario", texto="oi")], declaracoes_neutras())

    envio = sdk.chamadas[0]
    assert envio["model"] == "modelo-x"
    config = envio["config"]
    assert config.system_instruction == "Seja simples."
    assert config.automatic_function_calling.disable is True  # só o nosso laço executa ferramentas
    assert config.tools[0].function_declarations[0].name == "producao_por_periodo"
    assert envio["contents"][0].parts[0].text == "oi"


def test_gerar_sem_ferramentas_nao_envia_lista_de_ferramentas() -> None:
    sdk = sdk_falso(resposta_com(types.Part.from_text(text="ok")))
    ClienteGemini(sdk=sdk).gerar("x", [Mensagem(papel="usuario", texto="oi")], [])
    assert sdk.chamadas[0]["config"].tools is None


def test_gerar_devolve_texto_e_guarda_o_conteudo_bruto() -> None:
    partes = (types.Part.from_text(text="Foram "), types.Part.from_text(text="10 L"))
    sdk = sdk_falso(resposta_com(*partes))
    resposta = ClienteGemini(sdk=sdk).gerar("x", [Mensagem(papel="usuario", texto="oi")], [])
    assert resposta.texto == "Foram 10 L"
    assert resposta.chamadas == ()
    assert resposta.bruto.role == "model"


def test_gerar_ignora_o_raciocinio_interno_do_modelo() -> None:
    pensamento = types.Part(text="pensando alto...", thought=True)
    sdk = sdk_falso(resposta_com(pensamento, types.Part.from_text(text="Resposta.")))
    resposta = ClienteGemini(sdk=sdk).gerar("x", [Mensagem(papel="usuario", texto="oi")], [])
    assert resposta.texto == "Resposta."


def test_gerar_devolve_os_pedidos_de_ferramenta() -> None:
    chamada = types.Part(
        function_call=types.FunctionCall(name="producao_por_periodo", args={"dias": 7})
    )
    sdk = sdk_falso(resposta_com(chamada))
    resposta = ClienteGemini(sdk=sdk).gerar("x", [Mensagem(papel="usuario", texto="oi")], [])
    assert resposta.texto is None
    assert resposta.chamadas == (ChamadaFerramenta("producao_por_periodo", {"dias": 7}),)


def test_gerar_sem_candidatos_e_erro_claro() -> None:
    sdk = sdk_falso(types.GenerateContentResponse(candidates=[]))
    with pytest.raises(ErroLLM, match="não devolveu resposta"):
        ClienteGemini(sdk=sdk).gerar("x", [Mensagem(papel="usuario", texto="oi")], [])


def test_gerar_com_conteudo_nulo_e_erro_claro() -> None:
    sdk = sdk_falso(types.GenerateContentResponse(candidates=[types.Candidate(content=None)]))
    with pytest.raises(ErroLLM, match="não devolveu resposta"):
        ClienteGemini(sdk=sdk).gerar("x", [Mensagem(papel="usuario", texto="oi")], [])


def test_gerar_com_partes_nulas_devolve_resposta_vazia() -> None:
    conteudo = types.Content(role="model", parts=None)
    sdk = sdk_falso(types.GenerateContentResponse(candidates=[types.Candidate(content=conteudo)]))
    resposta = ClienteGemini(sdk=sdk).gerar("x", [Mensagem(papel="usuario", texto="oi")], [])
    assert resposta.texto is None
    assert resposta.chamadas == ()


def test_chamada_sem_argumentos_vira_dicionario_vazio() -> None:
    parte = types.Part(function_call=types.FunctionCall(name="producao_por_periodo", args=None))
    sdk = sdk_falso(resposta_com(parte))
    resposta = ClienteGemini(sdk=sdk).gerar("x", [Mensagem(papel="usuario", texto="oi")], [])
    assert resposta.chamadas == (ChamadaFerramenta("producao_por_periodo", {}),)


def test_chamada_sem_nome_vira_nome_vazio_que_o_registro_recusa() -> None:
    parte = types.Part(function_call=types.FunctionCall(name=None, args={"dias": 7}))
    sdk = sdk_falso(resposta_com(parte))
    resposta = ClienteGemini(sdk=sdk).gerar("x", [Mensagem(papel="usuario", texto="oi")], [])
    assert resposta.chamadas[0].nome == ""


def test_erro_5xx_do_provedor_vira_erro_llm_com_codigo_e_status() -> None:
    erro = errors.ServerError(500, {"error": {"code": 500, "message": None, "status": "INTERNAL"}})
    cliente = ClienteGemini(sdk=sdk_falso(erro=erro))
    with pytest.raises(ErroLLM, match="500, INTERNAL"):
        cliente.gerar("x", [Mensagem(papel="usuario", texto="oi")], [])


def test_falha_de_rede_vira_erro_llm_sem_repassar_o_texto_original() -> None:
    erro = ConnectionError("falha ao chamar https://exemplo/?key=chave-secreta-123")
    cliente = ClienteGemini(sdk=sdk_falso(erro=erro))
    with pytest.raises(ErroLLM, match="falar com o provedor") as info:
        cliente.gerar("x", [Mensagem(papel="usuario", texto="oi")], [])
    assert "chave-secreta-123" not in str(info.value)


def test_texto_do_provedor_nunca_entra_na_mensagem_de_erro() -> None:
    # Mesmo que o provedor repita a chave no texto do erro, a mensagem final só leva o código
    # e o status. Por construção, a chave não pode vazar por aqui.
    corpo = {
        "error": {
            "code": 400,
            "message": "A chave chave-secreta-123 é inválida",
            "status": "INVALID_ARGUMENT",
        }
    }
    erro = errors.ClientError(400, corpo)
    cliente = ClienteGemini(sdk=sdk_falso(erro=erro))
    with pytest.raises(ErroLLM) as info:
        cliente.gerar("x", [Mensagem(papel="usuario", texto="oi")], [])
    assert "chave-secreta-123" not in str(info.value)
    assert "400, INVALID_ARGUMENT" in str(info.value)


def test_cliente_gemini_configura_tempo_limite(monkeypatch: pytest.MonkeyPatch) -> None:
    capturado: dict[str, Any] = {}

    def cliente_falso(**kwargs: Any) -> object:
        capturado.update(kwargs)
        return object()

    monkeypatch.setattr("app.llm.client.genai.Client", cliente_falso)
    ClienteGemini(api_key="chave-falsa")
    assert capturado["http_options"].timeout == TIMEOUT_MS


def test_erro_da_api_vira_erro_llm_sem_expor_a_excecao_do_sdk() -> None:
    erro = errors.ClientError(
        429, {"error": {"code": 429, "message": "Cota excedida", "status": "RESOURCE_EXHAUSTED"}}
    )
    cliente = ClienteGemini(sdk=sdk_falso(erro=erro))
    with pytest.raises(ErroLLM, match="429"):
        cliente.gerar("x", [Mensagem(papel="usuario", texto="oi")], [])


# --- cliente_do_ambiente -------------------------------------------------------------


def test_ambiente_completo_cria_o_cliente_gemini_com_o_modelo_pedido() -> None:
    cliente = cliente_do_ambiente({"GEMINI_API_KEY": "chave-falsa", "LLM_MODEL": "gemini-x"})
    assert isinstance(cliente, ClienteGemini)
    assert cliente.modelo == "gemini-x"


def test_modelo_padrao_quando_nao_informado() -> None:
    cliente = cliente_do_ambiente({"GEMINI_API_KEY": "chave-falsa"})
    assert isinstance(cliente, ClienteGemini)
    assert cliente.modelo == MODELO_PADRAO == "gemini-3.5-flash-lite"


@pytest.mark.parametrize("ambiente", [{}, {"GEMINI_API_KEY": ""}, {"GEMINI_API_KEY": "   "}])
def test_chave_ausente_e_erro_claro_que_cita_a_variavel(ambiente: dict[str, str]) -> None:
    with pytest.raises(ErroLLM, match="GEMINI_API_KEY"):
        cliente_do_ambiente(ambiente)


def test_provedor_desconhecido_e_erro_claro_e_nao_vaza_a_chave() -> None:
    with pytest.raises(ErroLLM, match="desconhecido") as info:
        cliente_do_ambiente({"LLM_PROVIDER": "outro", "GEMINI_API_KEY": "chave-secreta-123"})
    assert "chave-secreta-123" not in str(info.value)


# --- regra do projeto: só client.py conhece o SDK do provedor ------------------------


_IMPORTA_SDK = re.compile(
    r"^\s*(from|import)\s+google\b"
    r"|__import__\(\s*[\"']google"
    r"|import_module\(\s*[\"']google",
    re.MULTILINE,
)
CLIENTE_PERMITIDO = Path("app") / "llm" / "client.py"


@pytest.mark.parametrize(
    "codigo",
    [
        "from google import genai",
        "import google.genai",
        "    from google.genai import types",
        '__import__("google.genai")',
        "importlib.import_module('google.genai')",
    ],
)
def test_detector_pega_as_formas_de_importar_o_sdk(codigo: str) -> None:
    assert _IMPORTA_SDK.search(codigo)


@pytest.mark.parametrize(
    "codigo", ["import googleapiclient", "# from google import genai", "x = 'from google'"]
)
def test_detector_nao_acusa_o_que_nao_e_importacao(codigo: str) -> None:
    assert not _IMPORTA_SDK.search(codigo)


def test_so_o_client_importa_o_sdk_do_provedor() -> None:
    # Varre o código do projeto (raiz, app, scripts e evals); só app/llm/client.py pode importar.
    arquivos = list(RAIZ.glob("*.py"))
    for pasta in ("app", "scripts", "evals"):
        arquivos.extend((RAIZ / pasta).rglob("*.py"))
    infratores = [
        str(arquivo.relative_to(RAIZ))
        for arquivo in arquivos
        if arquivo.relative_to(RAIZ) != CLIENTE_PERMITIDO
        and _IMPORTA_SDK.search(arquivo.read_text(encoding="utf-8"))
    ]
    assert infratores == []
    assert (RAIZ / CLIENTE_PERMITIDO).exists()
