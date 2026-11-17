"""Leitura e validação dos casos de eval (`evals/casos/*.json`). Formato no ADR 0007."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.agente import MAX_CARACTERES_PERGUNTA
from app.tools.registro import REGISTRO

PASTA_CASOS = Path(__file__).resolve().parent / "casos"
SEMENTE_PADRAO = 42
_CAMPOS = {
    "id",
    "semente",
    "pergunta",
    "variantes",
    "chamadas_esperadas",
    "ferramenta_esperada",
    "argumentos_esperados",
    "chamadas_proibidas",
    "valor_esperado",
    "numeros_na_resposta",
    "resposta_contem",
    "resposta_nao_contem",
    "sem_litros_na_resposta",
}


class ErroDeCaso(ValueError):
    """Caso de eval mal escrito. A mensagem diz o arquivo, o caso e o problema."""


@dataclass(frozen=True)
class Chamada:
    ferramenta: str
    argumentos: dict[str, Any]


@dataclass(frozen=True)
class Caso:
    id: str
    semente: int
    perguntas: tuple[str, ...]  # uma pergunta, ou as variantes do mesmo pedido
    chamadas_esperadas: tuple[Chamada, ...] | None  # None = a sequência não é checada
    chamadas_proibidas: tuple[str, ...]
    valor_esperado: dict[str, Any]
    numeros_na_resposta: tuple[str, ...]
    resposta_contem: tuple[tuple[str, ...], ...]  # cada item: alternativas (basta uma)
    resposta_nao_contem: tuple[str, ...]
    sem_litros_na_resposta: bool
    arquivo: str


def _ferramenta_valida(nome: object, onde: str) -> str:
    if not isinstance(nome, str) or nome not in REGISTRO:
        raise ErroDeCaso(f"{onde}: ferramenta desconhecida: {nome!r}.")
    return nome


def _lista_de_textos(valor: object, onde: str, campo: str) -> tuple[str, ...]:
    if not isinstance(valor, list) or not all(isinstance(v, str) and v.strip() for v in valor):
        raise ErroDeCaso(f"{onde}: `{campo}` deve ser uma lista de textos não vazios.")
    return tuple(valor)


def _ler_caso(bruto: object, arquivo: str) -> Caso:
    if not isinstance(bruto, dict) or not isinstance(bruto.get("id"), str) or not bruto["id"]:
        raise ErroDeCaso(f"{arquivo}: todo caso precisa de um `id` em texto.")
    onde = f"{arquivo}, caso {bruto['id']}"
    desconhecidos = sorted(set(bruto) - _CAMPOS)
    if desconhecidos:
        raise ErroDeCaso(f"{onde}: campos desconhecidos: {', '.join(desconhecidos)}.")

    if ("pergunta" in bruto) == ("variantes" in bruto):
        raise ErroDeCaso(f"{onde}: informe `pergunta` ou `variantes` (um dos dois).")
    perguntas = (
        _lista_de_textos([bruto["pergunta"]], onde, "pergunta")
        if "pergunta" in bruto
        else _lista_de_textos(bruto["variantes"], onde, "variantes")
    )
    if not perguntas or len(set(perguntas)) != len(perguntas):
        raise ErroDeCaso(f"{onde}: `variantes` não pode ser vazia nem ter perguntas repetidas.")
    if any(len(p.strip()) > MAX_CARACTERES_PERGUNTA for p in perguntas):
        raise ErroDeCaso(f"{onde}: pergunta longa demais.")

    semente = bruto.get("semente", SEMENTE_PADRAO)
    if isinstance(semente, bool) or not isinstance(semente, int):
        raise ErroDeCaso(f"{onde}: `semente` deve ser um número inteiro.")

    antigo = "ferramenta_esperada" in bruto or "argumentos_esperados" in bruto
    if antigo and "chamadas_esperadas" in bruto:
        raise ErroDeCaso(f"{onde}: use `chamadas_esperadas` ou `ferramenta_esperada`, não os dois.")
    chamadas: tuple[Chamada, ...] | None = None
    if antigo:
        argumentos = bruto.get("argumentos_esperados", {})
        if not isinstance(argumentos, dict):
            raise ErroDeCaso(f"{onde}: `argumentos_esperados` deve ser um objeto.")
        nome = _ferramenta_valida(bruto.get("ferramenta_esperada"), onde)
        chamadas = (Chamada(nome, argumentos),)
    elif "chamadas_esperadas" in bruto:
        itens = bruto["chamadas_esperadas"]
        if not isinstance(itens, list):
            raise ErroDeCaso(f"{onde}: `chamadas_esperadas` deve ser uma lista.")
        lidas = []
        for item in itens:
            if not isinstance(item, dict) or set(item) - {"ferramenta", "argumentos"}:
                raise ErroDeCaso(
                    f"{onde}: cada chamada esperada tem só `ferramenta` e `argumentos`."
                )
            argumentos = item.get("argumentos", {})
            if not isinstance(argumentos, dict):
                raise ErroDeCaso(f"{onde}: `argumentos` deve ser um objeto.")
            lidas.append(Chamada(_ferramenta_valida(item.get("ferramenta"), onde), argumentos))
        chamadas = tuple(lidas)

    proibidas = _lista_de_textos(bruto.get("chamadas_proibidas", []), onde, "chamadas_proibidas")
    for nome in proibidas:
        _ferramenta_valida(nome, onde)

    valor = bruto.get("valor_esperado", {})
    if not isinstance(valor, dict):
        raise ErroDeCaso(f"{onde}: `valor_esperado` deve ser um objeto.")
    if valor and not chamadas:
        raise ErroDeCaso(f"{onde}: `valor_esperado` exige ao menos uma chamada esperada.")
    numeros = _lista_de_textos(bruto.get("numeros_na_resposta", []), onde, "numeros_na_resposta")
    for campo in numeros:
        numero = valor.get(campo)
        if isinstance(numero, bool) or not isinstance(numero, int | float):
            raise ErroDeCaso(
                f"{onde}: `numeros_na_resposta` cita `{campo}`, que não é um número em"
                " `valor_esperado`."
            )

    contem_bruto = bruto.get("resposta_contem", [])
    if not isinstance(contem_bruto, list):
        raise ErroDeCaso(f"{onde}: `resposta_contem` deve ser uma lista.")
    contem = tuple(
        _lista_de_textos(item if isinstance(item, list) else [item], onde, "resposta_contem")
        for item in contem_bruto
    )
    nao_contem = _lista_de_textos(bruto.get("resposta_nao_contem", []), onde, "resposta_nao_contem")
    sem_litros = bruto.get("sem_litros_na_resposta", False)
    if not isinstance(sem_litros, bool):
        raise ErroDeCaso(f"{onde}: `sem_litros_na_resposta` deve ser verdadeiro ou falso.")

    return Caso(
        id=bruto["id"],
        semente=semente,
        perguntas=perguntas,
        chamadas_esperadas=chamadas,
        chamadas_proibidas=proibidas,
        valor_esperado=valor,
        numeros_na_resposta=numeros,
        resposta_contem=contem,
        resposta_nao_contem=nao_contem,
        sem_litros_na_resposta=sem_litros,
        arquivo=arquivo,
    )


def carregar_casos(pasta: Path = PASTA_CASOS) -> list[Caso]:
    """Lê todos os `*.json` da pasta, em ordem de nome. Levanta ErroDeCaso se algo estiver
    errado (formato, ferramenta inexistente, `id` repetido)."""
    casos: list[Caso] = []
    for arquivo in sorted(pasta.glob("*.json")):
        try:
            brutos = json.loads(arquivo.read_text(encoding="utf-8"))
        except json.JSONDecodeError as erro:
            raise ErroDeCaso(f"{arquivo.name}: JSON inválido ({erro}).") from erro
        if not isinstance(brutos, list):
            raise ErroDeCaso(f"{arquivo.name}: o arquivo deve conter uma lista de casos.")
        casos.extend(_ler_caso(bruto, arquivo.name) for bruto in brutos)
    repetidos = sorted({c.id for c in casos if sum(o.id == c.id for o in casos) > 1})
    if repetidos:
        raise ErroDeCaso(f"`id` repetido entre os casos: {', '.join(repetidos)}.")
    return casos
