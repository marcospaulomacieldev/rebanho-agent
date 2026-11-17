"""Medição da busca por nome com erros de digitação (sem modelo de linguagem).

Gera, para cada animal ativo do banco, um erro de cada tipo comum no português escrito como se
fala, e também consulta nomes que não existem no rebanho. Mostra o que `listar_animais` devolve:
o animal certo direto, uma sugestão (o agente segue com ela), várias (o agente pergunta) ou nada.

Uso: `python -m evals.busca_por_nome` (imprime a tabela para alguns limiares).
Os testes usam as mesmas funções, com metas, para o limiar não piorar sem ninguém perceber.
"""

import re
import sqlite3
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import app.tools.animais as ferramenta
from app.db.connection import criar_banco_em_memoria
from app.db.seed import _NOMES, NOME_INSTRUCAO, gerar_dados, gravar_dados
from app.tools.animais import listar_animais, normalizar

# Trocas comuns de quem escreve como fala (aplicadas uma de cada vez, na primeira ocorrência).
TROCAS_DE_SOM = (
    ("ç", "ss"), ("ss", "ç"), ("ce", "se"), ("ci", "si"), ("se", "ce"), ("s", "z"), ("z", "s"),
    ("ch", "x"), ("x", "ch"), ("lh", "li"), ("nh", "ni"), ("ge", "je"), ("gi", "ji"),
    ("j", "g"), ("qu", "k"), ("rr", "r"), ("ão", "am"), ("u", "o"), ("e", "i"),
)  # fmt: skip

# Nomes de vaca comuns que não estão no banco da semente 42 (além dos que o gerador não usou).
NOMES_FORA_DO_REBANHO = (
    "Rosana", "Joana", "Formosa", "Preta", "Pretinha", "Malhadinha", "Boneca", "Pituca",
    "Lindinha", "Morena", "Fofinha", "Rainha", "Serenata", "Caramela", "Mimi", "Lilica",
    "Neném", "Flor", "Belinha", "Estrelada", "Lia", "Bia", "Ana", "Eva", "Isa", "Nina", "Lola",
    "Duda", "Dita", "Fiona",
)  # fmt: skip

CATEGORIAS = (
    "achou direto",
    "1 sugestão certa",
    "várias, com a certa",
    "nada",
    "achou outro",
    "várias, sem a certa",
    "1 sugestão errada",
)


def erros_de_digitacao(nome: str) -> dict[str, str]:
    """Um erro de cada tipo para o nome, quando o tipo se aplica e muda o texto."""
    normal = normalizar(nome)
    erros: dict[str, str] = {}
    if len(normal) >= 4:
        meio = len(normal) // 2
        erros["falta letra"] = normal[:meio] + normal[meio + 1 :]
        erros["letras trocadas"] = (
            normal[: meio - 1] + normal[meio] + normal[meio - 1] + normal[meio + 1 :]
        )
        erros["letra dobrada"] = normal[:meio] + normal[meio] + normal[meio:]
        # Também nas pontas da palavra, onde os erros mudam mais a comparação.
        erros["falta a primeira"] = normal[1:]
        erros["troca no começo"] = normal[1] + normal[0] + normal[2:]
        erros["troca no fim"] = normal[:-2] + normal[-1] + normal[-2]
    if normal.startswith("h"):
        erros["sem h"] = normal[1:]
    minusculo = nome.casefold()
    for antes, depois in TROCAS_DE_SOM:
        if antes in minusculo:
            trocado = normalizar(minusculo.replace(antes, depois, 1))
            if trocado != normal:
                erros["troca de som"] = trocado
                break
    return {tipo: erro for tipo, erro in erros.items() if re.fullmatch(r"[a-z ]+", erro)}


