"""Ferramentas de animais do agente. Todas somente leitura."""

import re
import sqlite3
import unicodedata
from collections.abc import Sequence
from difflib import SequenceMatcher
from typing import Any

from app.db import animais as repositorio
from app.tools.erros import ErroDeFerramenta

MAX_ANIMAIS = 100
MAX_SUGESTOES = 3
# Quando um nome vira sugestão: semelhança de pelo menos CORTE_SUGESTAO (0 a 1), ou estar a até
# MAX_EDICOES letras de distância (na escrita ou no som) para textos de MIN_LETRAS_PARA_EDICAO
# letras ou mais. Escolhido pela medição de `evals/busca_por_nome.py` (erros gerados para todos
# os animais e nomes que não existem no rebanho); os testes guardam as metas. Com uma única
# sugestão o agente segue com ela, então sugestão fraca levaria à vaca errada.
CORTE_SUGESTAO = 0.82
MAX_EDICOES = 1
MIN_LETRAS_PARA_EDICAO = 4
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


# Regras da chave de som, aplicadas em ordem sobre o texto já sem acento.
_REGRAS_DE_SOM = (
    (r"ch", "x"),
    (r"ph", "f"),
    (r"lh", "li"),
    (r"nh", "ni"),
    (r"qu", "k"),
    (r"gu(?=[ei])", "g"),
    (r"sc(?=[ei])", "s"),
    (r"c(?=[ei])", "s"),
    (r"c", "k"),
    (r"g(?=[ei])", "j"),
    (r"z", "s"),
    (r"y", "i"),
    (r"w", "v"),
    (r"\bh", ""),
    (r"(.)\1+", r"\1"),  # letras dobradas viram uma (ss, rr, ll)
)


def chave_de_som(texto: str) -> str:
    """Escrita simplificada pelo som, para comparar nomes escritos como se fala.

    "Cereja", "sereja" e "serreja" dão a mesma chave; "Chita" e "xita" também. O "ç" vira "s"
    antes de tirar os acentos, senão viraria "c".
    """
    chave = normalizar(texto.casefold().replace("ç", "s"))
    for padrao, troca in _REGRAS_DE_SOM:
        chave = re.sub(padrao, troca, chave)
    return chave


def _distancia(a: str, b: str) -> int:
    """Quantas letras é preciso pôr, tirar, trocar ou inverter de lugar para ir de `a` a `b`.

    Duas letras vizinhas trocadas de lugar ("lnua" e "luna") contam como um erro só.
    """
    anterior2: list[int] = []
    anterior = list(range(len(b) + 1))
    for i, letra_a in enumerate(a, 1):
        atual = [i] + [0] * len(b)
        for j, letra_b in enumerate(b, 1):
            custo = 0 if letra_a == letra_b else 1
            atual[j] = min(anterior[j] + 1, atual[j - 1] + 1, anterior[j - 1] + custo)
            if i > 1 and j > 1 and letra_a == b[j - 2] and a[i - 2] == letra_b:
                atual[j] = min(atual[j], anterior2[j - 2] + 1)
        anterior2, anterior = anterior, atual
    return anterior[len(b)]


def semelhanca(a: str, b: str) -> float:
    """Semelhança de 0 a 1: a maior entre a de letras em comum e a de poucas edições."""
    if not a or not b:
        return 0.0
    por_edicoes = 1 - _distancia(a, b) / max(len(a), len(b))
    return max(SequenceMatcher(None, a, b).ratio(), por_edicoes)


