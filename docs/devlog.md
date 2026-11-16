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
- Primeira ferramenta, `producao_por_periodo` (janela em `dias`): consulta em
  `app/db/producao.py`, função em `app/tools/producao.py`, registro neutro em
  `app/tools/registro.py` (descrição das ferramentas no registro, prompt de sistema em
  `prompts/`), 2 casos de eval em `evals/casos/producao_por_periodo.json` e testes com banco
  escrito à mão e cruzamento com um cálculo independente sobre os dados do gerador. 218
  testes passando. Limite conhecido: só aceita janela relativa em `dias` e `animal_id`; ainda
  não responde "produção da mimosa em 21/10". A proposta para isso (datas, busca por nome e
  regras do agente) está no rascunho `docs/adr/0005-periodo-das-consultas-de-producao.md`,
  com status `proposta`: nada foi aplicado na spec nem no código.
- A revisão da ferramenta reprovou a primeira versão: `animal_id` gigante levantava
  `OverflowError` em vez de `ValueError`. Corrigido com teste, junto com `argumentos` nulos
  ou malformados no registro, `animal_id` nulo documentado como "rebanho inteiro" e um teste
  de cruzamento que também compara a média. 241 testes passando.
- Lembrete: a descrição de `producao_por_periodo` cita "outra ferramenta" e diz que ainda não
  há como achar um animal pelo nome; revisar esse texto quando `animais_abaixo_da_media` e
  `listar_animais` existirem.
- Prazo estendido para segunda. Domingo: caminho completo com a ferramenta que já existe.
  Feito: cliente do LLM (`app/llm/client.py`, interface `ClienteLLM`, `ClienteGemini` com
  chamada manual de ferramentas e devolução da mensagem original do provedor, e
  `cliente_do_ambiente` com `LLM_PROVIDER`, `LLM_MODEL` e `GEMINI_API_KEY`), laço do agente
  (`app/agente.py`, limite de 5 passos, erro de ferramenta devolvido ao modelo como texto,
  pergunta limitada a 1000 letras), prompt de sistema (`prompts/sistema.md`) e linha de
  comando (`python -m app.ask "pergunta"`). Só `client.py` importa o SDK, e um teste garante
  isso. Todos os testes rodam sem rede e sem chave (cliente falso).
- Os testes com o Gemini de verdade são feitos pelo dono do projeto (o ambiente bloqueia o
  uso da chave pelo assistente); os resultados estão em `docs/estado-do-agente.md`.
- Plano de segunda, com um requisito novo: o sistema deve entender perguntas diferentes que
  pedem a mesma coisa, no linguajar simples de quem trabalha no campo. Vale para as evals
  (grupos de variantes com o mesmo resultado esperado, inclusive erros de digitação), para o
  prompt (vocabulário da fazenda) e para a busca por nome. Itens: ADR 0005 (datas),
  `listar_animais`, `animais_abaixo_da_media` e executor mínimo das evals.
- Primeiro teste real com o Gemini (`gemini-3.5-flash-lite`): "qual a produção total do
  rebanho na última semana?" e "qual a produção total na última semana?" chegaram à mesma
  chamada (`dias = 7`, rebanho inteiro) e ao mesmo resultado, 4.479,1 L (09 a 15/11/2026).
- ADR 0006 escrito: por que o MVP não usa RAG, embeddings nem banco vetorial, e quando
  reconsiderar.
- 21 testes manuais com o Gemini (15, mais 3 de reteste e 3 depois da reescrita do prompt),
  registrados em `docs/estado-do-agente.md`. Três problemas:
  um número reescrito pelo modelo ("cerca de 639,8" quando a ferramenta devolveu 639,87),
  pedido de confirmação desnecessário ("quer que eu faça?") e perda de contexto no "sim",
  porque cada chamada da linha de comando é independente. Prompt ajustado (números exatos,
  responder de uma vez, avisar que não lembra da conversa); falta reconferir com o modelo real.
  A solução de fato para o "sim", conversa com histórico, aguarda decisão.
- A revisão do cliente, do laço e da linha de comando reprovou a primeira versão por ajustes
  pequenos, todos aplicados: o ADR 0006 citava a spec e o ADR 0001 por coisas que eles não
  dizem (corrigido); falha de rede virava `Traceback` e não havia limite de tempo (agora vira
  `ErroLLM`, com timeout de 60 s, e a mensagem de erro leva só o código e o status, nunca o
  texto do provedor); o prompt prometia consulta por animal e não listava períodos passados
  como limite (corrigido); só uma exceção própria, `ErroDeFerramenta`, chega ao modelo, e há
  teto de 10 chamadas por passo; o teste de "só `client.py` importa o SDK" ficou mais
  robusto. 310 testes passando.
- `LLM_MODEL` foi definido no `.env` do dono do projeto; o `.env.example` não será alterado.
- A segunda revisão aprovou o cliente, o laço e a linha de comando, com ajustes menores ainda
  por tratar: a descrição de `producao_por_periodo` diz que a ferramenta consulta um animal por
  id, enquanto o prompt diz que o agente não consulta animal (alinhar os dois textos); o
  `except Exception` do cliente também esconde erro de programação como "falha de conexão";
  um ADR curto para o contrato "só `ErroDeFerramenta` chega ao modelo"; e pequenos acertos de
  texto no `estado-do-agente.md` e no exemplo numérico do prompt.
- Pendente: reconferir com o modelo real a recusa explícita do assunto estranho em pedido
  misto (teste 16) e a resposta a um "sim" solto (teste 14); decidir sobre conversa com
  histórico; ADR 0005 (datas e busca por nome); `animais_abaixo_da_media`, `listar_animais` e o
  executor das evals; push e primeira rodada da CI no Python 3.12. Antes do Docker: incluir
  `schema.sql` como `package-data` no `pyproject.toml`, senão o arquivo não vai na instalação
  não editável.
