"""Ferramentas de produção de leite do agente. Todas somente leitura."""

import sqlite3
from datetime import date, timedelta
from typing import Any

from app.db.producao import animal_existe, data_de_referencia, producao_no_periodo
from app.tools.erros import ErroDeFerramenta

DIAS_MINIMO = 1
DIAS_MAXIMO = 90
_LIMITE_INTEIRO_SQLITE = 2**63 - 1  # o SQLite não aceita inteiros maiores que isto


def _como_inteiro(valor: object, nome: str) -> int:
    """Aceita inteiro, ou decimal de valor inteiro (modelos às vezes enviam 7.0). Recusa o resto.

    Também recusa inteiros enormes: sem isso, o SQLite levantaria OverflowError em vez do
    ValueError com mensagem clara que o laço do agente devolve ao modelo.
    """
    if isinstance(valor, bool) or not isinstance(valor, int | float):
        raise ErroDeFerramenta(f"`{nome}` deve ser um número inteiro.")
    if isinstance(valor, float):
        if not valor.is_integer():  # também recusa nan e infinito
            raise ErroDeFerramenta(f"`{nome}` deve ser um número inteiro.")
        valor = int(valor)
    if abs(valor) > _LIMITE_INTEIRO_SQLITE:
        raise ErroDeFerramenta(f"`{nome}` está fora do intervalo aceito.")
    return valor


def producao_por_periodo(
    conn: sqlite3.Connection,
    dias: int,
    animal_id: int | None = None,
    *,
    data_referencia: date | None = None,
) -> dict[str, Any]:
    """Produção de leite (manhã + tarde, em litros) nos últimos `dias` dias.

    Sem `animal_id`, soma o rebanho inteiro (inclusive animais que saíram dentro da janela).
    A janela termina na data de referência, inclusive: `dias = 7` vai de ref - 6 até ref.
    A data de referência é a maior data com produção no banco (ADR 0003); o parâmetro
    `data_referencia` existe só para testes e não aparece no esquema mostrado ao modelo.

    Retorna `litros_total` (1 casa decimal), `litros_media_dia` (2 casas; nulo se não houve
    registro), `dias_com_registro`, `data_inicio` e `data_fim`. Para um animal, a média é
    `litros_total / dias_com_registro`; para o rebanho, é a média dos totais diários.

    `animal_id` nulo equivale a omitido (rebanho inteiro).

    Levanta ErroDeFerramenta (um ValueError) se `dias` estiver fora de 1 a 90, se `dias` ou
    `animal_id` não forem inteiros (ou forem grandes demais para o SQLite), ou se o animal
    não existir.
    """
    dias = _como_inteiro(dias, "dias")
    if not DIAS_MINIMO <= dias <= DIAS_MAXIMO:
        raise ErroDeFerramenta(f"`dias` deve estar entre {DIAS_MINIMO} e {DIAS_MAXIMO}.")
    if animal_id is not None:
        animal_id = _como_inteiro(animal_id, "animal_id")
        if not animal_existe(conn, animal_id):
            raise ErroDeFerramenta(f"Não existe animal com id {animal_id}.")

    if data_referencia is None:
        texto = data_de_referencia(conn)
        if texto is None:  # banco sem nenhuma produção: não há data de referência
            return {
                "litros_total": 0.0,
                "litros_media_dia": None,
                "dias_com_registro": 0,
                "data_inicio": None,
                "data_fim": None,
            }
        data_referencia = date.fromisoformat(texto)

    inicio = data_referencia - timedelta(days=dias - 1)
    agregada = producao_no_periodo(conn, inicio.isoformat(), data_referencia.isoformat(), animal_id)
    media = (
        round(agregada.litros_total / agregada.dias_com_registro, 2)
        if agregada.dias_com_registro
        else None
    )
    return {
        "litros_total": round(agregada.litros_total, 1),
        "litros_media_dia": media,
        "dias_com_registro": agregada.dias_com_registro,
        "data_inicio": inicio.isoformat(),
        "data_fim": data_referencia.isoformat(),
    }
