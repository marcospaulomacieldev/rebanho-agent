"""Roda as evals com o modelo de verdade: `python -m evals.run`.

Precisa da chave do provedor no ambiente (normalmente no `.env`) e consome o limite de uso do
plano. Para uma amostra pequena: `python -m evals.run --limite 3 --repeticoes 1`.
Desenho e métricas no ADR 0007.
"""

import argparse
import hashlib
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from app.agente import carregar_prompt
from app.llm.client import ClienteLLM, ErroLLM, cliente_do_ambiente
from evals import relatorio as rel
from evals.casos import PASTA_CASOS, ErroDeCaso, carregar_casos
from evals.cliente import ClienteComEspera
from evals.executor import Bancos, Execucao, executar, resumir

RAIZ = Path(__file__).resolve().parents[1]
PASTA_RESULTADOS = RAIZ / "evals" / "resultados"


def _git(*argumentos: str) -> str | None:
    try:
        saida = subprocess.run(
            ["git", *argumentos], cwd=RAIZ, capture_output=True, text=True, timeout=10, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return saida.stdout.strip()


def _progresso(execucao: Execucao) -> None:
    estado = "não executada" if not execucao.executada else "ok" if execucao.passou else "FALHOU"
    print(
        f"[{execucao.caso_id} v{execucao.variante} r{execucao.repeticao}] {estado}",
        file=sys.stderr,
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    cliente: ClienteLLM | None = None,
    dormir: Callable[[float], None] = time.sleep,
) -> int:
    """Código de saída: 0 ok; 1 configuração do modelo inválida, nenhuma execução válida,
    rodada interrompida ou métrica abaixo de `--exigir`; 2 uso incorreto ou caso inválido.

    `cliente` e `dormir` existem para testes (cliente falso, sem esperar de verdade).
    """
    parser = argparse.ArgumentParser(description="Roda as evals do agente com o modelo real.")
    parser.add_argument("--casos", help="ids dos casos, separados por vírgula (padrão: todos)")
    parser.add_argument("--limite", type=int, help="roda só os N primeiros casos")
    parser.add_argument("--repeticoes", type=int, default=3, help="vezes por pergunta (padrão 3)")
    parser.add_argument(
        "--intervalo", type=float, default=4.0, help="segundos entre chamadas ao modelo"
    )
    parser.add_argument("--max-chamadas", type=int, help="teto de chamadas ao modelo na rodada")
    parser.add_argument("--exigir", type=float, help="taxa mínima (ex.: 0.9) nas métricas da spec")
    parser.add_argument("--saida", type=Path, default=PASTA_RESULTADOS, help="pasta do JSON")
    parser.add_argument("--pasta-casos", type=Path, default=PASTA_CASOS, help=argparse.SUPPRESS)
    parser.add_argument("--listar", action="store_true", help="lista os casos e sai, sem rodar")
    args = parser.parse_args(argv)

    for fluxo in (sys.stdout, sys.stderr):  # acentos corretos também no Windows
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")

    try:
        casos = carregar_casos(args.pasta_casos)
    except ErroDeCaso as erro:
        print(f"Erro nos casos: {erro}", file=sys.stderr)
        return 2
    if args.casos:
        pedidos = [c.strip() for c in args.casos.split(",") if c.strip()]
        inexistentes = sorted(set(pedidos) - {c.id for c in casos})
        if inexistentes:
            print(f"Erro: casos inexistentes: {', '.join(inexistentes)}.", file=sys.stderr)
            return 2
        casos = [c for c in casos if c.id in pedidos]
    if args.limite is not None:
        casos = casos[: max(args.limite, 0)]
    if args.exigir is not None and not 0 <= args.exigir <= 1:
        print("Erro: --exigir deve ficar entre 0 e 1 (por exemplo, 0.9).", file=sys.stderr)
        return 2
    if args.repeticoes < 1 or not casos:
        print("Erro: nada para rodar (confira --repeticoes, --casos e --limite).", file=sys.stderr)
        return 2

    perguntas = sum(len(c.perguntas) for c in casos)
    if args.listar:
        for caso in casos:
            print(f"{caso.id} ({len(caso.perguntas)} pergunta(s), {caso.arquivo})")
        print(f"{len(casos)} casos, {perguntas} perguntas.")
        return 0

    if cliente is None:
        load_dotenv()
        try:
            cliente = cliente_do_ambiente()
        except ErroLLM as erro:
            print(f"Erro: {erro}", file=sys.stderr)
            return 1

    com_espera = ClienteComEspera(
        cliente, intervalo=args.intervalo, max_chamadas=args.max_chamadas, dormir=dormir
    )
    print(
        f"Rodando {len(casos)} casos, {perguntas} perguntas, {args.repeticoes} repetição(ões):"
        f" {perguntas * args.repeticoes} execuções com o modelo {com_espera.modelo}.",
        file=sys.stderr,
    )
    iniciado = datetime.now().astimezone()
    with Bancos() as bancos:
        rodada = executar(
            casos, com_espera, bancos, repeticoes=args.repeticoes, ao_terminar=_progresso
        )

    metadados: dict[str, Any] = {
        "iniciado_em": iniciado.isoformat(timespec="seconds"),
        "modelo": com_espera.modelo,
        "provedor": type(cliente).__name__,
        "repeticoes": args.repeticoes,
        "intervalo_s": args.intervalo,
        "casos": [c.id for c in casos],
        "commit": _git("rev-parse", "--short", "HEAD"),
        "arvore_suja": bool(_git("status", "--porcelain")),
        "prompt_sha256": hashlib.sha256(carregar_prompt().encode("utf-8")).hexdigest(),
        "chamadas_ao_modelo": com_espera.chamadas,
        "novas_tentativas": com_espera.novas_tentativas,
    }
    resumo = resumir(casos, rodada)
    relatorio = rel.montar(metadados, resumo, rodada)
    modelo_no_nome = "".join(c if c.isalnum() or c in "-." else "_" for c in str(com_espera.modelo))
    caminho = rel.gravar(relatorio, args.saida, f"{iniciado:%Y%m%d-%H%M%S}-{modelo_no_nome}.json")

    print(rel.formatar(relatorio))
    print(f"\nRelatório completo: {caminho}")
    if not resumo["execucoes_validas"] or resumo["interrompida"]:
        return 1  # nada medido, ou rodada incompleta
    if args.exigir is not None:
        reprovadas = rel.abaixo_do_exigido(resumo, args.exigir)
        if reprovadas:
            print(f"Abaixo do exigido ({args.exigir}): {', '.join(reprovadas)}.", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
