"""Registro das ferramentas do agente.

O registro é uma tabela "nome da ferramenta -> definição". Adicionar uma ferramenta nova é
acrescentar uma entrada aqui, sem cadeia de `if/elif` no laço do agente.

O formato das definições é neutro (nome, descrição e JSON Schema dos parâmetros), sem
depender de nenhum provedor de LLM. Quem converte para o formato do Gemini (ou de outro
provedor) é `app/llm/client.py`.

A descrição de cada ferramenta fica aqui, ao lado do esquema dos parâmetros, porque faz
parte do contrato da função. O prompt de sistema, esse sim, fica em `prompts/`.
"""

import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.db.animais import LOTES_VALIDOS, STATUS_VALIDOS
from app.tools.animais import MAX_ANIMAIS, listar_animais
from app.tools.erros import ErroDeFerramenta
from app.tools.producao import producao_por_periodo


@dataclass(frozen=True)
class Ferramenta:
    nome: str
    descricao: str
    parametros: dict[str, Any]  # JSON Schema de um objeto
    funcao: Callable[..., dict[str, Any]]


FERRAMENTAS: tuple[Ferramenta, ...] = (
    Ferramenta(
        nome="producao_por_periodo",
        descricao=(
            "Soma a produção de leite (manhã e tarde, em litros) de um período, do rebanho "
            "inteiro (sem animal_id) ou de um animal (com animal_id). O período é dado de UM "
            "destes dois jeitos, nunca dos dois: `dias` (os últimos N dias, de 1 a 90, "
            "terminando no dia mais recente com registro) OU `data_inicio` e `data_fim` "
            "(as duas, no formato AAAA-MM-DD; para um dia só, a mesma data nas duas). "
            "Retorna litros_total, litros_manha_total, litros_tarde_total, litros_media_dia, "
            "dias_com_registro, data_inicio e data_fim. Se não houver registro no período, "
            "os litros vêm nulos e dias_com_registro vale 0: isso significa 'sem registro', "
            "e não 'zero litros'. USE para perguntas sobre quanto o rebanho ou um animal "
            "produziu em uma semana, em um mês, em um dia ou em qualquer período. NÃO USE "
            "para listar animais. Comparar animais ou saber quem produz menos ainda não é "
            "possível com nenhuma ferramenta. O animal_id é o número de identificação, e "
            "não o nome: para descobrir o id a partir do nome, use antes a ferramenta "
            "listar_animais."
        ),
        parametros={
            "type": "object",
            "properties": {
                "dias": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 90,
                    "description": (
                        "Os últimos N dias, de 1 a 90, terminando no dia mais recente com "
                        "registro (inclusive). Exemplo: 7 para a última semana. Não use junto "
                        "com data_inicio e data_fim."
                    ),
                },
                "data_inicio": {
                    "type": "string",
                    "description": (
                        "Primeiro dia do período, no formato AAAA-MM-DD (por exemplo, "
                        "2026-10-21). Use junto com data_fim, e não junto com dias."
                    ),
                },
                "data_fim": {
                    "type": "string",
                    "description": (
                        "Último dia do período, no formato AAAA-MM-DD. Para consultar um dia "
                        "só, use a mesma data de data_inicio."
                    ),
                },
                "animal_id": {
                    "type": "integer",
                    "description": (
                        "Id numérico do animal. Omita (ou envie null) para consultar o "
                        "rebanho inteiro."
                    ),
                },
            },
            "required": [],
        },
        funcao=producao_por_periodo,
    ),
    Ferramenta(
        nome="listar_animais",
        descricao=(
            "Lista os animais da fazenda, com filtros opcionais por status (a fase do "
            "animal), lote e nome. O nome é buscado por trecho, sem diferenciar maiúsculas "
            "nem acentos ('estrel' acha Estrela e Estrelinha). Só mostra animais ativos, a "
            "menos que incluir_inativos seja verdadeiro (use isso para animais vendidos, "
            "mortos ou abatidos). Retorna animais (cada um com id, nome, sexo, raca, "
            "data_nascimento, status, lote, ativo, data_saida e motivo_saida), total "
            f"(quantos foram encontrados; a lista mostra até {MAX_ANIMAIS}) e sugestoes "
            "(nomes parecidos, só quando nenhum nome casou, como 'mimoza' para 'Mimosa') e "
            "encontrados_entre_inativos (se for maior que zero, o animal procurado saiu da "
            "fazenda: repita a busca com incluir_inativos verdadeiro). "
            "USE para descobrir o id de um animal a partir do nome que o produtor usa, para "
            "contar ou listar animais por fase ou lote e para saber quais animais saíram da "
            "fazenda. Se mais de um animal casar com o nome, NÃO escolha por conta própria: "
            "mostre as opções ao produtor e pergunte qual. NÃO USE para saber quanto um "
            "animal produziu (para isso, use producao_por_periodo com o id)."
        ),
        parametros={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": list(STATUS_VALIDOS),
                    "description": "Fase do animal. Omita para não filtrar.",
                },
                "lote": {
                    "type": "string",
                    "enum": list(LOTES_VALIDOS),
                    "description": "Lote onde o animal está. Omita para não filtrar.",
                },
                "nome": {
                    "type": "string",
                    "description": (
                        "Nome, ou parte do nome, do animal. Não precisa de acento nem de "
                        "letras maiúsculas. Omita para não filtrar por nome."
                    ),
                },
                "incluir_inativos": {
                    "type": "boolean",
                    "description": (
                        "Verdadeiro para incluir também animais que saíram da fazenda "
                        "(vendidos, mortos, abatidos). Padrão: falso."
                    ),
                },
            },
            "required": [],
        },
        funcao=listar_animais,
    ),
)

