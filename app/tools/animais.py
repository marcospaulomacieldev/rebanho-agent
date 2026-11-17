"""Ferramentas de animais do agente. Todas somente leitura."""

import sqlite3
import unicodedata
from collections.abc import Sequence
from difflib import SequenceMatcher
from typing import Any

from app.db import animais as repositorio
from app.tools.erros import ErroDeFerramenta

MAX_ANIMAIS = 100
MAX_SUGESTOES = 3
CORTE_SUGESTAO = 0.6  # semelhança mínima (0 a 1) entre o texto digitado e um nome
MAX_CARACTERES_NOME = 100


def normalizar(texto: str) -> str:
    """Minúsculas, sem acentos e com espaços simples: base da busca por nome."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    return " ".join(sem_acento.casefold().split())


def _filtro_de_lista(valor: object, nome: str, validos: Sequence[str]) -> str | None:
    """Filtro de lista fechada. Nulo ou texto vazio equivale a omitido."""
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    if not isinstance(valor, str):
        raise ErroDeFerramenta(f"`{nome}` deve ser um texto.")
    limpo = valor.strip().lower()
    if limpo not in validos:
        raise ErroDeFerramenta(
            f"`{nome}` inválido: {valor[:40]!r}. Valores válidos: {', '.join(validos)}."
        )
    return limpo


def _nome_ou_nulo(valor: object) -> str | None:
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    if not isinstance(valor, str):
        raise ErroDeFerramenta("`nome` deve ser um texto.")
    limpo = valor.strip()
    if len(limpo) > MAX_CARACTERES_NOME:
        raise ErroDeFerramenta(f"`nome` é longo demais (máximo de {MAX_CARACTERES_NOME} letras).")
    return limpo


def _booleano(valor: object, nome: str) -> bool:
    if valor is None:
        return False
    if not isinstance(valor, bool):
        raise ErroDeFerramenta(f"`{nome}` deve ser verdadeiro ou falso.")
    return valor


def _sugerir(alvo: str, candidatos: list[dict[str, Any]]) -> list[str]:
    """Até 3 nomes parecidos com o texto digitado (erro de digitação), do mais parecido ao menos.

    Compara com o nome inteiro e com cada palavra dele, e usa só a semelhança de letras da
    biblioteca padrão do Python: não precisa de embeddings nem de banco novo (ADR 0006).
    """
    pontuacao: dict[str, float] = {}
    for animal in candidatos:
        normal = normalizar(animal["nome"])
        melhor = max(
            SequenceMatcher(None, alvo, parte).ratio() for parte in (normal, *normal.split())
        )
        if melhor >= CORTE_SUGESTAO:
            pontuacao[animal["nome"]] = max(melhor, pontuacao.get(animal["nome"], 0.0))
    ordenados = sorted(pontuacao, key=lambda nome: (-pontuacao[nome], normalizar(nome)))
    return ordenados[:MAX_SUGESTOES]


def _publico(animal: dict[str, Any]) -> dict[str, Any]:
    return {**animal, "ativo": bool(animal["ativo"])}


def listar_animais(
    conn: sqlite3.Connection,
    status: str | None = None,
    lote: str | None = None,
    nome: str | None = None,
    incluir_inativos: bool | None = False,
) -> dict[str, Any]:
    """Lista animais com filtros opcionais por status, lote e nome.

    O nome é buscado por trecho, sem diferenciar maiúsculas nem acentos (`estrel` acha Estrela
    e Estrelinha). Só os animais ativos aparecem, a menos que `incluir_inativos` seja
    verdadeiro. Retorna `animais` (cada um com `id`, `nome`, `sexo`, `raca`,
    `data_nascimento`, `status`, `lote`, `ativo`, `data_saida` e `motivo_saida`, ordenados por
    nome, até 100), `total` (quantos foram encontrados), `sugestoes` (até 3 nomes parecidos,
    só quando `nome` foi informado e nenhum animal casou) e `encontrados_entre_inativos`
    (quantos animais que saíram da fazenda têm esse nome, quando a busca só entre os ativos
    não achou ninguém; nesse caso não há sugestões).

    Valores nulos ou texto vazio nos filtros equivalem a omitidos. Levanta ErroDeFerramenta
    (um ValueError) se `status` ou `lote` estiver fora das listas fechadas, se `nome` não for
    texto ou for longo demais, ou se `incluir_inativos` não for verdadeiro ou falso. Uma
    combinação válida mas impossível (como `lactacao` com `recria`) devolve lista vazia.
    """
    status_ok = _filtro_de_lista(status, "status", repositorio.STATUS_VALIDOS)
    lote_ok = _filtro_de_lista(lote, "lote", repositorio.LOTES_VALIDOS)
    nome_ok = _nome_ou_nulo(nome)
    com_inativos = _booleano(incluir_inativos, "incluir_inativos")

    candidatos = repositorio.listar(conn, status_ok, lote_ok, com_inativos)
    sugestoes: list[str] = []
    entre_inativos = 0
    if nome_ok is None:
        encontrados = candidatos
    else:
        alvo = normalizar(nome_ok)
        encontrados = [a for a in candidatos if alvo in normalizar(a["nome"])]
        if not encontrados and not com_inativos:
            # Antes de sugerir um nome parecido, confere se o animal existe entre os que
            # saíram: sugerir "Onça" para quem procura a Dona (vendida) seria enganoso.
            todos = repositorio.listar(conn, status_ok, lote_ok, True)
            entre_inativos = sum(
                1 for a in todos if not a["ativo"] and alvo in normalizar(a["nome"])
            )
        if not encontrados and not entre_inativos:
            sugestoes = _sugerir(alvo, candidatos)

    encontrados.sort(key=lambda a: (normalizar(a["nome"]), a["id"]))
    return {
        "animais": [_publico(a) for a in encontrados[:MAX_ANIMAIS]],
        "total": len(encontrados),
        "sugestoes": sugestoes,
        "encontrados_entre_inativos": entre_inativos,
    }
