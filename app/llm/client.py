"""Acesso ao modelo de linguagem (LLM).

Todo acesso ao LLM passa por este arquivo (ADR 0002): é o único que importa o SDK do
provedor. O resto do projeto conversa com a interface `ClienteLLM` e com tipos próprios
(`Mensagem`, `RespostaLLM`), sem saber qual provedor está por trás. Trocar de provedor
significa escrever outra classe que cumpra `ClienteLLM` e escolhê-la em `cliente_do_ambiente`.

Configuração, sempre por variáveis de ambiente (a chave nunca é impressa nem registrada):
- `LLM_PROVIDER`: provedor (padrão `gemini`);
- `LLM_MODEL`: modelo (padrão `gemini-3.5-flash-lite`);
- `GEMINI_API_KEY`: chave da API do Gemini.
"""

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from google import genai
from google.genai import errors, types

PROVEDOR_PADRAO = "gemini"
MODELO_PADRAO = "gemini-3.5-flash-lite"
TIMEOUT_MS = 60_000  # tempo máximo de espera por uma chamada ao modelo


class ErroLLM(RuntimeError):
    """Falha ao falar com o modelo (chave ausente, limite de uso, rede, resposta vazia...).

    A mensagem é segura para mostrar ao usuário e nunca contém a chave da API: ela é montada
    só com textos fixos e com o código e o status do erro, nunca com o texto que o provedor
    ou a biblioteca de rede devolveram.
    """


@dataclass(frozen=True)
class ChamadaFerramenta:
    """Pedido do modelo para executar uma ferramenta."""

    nome: str
    argumentos: dict[str, Any]


@dataclass(frozen=True)
class ResultadoFerramenta:
    """O que a ferramenta devolveu (ou {"erro": "..."}), para o modelo ler."""

    nome: str
    conteudo: dict[str, Any]


@dataclass(frozen=True)
class Mensagem:
    """Uma mensagem da conversa, em formato neutro (sem depender de provedor).

    `bruto` guarda a mensagem original do provedor, quando existe, para devolvê-la como veio.
    Alguns modelos exigem isso: o Gemini 3 inclui "assinaturas de raciocínio" nas chamadas de
    ferramenta e rejeita a conversa se elas não voltarem junto.
    """

    papel: Literal["usuario", "modelo", "ferramenta"]
    texto: str | None = None
    chamadas: tuple[ChamadaFerramenta, ...] = ()
    resultados: tuple[ResultadoFerramenta, ...] = ()
    bruto: Any = None


@dataclass(frozen=True)
class RespostaLLM:
    """Um turno do modelo: texto, pedidos de ferramenta, ou os dois."""

    texto: str | None
    chamadas: tuple[ChamadaFerramenta, ...] = ()
    bruto: Any = None


class ClienteLLM(Protocol):
    """O que o agente precisa de qualquer provedor."""

    def gerar(
        self,
        instrucoes: str,
        mensagens: Sequence[Mensagem],
        ferramentas: Sequence[Mapping[str, Any]],
    ) -> RespostaLLM:
        """Gera o próximo turno do modelo.

        `ferramentas` são as definições neutras ({"name", "description", "parameters"}).
        Levanta ErroLLM em caso de falha.
        """
        ...


# --- Gemini --------------------------------------------------------------------------


def _declaracao(ferramenta: Mapping[str, Any]) -> types.FunctionDeclaration:
    return types.FunctionDeclaration(
        name=ferramenta["name"],
        description=ferramenta["description"],
        parameters_json_schema=ferramenta["parameters"],
    )


def _conteudo(mensagem: Mensagem) -> types.Content:
    """Converte uma Mensagem neutra no formato do Gemini."""
    if mensagem.bruto is not None:
        return mensagem.bruto  # turno do modelo, devolvido exatamente como veio
    if mensagem.papel == "ferramenta":
        partes = [
            types.Part.from_function_response(name=r.nome, response=r.conteudo)
            for r in mensagem.resultados
        ]
        return types.Content(role="user", parts=partes)
    partes = []
    if mensagem.texto:
        partes.append(types.Part.from_text(text=mensagem.texto))
    for chamada in mensagem.chamadas:
        partes.append(
            types.Part(
                function_call=types.FunctionCall(name=chamada.nome, args=chamada.argumentos)
            )
        )
    return types.Content(role="user" if mensagem.papel == "usuario" else "model", parts=partes)


class ClienteGemini:
    """Cliente do Gemini com chamada manual de ferramentas.

    A chamada automática do SDK fica desligada: quem executa as ferramentas é o laço do
    agente, e só ele toca no banco.
    """

    def __init__(
        self,
        api_key: str | None = None,
        modelo: str = MODELO_PADRAO,
        *,
        sdk: Any = None,
    ) -> None:
        self.modelo = modelo
        self._sdk = (
            sdk
            if sdk is not None
            else genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=TIMEOUT_MS))
        )

    def gerar(
        self,
        instrucoes: str,
        mensagens: Sequence[Mensagem],
        ferramentas: Sequence[Mapping[str, Any]],
    ) -> RespostaLLM:
        config = types.GenerateContentConfig(
            system_instruction=instrucoes,
            tools=[types.Tool(function_declarations=[_declaracao(f) for f in ferramentas])]
            if ferramentas
            else None,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        try:
            resposta = self._sdk.models.generate_content(
                model=self.modelo,
                contents=[_conteudo(m) for m in mensagens],
                config=config,
            )
        except errors.APIError as erro:
            status = f", {erro.status}" if getattr(erro, "status", None) else ""
            raise ErroLLM(f"O provedor recusou a chamada (código {erro.code}{status}).") from erro
        except Exception as erro:  # rede fora do ar, tempo esgotado, falha do SDK...
            raise ErroLLM(
                "Não consegui falar com o provedor do modelo. Verifique a conexão e tente de novo."
            ) from erro

        candidatos = resposta.candidates or []
        conteudo = candidatos[0].content if candidatos else None
        if conteudo is None:
            raise ErroLLM("O modelo não devolveu resposta (pode ter sido bloqueada).")
        partes = conteudo.parts or []
        texto = "".join(p.text for p in partes if p.text and not p.thought) or None
        chamadas = tuple(
            ChamadaFerramenta(
                nome=p.function_call.name or "", argumentos=dict(p.function_call.args or {})
            )
            for p in partes
            if p.function_call is not None
        )
        return RespostaLLM(texto=texto, chamadas=chamadas, bruto=conteudo)


def cliente_do_ambiente(ambiente: Mapping[str, str] | None = None) -> ClienteLLM:
    """Escolhe e configura o cliente a partir das variáveis de ambiente.

    `ambiente` existe para testes; sem ele, usa `os.environ`. Não lê o arquivo `.env`:
    quem quiser isso (a linha de comando) chama `load_dotenv()` antes.
    """
    variaveis = os.environ if ambiente is None else ambiente
    provedor = variaveis.get("LLM_PROVIDER", PROVEDOR_PADRAO).strip().lower()
    if provedor == "gemini":
        chave = variaveis.get("GEMINI_API_KEY", "").strip()
        if not chave:
            raise ErroLLM(
                "A variável de ambiente GEMINI_API_KEY não está definida. "
                "Coloque a chave no arquivo .env (que não vai para o Git)."
            )
        modelo = variaveis.get("LLM_MODEL", "").strip() or MODELO_PADRAO
        return ClienteGemini(api_key=chave, modelo=modelo)
    raise ErroLLM(f"Provedor de LLM desconhecido: {provedor!r}. Disponível: gemini.")