REGISTRO: dict[str, Ferramenta] = {ferramenta.nome: ferramenta for ferramenta in FERRAMENTAS}


def declaracoes_neutras() -> list[dict[str, Any]]:
    """Definições das ferramentas no formato neutro, para o cliente do LLM traduzir."""
    return [
        {"name": f.nome, "description": f.descricao, "parameters": f.parametros}
        for f in FERRAMENTAS
    ]


def executar_ferramenta(
    conn: sqlite3.Connection, nome: str, argumentos: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Executa uma ferramenta pelo nome, com a conexão somente leitura.

    `argumentos` nulo vale como "nenhum argumento" (alguns provedores enviam uma chamada
    sem objeto de argumentos).

    Levanta ErroDeFerramenta (um ValueError, com mensagem em português que o laço do agente
    devolve ao modelo) se a ferramenta não existir, se os argumentos não forem um objeto de
    nomes em texto, ou se tiverem nomes desconhecidos ou faltarem. Erros de valor (como
    `dias` fora do intervalo) vêm da própria ferramenta, também como ErroDeFerramenta.
    """
    ferramenta = REGISTRO.get(nome) if isinstance(nome, str) else None
    if argumentos is None:
        argumentos = {}
    if not isinstance(argumentos, Mapping):
        raise ErroDeFerramenta("Os argumentos devem ser um objeto (nome do argumento -> valor).")
    if not all(isinstance(chave, str) for chave in argumentos):
        raise ErroDeFerramenta("Os nomes dos argumentos devem ser texto.")
    if ferramenta is None:
        disponiveis = ", ".join(sorted(REGISTRO))
        raise ErroDeFerramenta(f"Ferramenta desconhecida: {nome}. Disponíveis: {disponiveis}.")
    propriedades = ferramenta.parametros.get("properties", {})
    desconhecidos = sorted(set(argumentos) - set(propriedades))
    if desconhecidos:
        raise ErroDeFerramenta(
            f"Argumentos não reconhecidos em {nome}: {', '.join(desconhecidos)}."
        )
    faltando = [n for n in ferramenta.parametros.get("required", []) if n not in argumentos]
    if faltando:
        raise ErroDeFerramenta(
            f"Argumentos obrigatórios ausentes em {nome}: {', '.join(faltando)}."
        )
    return ferramenta.funcao(conn, **argumentos)
