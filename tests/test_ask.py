"""Testes da linha de comando (cliente falso; o arquivo .env nunca é lido)."""

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace
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


# --- modo interativo -----------------------------------------------------------------


def teclado(*linhas: str) -> Callable[[str], str]:
    """Entrada simulada: devolve as linhas em ordem e depois acaba (EOF, como Ctrl+D)."""
    restantes = iter(linhas)

    def entrada(prompt: str) -> str:
        try:
            return next(restantes)
        except StopIteration:
            raise EOFError from None

    return entrada


def fala(texto: str) -> RespostaLLM:
    return RespostaLLM(texto=texto)


def pede_producao() -> RespostaLLM:
    return RespostaLLM(None, (ChamadaFerramenta("producao_por_periodo", {"dias": 7}),))


def test_modo_interativo_responde_varias_perguntas_e_sai_com_sair(
    banco: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cliente = ClienteFalso([fala("Primeira resposta."), fala("Segunda resposta.")])
    entrada = teclado("primeira pergunta", "segunda pergunta", "/sair", "nunca chega aqui")
    assert main(["--banco", str(banco)], cliente=cliente, entrada=entrada) == 0
    saida = capsys.readouterr()
    assert "Primeira resposta." in saida.out
    assert "Segunda resposta." in saida.out
    assert "Até logo!" in saida.out


def test_banner_mostra_modelo_banco_e_avisa_que_nao_ha_memoria(
    banco: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cliente = ClienteFalso()
    cliente.modelo = "modelo-de-teste"  # type: ignore[attr-defined]
    main(["--banco", str(banco)], cliente=cliente, entrada=teclado("/sair"))
    saida = capsys.readouterr().out
    assert "modelo-de-teste" in saida
    assert str(banco) in saida
    assert "independente" in saida
    assert "/ajuda" in saida


def test_ctrl_d_encerra_sem_erro(banco: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--banco", str(banco)], cliente=ClienteFalso(), entrada=teclado()) == 0
    assert "Até logo!" in capsys.readouterr().out


def test_linhas_vazias_sao_ignoradas_e_nao_chamam_o_modelo(
    banco: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cliente = ClienteFalso()  # sem respostas: qualquer chamada ao modelo daria erro
    entrada = teclado("", "   ", "/sair")
    assert main(["--banco", str(banco)], cliente=cliente, entrada=entrada) == 0
    assert "Erro" not in capsys.readouterr().err


def test_chamadas_aparecem_por_padrao_e_o_comando_alterna(
    banco: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    respostas = [pede_producao(), fala("Resposta 1."), pede_producao(), fala("Resposta 2.")]
    cliente = ClienteFalso(respostas)
    entrada = teclado("pergunta 1", "/chamadas", "pergunta 2", "/sair")
    main(["--banco", str(banco)], cliente=cliente, entrada=entrada)
    saida = capsys.readouterr()
    assert saida.err.count("[ferramenta] producao_por_periodo") == 1  # só na primeira
    assert "desligada" in saida.out


def test_mostra_tempo_e_passos_de_cada_pergunta(
    banco: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cliente = ClienteFalso([pede_producao(), fala("Resposta.")])
    main(["--banco", str(banco)], cliente=cliente, entrada=teclado("pergunta", "/sair"))
    assert " s, 2 passos)" in capsys.readouterr().err


def test_ajuda_lista_os_comandos(banco: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["--banco", str(banco)], cliente=ClienteFalso(), entrada=teclado("/ajuda", "/sair"))
    saida = capsys.readouterr().out
    assert "/chamadas" in saida
    assert "/sair" in saida


def test_erro_do_modelo_nao_encerra_o_modo_interativo(
    banco: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cliente = ClienteFalso(erro=ErroLLM("O provedor recusou a chamada (código 429)."))
    entrada = teclado("primeira", "segunda", "/sair")
    assert main(["--banco", str(banco)], cliente=cliente, entrada=entrada) == 0
    saida = capsys.readouterr()
    assert saida.err.count("429") == 2  # as duas perguntas falharam, e a conversa seguiu
    assert "Até logo!" in saida.out


def test_pergunta_longa_demais_mostra_erro_e_continua(
    banco: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cliente = ClienteFalso([fala("Resposta depois do erro.")])
    entrada = teclado("a" * 1001, "pergunta normal", "/sair")
    main(["--banco", str(banco)], cliente=cliente, entrada=entrada)
    saida = capsys.readouterr()
    assert "longa demais" in saida.err
    assert "Resposta depois do erro." in saida.out


def test_ctrl_c_durante_a_resposta_cancela_so_a_pergunta(
    banco: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cliente = ClienteFalso(erro=KeyboardInterrupt())
    entrada = teclado("pergunta demorada", "/sair")
    assert main(["--banco", str(banco)], cliente=cliente, entrada=entrada) == 0
    saida = capsys.readouterr()
    assert "interrompida" in saida.err
    assert "Até logo!" in saida.out


def test_sem_pergunta_e_sem_terminal_sai_com_2(
    banco: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Sem terminal e sem pergunta, não dá para abrir o modo interativo. O `isatty` é fixado
    # aqui para o teste não depender de como o pytest foi chamado (por exemplo, com -s).
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: False))
    assert main(["--banco", str(banco)], cliente=ClienteFalso()) == 2
    assert "modo interativo" in capsys.readouterr().err


def test_modo_interativo_abre_o_banco_em_somente_leitura(banco: Path) -> None:
    # A conexão do modo interativo é a mesma de sempre: nada pode ser escrito.
    antes = banco.read_bytes()
    cliente = ClienteFalso([pede_producao(), fala("ok")])
    main(["--banco", str(banco)], cliente=cliente, entrada=teclado("pergunta", "/sair"))
    assert banco.read_bytes() == antes


def test_launcher_do_windows_existe_e_aponta_para_o_modulo_certo() -> None:
    launcher = Path(__file__).resolve().parents[1] / "scripts" / "perguntar.cmd"
    texto = launcher.read_text(encoding="utf-8")
    assert "-m app.ask" in texto
    assert ".venv" in texto


def test_sem_chave_no_ambiente_sai_com_1_e_cita_a_variavel(
    banco: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    codigo = main(["oi", "--banco", str(banco)])
    assert codigo == 1
    assert "GEMINI_API_KEY" in capsys.readouterr().err
