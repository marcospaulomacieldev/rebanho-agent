"""Linha de comando para perguntar ao agente.

Dois jeitos de usar (antes, gere o banco com `python scripts/seed_data.py`):
- `python -m app.ask "sua pergunta"`: faz uma pergunta e sai;
- `python -m app.ask` (sem pergunta): abre o **modo interativo**, feito para testar o agente
  durante o desenvolvimento. Você digita uma pergunta atrás da outra, sem repetir o comando.

A chave do Gemini vem do ambiente (`GEMINI_API_KEY`), normalmente do arquivo `.env`. Ela
nunca é impressa.
"""

import argparse
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from sqlite3 import Connection

from dotenv import load_dotenv

from app.agente import RespostaAgente, responder
from app.db.connection import abrir_somente_leitura
from app.db.seed import CAMINHO_PADRAO
from app.llm.client import ClienteLLM, ErroLLM, cliente_do_ambiente

COMANDOS_SAIR = {"/sair", "sair", "exit", "quit"}
AJUDA = """Comandos do modo de teste:
  /chamadas   liga ou desliga a exibição das ferramentas que o agente chamou
  /ajuda      mostra esta ajuda
  /sair       encerra (também funciona Ctrl+C ou Ctrl+D)
Qualquer outra linha é enviada ao agente como pergunta."""


def _imprimir_chamadas(resposta: RespostaAgente) -> None:
    for chamada in resposta.chamadas:
        print(
            f"[ferramenta] {chamada.nome}({chamada.argumentos}) -> {chamada.resultado}",
            file=sys.stderr,
        )


def _perguntar(
    texto: str,
    conn: Connection,
    cliente: ClienteLLM,
    *,
    mostrar_chamadas: bool,
    mostrar_tempo: bool = False,
) -> int:
    """Faz uma pergunta e imprime a resposta. Devolve 0 (ok), 1 (modelo) ou 2 (pergunta)."""
    inicio = time.perf_counter()
    try:
        resposta = responder(texto, conn, cliente)
    except ValueError as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 2
    except ErroLLM as erro:
        print(f"Erro ao falar com o modelo: {erro}", file=sys.stderr)
        return 1
    if mostrar_chamadas:
        _imprimir_chamadas(resposta)
    print(resposta.texto)
    if mostrar_tempo:
        segundos = f"{time.perf_counter() - inicio:.1f}".replace(".", ",")
        passos = f"{resposta.passos} passo{'s' if resposta.passos != 1 else ''}"
        print(f"({segundos} s, {passos})", file=sys.stderr)
    return 0


def _modo_interativo(
    conn: Connection, cliente: ClienteLLM, banco: Path, entrada: Callable[[str], str]
) -> int:
    """Conversa de teste no terminal. Cada pergunta é independente (sem memória de conversa)."""
    modelo = getattr(cliente, "modelo", "desconhecido")
    print("Assistente do rebanho (modo de teste)")
    print(f"Modelo: {modelo} | Banco: {banco}")
    print("Cada pergunta é independente: o agente ainda não lembra da pergunta anterior.")
    print("O prompt (prompts/sistema.md) é relido a cada pergunta: editá-lo vale na hora.")
    print("Digite /ajuda para ver os comandos.\n")
    mostrar_chamadas = True
    while True:
        try:
            linha = entrada("pergunta> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not linha:
            continue
        if linha.lower() in COMANDOS_SAIR:
            break
        if linha.lower() in ("/ajuda", "/?"):
            print(AJUDA)
            continue
        if linha.lower() == "/chamadas":
            mostrar_chamadas = not mostrar_chamadas
            estado = "ligada" if mostrar_chamadas else "desligada"
            print(f"Exibição das ferramentas chamadas: {estado}.")
            continue
        try:
            _perguntar(linha, conn, cliente, mostrar_chamadas=mostrar_chamadas, mostrar_tempo=True)
        except KeyboardInterrupt:  # Ctrl+C durante a espera da resposta: cancela só esta pergunta
            print("(pergunta interrompida)", file=sys.stderr)
        print()
    print("Até logo!")
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    cliente: ClienteLLM | None = None,
    entrada: Callable[[str], str] = input,
) -> int:
    """Código de saída: 0 ok; 1 falha do modelo ou da configuração do modelo (por exemplo,
    chave ausente); 2 uso incorreto (pergunta vazia ou longa demais, ou sem pergunta fora de
    um terminal) ou banco ausente.

    `cliente` e `entrada` existem para testes; sem eles, o cliente vem das variáveis de
    ambiente e a entrada é o teclado.
    """
    parser = argparse.ArgumentParser(description="Pergunte ao assistente do rebanho.")
    parser.add_argument(
        "pergunta",
        nargs="*",
        help="a pergunta, em português; sem ela, abre o modo interativo de teste",
    )
    parser.add_argument("--banco", type=Path, default=CAMINHO_PADRAO, help="arquivo do banco")
    parser.add_argument(
        "--mostrar-chamadas",
        action="store_true",
        help="mostra as ferramentas que o agente chamou (útil para depurar)",
    )
    args = parser.parse_args(argv)
    interativo = not args.pergunta

    if interativo and entrada is input and not sys.stdin.isatty():
        print(
            "Erro: informe a pergunta, ou rode em um terminal para usar o modo interativo.",
            file=sys.stderr,
        )
        return 2

    if cliente is None:
        for fluxo in (sys.stdout, sys.stderr):  # acentos corretos também no Windows
            if hasattr(fluxo, "reconfigure"):
                fluxo.reconfigure(encoding="utf-8", errors="replace")
        load_dotenv()  # lê o .env, se existir; não imprime nada
        try:
            cliente = cliente_do_ambiente()
        except ErroLLM as erro:
            print(f"Erro: {erro}", file=sys.stderr)
            return 1

    try:
        conn = abrir_somente_leitura(args.banco)
    except FileNotFoundError:
        print(
            f"Erro: banco não encontrado em {args.banco}. "
            "Gere-o com: python scripts/seed_data.py",
            file=sys.stderr,
        )
        return 2

    try:
        if interativo:
            return _modo_interativo(conn, cliente, args.banco, entrada)
        return _perguntar(
            " ".join(args.pergunta),
            conn,
            cliente,
            mostrar_chamadas=args.mostrar_chamadas,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
