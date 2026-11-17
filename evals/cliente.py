"""Invólucro do cliente do LLM para as evals: ritmo, novas tentativas e teto de chamadas."""

import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from app.llm.client import ClienteLLM, ErroLLM, Mensagem, RespostaLLM

CODIGOS_COM_NOVA_TENTATIVA = (429, 503)  # limite de requisições e sobrecarga do provedor
ESPERAS_PADRAO = (15.0, 30.0, 60.0, 120.0)


class TetoDeChamadas(RuntimeError):
    """O limite de chamadas ao modelo definido para a rodada (`--max-chamadas`) foi atingido."""


class ClienteComEspera:
    """Cumpre a interface `ClienteLLM` em volta de outro cliente.

    - espera `intervalo` segundos entre chamadas, para respeitar o limite do plano gratuito;
    - em erro 429 ou 503, espera e tenta de novo (uma vez para cada valor de `esperas`);
    - conta as chamadas e recusa novas quando `max_chamadas` é atingido.

    `dormir` e `relogio` existem para os testes não esperarem de verdade.
    """

    def __init__(
        self,
        cliente: ClienteLLM,
        *,
        intervalo: float = 0.0,
        esperas: Sequence[float] = ESPERAS_PADRAO,
        max_chamadas: int | None = None,
        dormir: Callable[[float], None] = time.sleep,
        relogio: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._cliente = cliente
        self._intervalo = intervalo
        self._esperas = tuple(esperas)
        self._max_chamadas = max_chamadas
        self._dormir = dormir
        self._relogio = relogio
        self.modelo = getattr(cliente, "modelo", "desconhecido")
        self.chamadas = 0  # tentativas enviadas ao modelo, incluindo as repetidas
        self.novas_tentativas = 0
        self.tempo_no_modelo = 0.0  # segundos dentro do modelo, sem contar as esperas

    def _chamar(
        self,
        instrucoes: str,
        mensagens: Sequence[Mensagem],
        ferramentas: Sequence[Mapping[str, Any]],
    ) -> RespostaLLM:
        if self._max_chamadas is not None and self.chamadas >= self._max_chamadas:
            raise TetoDeChamadas(f"Teto de {self._max_chamadas} chamadas ao modelo atingido.")
        if self.chamadas and self._intervalo > 0:
            self._dormir(self._intervalo)
        self.chamadas += 1
        inicio = self._relogio()
        try:
            return self._cliente.gerar(instrucoes, mensagens, ferramentas)
        finally:
            self.tempo_no_modelo += self._relogio() - inicio

    def gerar(
        self,
        instrucoes: str,
        mensagens: Sequence[Mensagem],
        ferramentas: Sequence[Mapping[str, Any]],
    ) -> RespostaLLM:
        for espera in (*self._esperas, None):
            try:
                return self._chamar(instrucoes, mensagens, ferramentas)
            except ErroLLM as erro:
                if espera is None or erro.codigo not in CODIGOS_COM_NOVA_TENTATIVA:
                    raise
                self.novas_tentativas += 1
                self._dormir(espera)
        raise AssertionError("inalcançável")  # o laço sempre retorna ou levanta
