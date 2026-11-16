"""Erros das ferramentas do agente."""


class ErroDeFerramenta(ValueError):
    """Erro previsto de uma ferramenta, com mensagem escrita para o modelo ler.

    É a única exceção cuja mensagem o laço do agente devolve ao modelo. Qualquer outra
    exceção (inclusive um ValueError que venha de uma biblioteca) é tratada como erro
    interno: vira uma mensagem genérica, e o detalhe vai só para o log.
    """
