# Assistente de Rebanho (projeto de portfólio)

## Objetivo
Agente que responde perguntas em linguagem natural sobre um rebanho leiteiro,
usando tool use (o modelo chama funções Python) sobre SQLite com dados sintéticos.
Projeto de portfólio: a prioridade é qualidade, avaliação (evals) e clareza,
não quantidade de recursos.

## Antes de começar qualquer sessão
Ler `docs/spec.md` (o que construir) e `docs/devlog.md` (onde paramos).

## Stack
Python 3.11+ (o CI usa 3.12), FastAPI, SQLite, pytest, ruff.
O SDK do provedor de LLM será definido em `docs/adr/0002-provedor-de-llm.md`.
Docker entra no final.

## Comandos
- Instalar: `pip install -e ".[dev]"`
- Testes: `pytest`
- Lint: `ruff check .`
- Evals: `python -m evals.run` (a criar)
- API: `uvicorn app.main:app --reload` (a criar)

## Regras
- As ferramentas do agente são SOMENTE LEITURA. O modelo nunca escreve SQL livre.
- Nunca commitar `.env` ou chaves; usar variáveis de ambiente.
- Prompts ficam em `prompts/`, nunca embutidos no código.
- Todo acesso ao LLM passa por `app/llm/client.py`, para o provedor ser trocável.
- Funções públicas com type hints e teste.
- Para qualquer coisa não trivial: propor um plano e esperar aprovação antes de codar.
- Commits pequenos, no formato `feat:`, `fix:`, `test:`, `docs:`.
- Decisões de arquitetura novas viram um ADR em `docs/adr/`.
- O dono do projeto está aprendendo: explicar o porquê das decisões e cada termo técnico novo.

## Fora do escopo (por enquanto)
Autenticação, front-end, escrita no banco, RAG.