def _sugerir(digitado: str, candidatos: list[dict[str, Any]]) -> list[str]:
    """Até 3 nomes parecidos com o texto digitado (erro de digitação), do mais parecido ao menos.

    Compara com o nome inteiro e com cada palavra dele, pela escrita e pelo som, só com a
    biblioteca padrão do Python: não precisa de embeddings nem de banco novo (ADR 0006).
    """
    alvo, alvo_som = normalizar(digitado), chave_de_som(digitado)
    pontuacao: dict[str, float] = {}
    for animal in candidatos:
        palavras = animal["nome"].split()
        partes = (animal["nome"], *palavras) if len(palavras) > 1 else (animal["nome"],)
        melhor = max(
            max(semelhanca(alvo, normalizar(parte)), semelhanca(alvo_som, chave_de_som(parte)))
            for parte in partes
        )
        # Nome curto: um erro só já derruba a nota ("dvia" e Diva ficam em 0,75). Por isso,
        # também vale estar a uma letra de distância, na escrita ou no som. Só contra o nome
        # inteiro: contra cada palavra, "dita" casaria com o "diga" de um nome longo.
        nome = animal["nome"]
        edicoes = min(_distancia(alvo, normalizar(nome)), _distancia(alvo_som, chave_de_som(nome)))
        perto = edicoes <= MAX_EDICOES and len(alvo) >= MIN_LETRAS_PARA_EDICAO
        if melhor >= CORTE_SUGESTAO or perto:
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
    e Estrelinha). **Nome exato vence:** se o texto for exatamente o nome de algum animal, só os
    de nome exato vêm em `animais`, e os outros que contêm o trecho vêm em
    `outros_com_esse_trecho` (`mel` traz a Mel, e a Caramelo fica só nesse campo). Sem isso, a
    Mel nunca poderia ser escolhida pelo nome, porque "mel" sempre casaria também com Caramelo.
    Só os animais ativos aparecem, a menos que `incluir_inativos` seja verdadeiro. Retorna
    `animais` (cada um com `id`, `nome`, `sexo`, `raca`, `data_nascimento`, `status`, `lote`,
    `ativo`, `data_saida` e `motivo_saida`, ordenados por nome, até 100), `total` (quantos
    foram encontrados), `outros_com_esse_trecho`, `nome_considerado`, `sugestoes` e
    `encontrados_entre_inativos`.

    Erro de digitação (ADR 0005): quando `nome` não casa com ninguém, a ferramenta procura nomes
    parecidos e decide, em vez de deixar o modelo contar:
    - **um só** parecido: devolve esse animal em `animais` e o nome dele em `nome_considerado`
      (o agente segue com ele e avisa); se dois animais tiverem esse nome, devolve os dois, sem
      `nome_considerado` (o agente pergunta qual);
    - **mais de um**: devolve até 3 nomes em `sugestoes` e nenhum animal (o agente pergunta).
    `encontrados_entre_inativos` diz quantos animais que saíram da fazenda têm esse nome, quando
    a busca só entre os ativos não achou ninguém, ou quando o nome exato só existe entre os que
    saíram (os ativos que apenas contêm o texto ficam em `outros_com_esse_trecho`); nesse caso
    não há nome considerado nem sugestões.

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
    nome_considerado: str | None = None
    outros: list[str] = []
    entre_inativos = 0
    if nome_ok is None:
        encontrados = candidatos
    else:
        alvo = normalizar(nome_ok)
        encontrados = [a for a in candidatos if alvo in normalizar(a["nome"])]
        exatos = [a for a in encontrados if normalizar(a["nome"]) == alvo]
        if exatos and len(exatos) < len(encontrados):
            # Decidido aqui, e não pelo modelo (ADR 0005, revisão de 2026-11-17).
            outros = sorted({a["nome"] for a in encontrados if a not in exatos}, key=normalizar)
            encontrados = exatos
        if not exatos and not com_inativos:
            # Antes de sugerir um nome parecido ou de devolver só um nome que apenas contém o
            # texto, confere se o animal existe entre os que saíram: sugerir "Onça" para quem
            # procura a Dona (vendida), ou responder sobre a Caramelo para quem procura uma Mel
            # que saiu, seria enganoso. Achado da revisão de 2026-11-17.
            todos = repositorio.listar(conn, status_ok, lote_ok, True)
            inativos = [a for a in todos if not a["ativo"]]
            exatos_inativos = sum(1 for a in inativos if normalizar(a["nome"]) == alvo)
            if exatos_inativos:
                outros = sorted({a["nome"] for a in encontrados}, key=normalizar)
                encontrados = []
                entre_inativos = exatos_inativos
            elif not encontrados:
                entre_inativos = sum(1 for a in inativos if alvo in normalizar(a["nome"]))
        if not encontrados and not entre_inativos:
            parecidos = _sugerir(nome_ok, candidatos)
            if len(parecidos) == 1:
                # Decidido aqui, e não pelo modelo: nas evals ele tratava várias sugestões
                # como se fosse uma, assumindo a primeira.
                encontrados = [a for a in candidatos if a["nome"] == parecidos[0]]
                # Dois animais com esse nome (uma ativa e outra que saiu, com
                # `incluir_inativos`): sem nome considerado, e o agente pergunta qual.
                if len(encontrados) == 1:
                    nome_considerado = parecidos[0]
            else:
                sugestoes = parecidos

    encontrados.sort(key=lambda a: (normalizar(a["nome"]), a["id"]))
    return {
        "animais": [_publico(a) for a in encontrados[:MAX_ANIMAIS]],
        "total": len(encontrados),
        "outros_com_esse_trecho": outros,
        "nome_considerado": nome_considerado,
        "sugestoes": sugestoes,
        "encontrados_entre_inativos": entre_inativos,
    }
