"""Linha de comando para perguntar ao agente: `python -m app.ask "sua pergunta"`.

Antes, gere o banco: `python scripts/seed_data.py`. A chave do Gemini vem do ambiente
(`GEMINI_API_KEY`), normalmente do arquivo `.env`. Ela nunca é impressa.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from dotenv import load_dotenv

from app.agente import responder
from app.db.connection import abrir_somente_leitura
from app.db.seed import CAMINHO_PADRAO
from app.llm.client import ClienteLLM, ErroLLM, cliente_do_ambiente


def main(argv: Sequence[str] | None = None, *, cliente: ClienteLLM | None = None) -> int:
    """Código de saída: 0 ok; 1 falha do modelo ou da configuração do modelo (por exemplo,
    chave ausente); 2 uso incorreto (pergunta vazia ou longa demais) ou banco ausente.

    `cliente` existe para testes; sem ele, o cliente vem das variáveis de ambiente.
    """
    parser = argparse.ArgumentParser(description="Pergunte ao assistente do rebanho.")
    parser.add_argument("pergunta", nargs="+", help="a pergunta, em português")
    parser.add_argument("--banco", type=Path, default=CAMINHO_PADRAO, help="arquivo do banco")
    parser.add_argument(
        "--mostrar-chamadas",
        action="store_true",
        help="mostra as ferramentas que o agente chamou (útil para depurar)",
    )
    args = parser.parse_args(argv)

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
        resposta = responder(" ".join(args.pergunta), conn, cliente)
    except ValueError as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 2
    except ErroLLM as erro:
        print(f"Erro ao falar com o modelo: {erro}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    if args.mostrar_chamadas:
        for chamada in resposta.chamadas:
            print(
                f"[ferramenta] {chamada.nome}({chamada.argumentos}) -> {chamada.resultado}",
                file=sys.stderr,
            )
    print(resposta.texto)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
