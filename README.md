# Assistente de Rebanho

Agente de IA generativa que responde, em português, perguntas sobre um rebanho
leiteiro ("quais vacas produziram abaixo da média nos últimos 7 dias?"). O modelo
não inventa números: ele chama funções de consulta (tool use) e responde com base
no resultado.

> Status: em construção (projeto de portfólio).

## Por que este projeto
- Mostra um sistema com LLM de ponta a ponta: dados, ferramentas, agente, API.
- Foca em **avaliação**: um conjunto de evals mede se o agente escolhe a ferramenta certa
  e responde com os números corretos.
- Parte de um domínio real (pecuária leiteira).

## Como funciona
_(diagrama e descrição da arquitetura: a preencher após o dia 3)_

## Como rodar
_(a preencher)_

## Resultados das evals
_(tabela comparando modelos: a preencher após o dia 4)_

## Decisões de arquitetura
Ver [`docs/adr/`](docs/adr/).

## Estrutura
Ver [`CLAUDE.md`](CLAUDE.md) e [`docs/spec.md`](docs/spec.md).
