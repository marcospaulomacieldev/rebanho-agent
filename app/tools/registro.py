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
            "Soma a produção de leite (manhã + tarde, em litros) dos últimos N dias, do "
            "rebanho inteiro (sem animal_id) ou de um animal (com animal_id). Retorna "
            "litros_total, litros_media_dia, dias_com_registro, data_inicio e data_fim. "
            "USE para perguntas como 'qual a produção total da última semana?' ou 'quanto "
            "o rebanho produziu em 30 dias?'. NÃO USE para listar animais nem para saber "
            "quem produz menos (isso é outra ferramenta). Só aceita uma janela em dias "
            "contada a partir da data mais recente com registro: não consulta uma data "
            "específica. O animal_id é o número de identificação do animal, e não o nome; "
            "se o usuário citar um animal pelo nome, ainda não há como descobrir o id, "
            "então avise que só consegue consultar por id ou o rebanho inteiro."
        ),
        parametros={
            "type": "object",
            "properties": {
                "dias": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 90,
                    "description": (
                        "Quantidade de dias, de 1 a 90, terminando na data mais recente com "
                        "registro (inclusive). Exemplo: 7 para a última semana."
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
            "required": ["dias"],
        },
        funcao=producao_por_periodo,
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
