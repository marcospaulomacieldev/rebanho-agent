"""Validações de argumentos compartilhadas pelas ferramentas."""

from app.tools.erros import ErroDeFerramenta

_LIMITE_INTEIRO_SQLITE = 2**63 - 1  # o SQLite não aceita inteiros maiores que isto


def como_inteiro(valor: object, nome: str) -> int:
    """Aceita inteiro, ou decimal de valor inteiro (modelos às vezes enviam 7.0). Recusa o resto.

    Também recusa inteiros enormes: sem isso, o SQLite levantaria OverflowError em vez do
    ErroDeFerramenta com mensagem clara que o laço do agente devolve ao modelo.
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
