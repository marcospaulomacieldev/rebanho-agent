"""Testes da linha de comando (cliente falso; o arquivo .env nunca é lido)."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from app import ask
from app.ask import main
from app.db.seed import gerar_banco
from app.llm.client import ChamadaFerramenta, ErroLLM, Mensagem, RespostaLLM


class ClienteFalso:
    def __init__(
        self, respostas: Sequence[RespostaLLM] = (), erro: Exception | None = None
    ) -> None:
        self._respostas = list(respostas)
        self._erro = erro

    def gerar(
        self,
        instrucoes: str,
        mensagens: Sequence[Mensagem],
        ferramentas: Sequence[Mapping[str, Any]],
    ) -> RespostaLLM:
        if self._erro is not None:
            raise self._erro
        return self._respostas.pop(0)


@pytest.fixture
def banco(tmp_path: Path) -> Path:
    caminho = tmp_path / "rebanho.db"
    gerar_banco(caminho)
    return caminho


@pytest.fixture(autouse=True)
def nao_ler_o_env_de_verdade(monkeypatch: pytest.MonkeyPatch) -> None:
    # Os testes não podem carregar a chave real do arquivo .env do desenvolvedor.
    monkeypatch.setattr(ask, "load_dotenv", lambda *a, **k: False)


def test_pergunta_e_resposta(banco: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cliente = ClienteFalso([RespostaLLM(texto="O rebanho produziu bastante.")])
    codigo = main(["quanto", "o", "rebanho", "produziu?", "--banco", str(banco)], cliente=cliente)
    saida = capsys.readouterr()
    assert codigo == 0
    assert saida.out.strip() == "O rebanho produziu bastante."


def test_mostrar_chamadas_imprime_o_rastro_no_erro_padrao(
    banco: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cliente = ClienteFalso(
        [
            RespostaLLM(None, (ChamadaFerramenta("producao_por_periodo", {"dias": 7}),)),
            RespostaLLM(texto="Foram 4479,1 litros."),
        ]
    )
    argumentos = ["produção da semana", "--banco", str(banco), "--mostrar-chamadas"]
    codigo = main(argumentos, cliente=cliente)
    saida = capsys.readouterr()
    assert codigo == 0
    assert saida.out.strip() == "Foram 4479,1 litros."
    assert "[ferramenta] producao_por_periodo({'dias': 7})" in saida.err
    assert "4479.1" in saida.err


def test_banco_ausente_orienta_a_gerar_e_sai_com_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    codigo = main(["oi", "--banco", str(tmp_path / "nao_existe.db")], cliente=ClienteFalso())
    saida = capsys.readouterr()
    assert codigo == 2
    assert "seed_data.py" in saida.err
    assert not (tmp_path / "nao_existe.db").exists()  # não cria banco por engano


def test_pergunta_em_branco_sai_com_2(banco: Path, capsys: pytest.CaptureFixture[str]) -> None:
    codigo = main(["   ", "--banco", str(banco)], cliente=ClienteFalso())
    assert codigo == 2
    assert "vazia" in capsys.readouterr().err


def test_falha_do_modelo_sai_com_1_e_mensagem_amigavel(
    banco: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cliente = ClienteFalso(erro=ErroLLM("O provedor recusou a chamada (código 429): Cota excedida"))
    codigo = main(["oi", "--banco", str(banco)], cliente=cliente)
    saida = capsys.readouterr()
    assert codigo == 1
    assert "429" in saida.err
    assert "Traceback" not in saida.err


def test_sem_chave_no_ambiente_sai_com_1_e_cita_a_variavel(
    banco: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    codigo = main(["oi", "--banco", str(banco)])
    assert codigo == 1
    assert "GEMINI_API_KEY" in capsys.readouterr().err