def classificar(resultado: dict[str, Any], esperado: str | None) -> str:
    """Categoria do que a busca devolveu. `esperado` é o nome certo (None se não existe)."""
    considerado = resultado.get("nome_considerado")
    if considerado is not None:  # a ferramenta seguiu com a única sugestão
        return "1 sugestão certa" if considerado == esperado else "1 sugestão errada"
    nomes = [a["nome"] for a in resultado["animais"]]
    sugestoes = resultado["sugestoes"]
    if nomes:
        return "achou direto" if esperado in nomes else "achou outro"
    if not sugestoes:
        return "nada"
    if len(sugestoes) == 1:
        return "1 sugestão certa" if sugestoes[0] == esperado else "1 sugestão errada"
    return "várias, com a certa" if esperado in sugestoes else "várias, sem a certa"


def nomes_fora_do_rebanho(conn: sqlite3.Connection) -> list[str]:
    """Nomes de vaca plausíveis que não existem no banco, nem entre os inativos."""
    usados = {normalizar(a["nome"]) for a in listar_animais(conn, incluir_inativos=True)["animais"]}
    candidatos = [*_NOMES, *NOMES_FORA_DO_REBANHO]
    return [n for n in dict.fromkeys(candidatos) if normalizar(n) not in usados]


def medir(conn: sqlite3.Connection) -> dict[str, Any]:
    """Contagens por categoria para os erros de digitação e para os nomes fora do rebanho."""
    erros: Counter[str] = Counter()
    por_tipo: dict[str, Counter[str]] = {}
    exemplos: dict[str, list[str]] = {}
    for animal in listar_animais(conn)["animais"]:
        if animal["nome"] == NOME_INSTRUCAO:
            continue
        for tipo, digitado in erros_de_digitacao(animal["nome"]).items():
            categoria = classificar(listar_animais(conn, nome=digitado), animal["nome"])
            erros[categoria] += 1
            por_tipo.setdefault(tipo, Counter())[categoria] += 1
            exemplos.setdefault(categoria, []).append(f"{digitado} ({animal['nome']})")

    fora: Counter[str] = Counter()
    assumidos: list[str] = []
    for nome in nomes_fora_do_rebanho(conn):
        resultado = listar_animais(conn, nome=nome)
        categoria = classificar(resultado, None)
        fora[categoria] += 1
        if categoria == "1 sugestão errada":
            assumidos.append(f"{nome} -> {resultado['nome_considerado']}")
    return {
        "erros": erros,
        "erros_total": sum(erros.values()),
        "por_tipo": por_tipo,
        "exemplos": exemplos,
        "fora": fora,
        "fora_total": sum(fora.values()),
        "fora_assumidos": assumidos,
    }


@contextmanager
def limiar(valor: float) -> Iterator[None]:
    """Troca o limiar das sugestões só dentro do bloco (para comparar limiares)."""
    anterior = ferramenta.CORTE_SUGESTAO
    ferramenta.CORTE_SUGESTAO = valor
    try:
        yield
    finally:
        ferramenta.CORTE_SUGESTAO = anterior


def main() -> None:
    conn = criar_banco_em_memoria()
    gravar_dados(conn, gerar_dados())
    atual = ferramenta.CORTE_SUGESTAO
    for valor in sorted({0.7, 0.75, 0.8, 0.82, 0.85, atual}):
        with limiar(valor):
            medida = medir(conn)
        marca = "  (limiar atual)" if valor == atual else ""
        print(f"\n== limiar {valor}{marca} ==")
        print(f"Erros de digitação de vacas que existem ({medida['erros_total']}):")
        for categoria in CATEGORIAS:
            if medida["erros"][categoria]:
                print(f"  {categoria:<22} {medida['erros'][categoria]:>3}")
        assumidos = len(medida["fora_assumidos"])
        print(
            f"Nomes fora do rebanho ({medida['fora_total']}): {assumidos} viram outra vaca"
            + (f": {'; '.join(medida['fora_assumidos'])}" if assumidos else "")
        )
        if valor == atual:
            for tipo, contagem in medida["por_tipo"].items():
                print(f"    [{tipo}] {dict(contagem)}")
            for categoria in ("nada", "1 sugestão errada", "achou outro"):
                if medida["exemplos"].get(categoria):
                    print(f"    {categoria}: {', '.join(medida['exemplos'][categoria][:12])}")


if __name__ == "__main__":
    main()
