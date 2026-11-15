# Diário de desenvolvimento

Registre aqui, a cada dia: o que fez, o que errou, o que aprendeu e o que decidiu.
Serve de memória do projeto: decisões, erros e aprendizados.

## 2026-11-11
- Projeto definido: assistente de consulta ao rebanho com tool use, em torno de dados sintéticos.
- Repositório criado com estrutura base, `CLAUDE.md`, `docs/spec.md` e dois ADRs (o de provedor de LLM ainda é proposta).
- Próximo: revisar `docs/spec.md`, rodar `git init` e fazer o plano do dia 1 no Claude Code.

## 2026-11-14
- Plano do dia 1 discutido e aprovado. O código só começou depois que o modelo de dados
  foi revisado (ver abaixo).
- Modelo de dados revisado em `docs/spec.md` (seção 4): sem `brinco`, listas fechadas para
  `status`, `lote` e `raca`, exclusão lógica de animais (`ativo`, `data_saida`,
  `motivo_saida`) e duas tabelas de apoio para análise futura (`condicoes_dia`, `partos`).
- Decisões registradas em `docs/adr/0003-data-de-referencia-das-consultas.md` e
  `docs/adr/0004-modelo-de-dados-e-exclusao-logica.md`.
- Dependência `google-genai` adicionada ao `pyproject.toml` (SDK atual do Gemini; o antigo
  `google-generativeai` está descontinuado). Ambiente virtual `.venv` criado.
- Modelo do Gemini testado com a chave (texto e tool use): `gemini-2.5-flash` retorna 404
  ("no longer available to new users"); `gemini-3.5-flash-lite` passou nos dois testes
  (0,6 a 0,7 s) e será o padrão em `LLM_MODEL`; `gemini-3.5-flash` passou, mas a chamada de
  ferramenta levou 33,8 s; `gemini-3.8-flash` deu 503 (alta demanda), não reavaliado.
- A revisão (`/revisar`) reprovou a primeira versão da spec; os achados foram corrigidos,
  incluindo um erro da proposta inicial: ordenha ausente não pode ser "linha ausente"
  quando cada linha tem os dois turnos.
- A segunda revisão reprovou de novo (regras das ferramentas ainda ambíguas); corrigido
  na spec: janela de dias, retornos, inativos, vazios e busca por nome.
- Código do commit 1: `app/db/schema.sql` (regras no banco), `app/db/connection.py`
  (conexão somente leitura com duas barreiras: `mode=ro` e `query_only`) e
  `tests/test_schema.py` (`pytest` e `ruff` passando).
- A terceira revisão aprovou os três grupos de commit. Ajustes aplicados em seguida:
  tabelas `STRICT` (o SQLite aceitava o texto "abc" em coluna de litros, e testes novos
  provam que agora recusa), `CHECK` de saída não anterior ao nascimento, nome sem espaços
  nas pontas, testes da matriz completa de status x lote (32 combinações, 10 válidas) e das
  duas barreiras de somente leitura, e nomes distintos para as duas médias de rebanho na
  spec (`litros_media_dia_total_rebanho` e `litros_media_dia_por_animal`).
- Commits feitos: docs, dependência `google-genai` e schema com conexão somente leitura.
- Gerador de dados (`app/db/seed.py`, `scripts/seed_data.py`, `tests/test_seed.py`): 60
  animais (55 ativos), 90 dias (2026-08-18 a 2026-11-15), 3119 registros de produção, 87
  partos e semente fixa 42. A função `gerar_dados` é pura (só gera) e `gravar_dados` grava;
  `gerar_banco` recusa sobrescrever sem `--forcar`. Média das vacas em lactação: 20,1 L/dia.
  As 4 vacas de baixa produção (12,6 a 13,0 L/dia; a quinta pior tem 15,4) são as 4 piores,
  e uma delas tem o nome em forma de instrução, para a eval de prompt injection. Sem curva
  de lactação e sem efeito do clima, de propósito.
- A revisão do gerador aprovou com ajustes, todos aplicados: a garantia das 4 piores só
  valia para a semente 42 (quebrava em 2 de 40 sementes); agora o piso das vacas normais é
  15,5 L e o teto das de baixa produção é 13,2 L, e um teste cobre 40 sementes (500
  conferidas à mão, nenhuma quebra). `--forcar` só apaga arquivo que seja um banco SQLite
  (cabeçalho conferido), a geração roda antes de apagar o banco antigo, e `Dados` guarda
  tuplas. 172 testes passando.
- Pendente: as duas ferramentas de leite, cliente do LLM, laço do agente e a entrega de
  domingo (pergunta em linguagem natural pela linha de comando). Antes do Docker: incluir
  `schema.sql` como `package-data` no `pyproject.toml`, senão o arquivo não vai na
  instalação não editável.
