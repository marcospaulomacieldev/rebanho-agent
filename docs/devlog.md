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
- Primeiro push para o GitHub (repositório privado `rebanho-agent`). A CI passou na primeira
  rodada, no Python 3.12 e em Linux, sem chave de API e sem rede (34 s).

## 2026-11-16
- Plano de segunda aprovado: nome ambíguo sempre pergunta, `listar_animais` antes de
  `animais_abaixo_da_media`, conversa com histórico depois das evals. Requisito central: o
  produtor pergunta do jeito dele e o sistema chega ao mesmo resultado.
- **ADR 0005 aceito** e spec atualizada (seção 3): período por `dias` ou por
  `data_inicio` + `data_fim`, "sem registro" como nulo e não zero, `listar_animais` com
  `sugestoes`, nova subseção "Comportamento do agente" e um critério de sucesso para perguntas
  equivalentes (90%).
- **`producao_por_periodo` com datas:** resolvedor único em `app/tools/periodo.py`, retorno com
  `litros_manha_total` e `litros_tarde_total`, erros claros (datas misturadas, no futuro, fora do
  intervalo, com o intervalo disponível). Nulo e texto vazio nos parâmetros opcionais valem como
  omitidos, porque o Gemini os envia.
- **`listar_animais`:** busca por nome sem diferenciar acento nem maiúsculas, filtros por fase e
  lote, `incluir_inativos`, limite de 100 e `sugestoes` para erro de digitação ("mimoza" sugere
  Mimosa), só com a biblioteca padrão (`difflib`), sem embeddings (ADR 0006).
- **Prompt reescrito** e agora montado a cada pergunta, com as datas do banco (primeiro dia,
  último dia e dia da semana); nenhum texto de usuário ou de ferramenta entra no prompt de
  sistema. Traz as regras de nome ambíguo, "semana passada", "sem registro" e dia/mês sem ano.
- **Interface de teste:** `python -m app.ask` sem pergunta abre um modo interativo (comandos
  `/chamadas`, `/ajuda`, `/sair`, tempo e passos por pergunta, o prompt é relido a cada
  pergunta); `scripts/perguntar.cmd` abre tudo com um comando. É só para desenvolvimento.
- **Erro corrigido:** o ADR 0005 dizia que "estrela" casava com "Estrelinha". Não casa (só
  "estrel" casa com os dois). A ambiguidade real do banco é "mel", que casa com Mel e Caramelo.
  O ADR e os casos de eval foram corrigidos.
- CI: `ubuntu-24.04` e `actions/checkout`/`setup-python` na v7 (ainda sem rodar no GitHub).
- 429 testes passando; as evals de `listar_animais` (7 casos) e de `producao_por_periodo` (4
  casos) são dados conferidos contra o banco.
- **Executor de evals** (ADR 0007, `python -m evals.run`): casos com `variantes`,
  `chamadas_esperadas` em sequência, recusas e pergunta de volta; checagens determinísticas
  (ferramenta, argumentos idênticos ou equivalentes por resultado, números em português no
  texto, fidelidade numérica); repetições por pergunta; espera e nova tentativa em erro 429 e
  503, com falha de infraestrutura fora das taxas; relatório no terminal e em JSON
  (`evals/resultados/`, fora do Git). 23 casos e 30 perguntas. `ErroLLM` ganhou o atributo
  `codigo`. Testado com cliente falso (516 testes passando).
- **Primeira amostra das evals com o modelo real** (`gemini-3.5-flash-lite`, árvore com mudanças
  não commitadas sobre o commit 26bb80f): 3 dos 23 casos (`rebanho-ultima-semana`,
  `mimosa-dia-especifico`, `mel-nome-ambiguo`), 7 perguntas, 2 repetições, 14 execuções válidas
  e nenhuma falha de infraestrutura. Todas as 14 passaram em todas as checagens (ferramenta,
  argumentos, números 12/12, fidelidade, comportamento 2/2, consistência 2/2 casos). É amostra
  pequena e só de 3 casos: **não mede os critérios de 90% da spec**. Latência do modelo por
  pergunta: mediana 14,9 s e percentil 90 de 17,5 s, com 2,57 passos em média; é alta para o
  uso real e precisa ser investigada.
- **Revisão dos blocos de segunda: aprovado com ajustes**, todos aplicados. Os principais: nas
  evals, só rede, chave, 429 e 5xx ficam fora das taxas (resposta vazia ou bloqueada agora
  conta como reprovação); casos frouxos ganharam trechos de recusa e alternativas; rodada
  interrompida sai com código 1 e grava o parcial, inclusive com Ctrl+C; números de datas não
  contam mais como valores; `listar_animais` devolve `encontrados_entre_inativos` em vez de
  sugerir nomes errados para animal que saiu da fazenda; o prompt cita o lote no nome ambíguo;
  a descrição de `producao_por_periodo` não cita mais uma ferramenta que não existe. Cinco casos
  novos (semana passada, mês passado, pedido misto, pergunta vaga, "sim" solto): 28 casos e 35
  perguntas. 543 testes passando e 6 pulados (casos sem chamada esperada).
- A amostra de 14 execuções foi medida **antes** desses ajustes de prompt, de ferramenta e de
  casos; não vale para a versão atual.
- **Primeira rodada completa das evals** (commit `3529001`, `gemini-3.5-flash-lite`, 28 casos,
  35 perguntas, **uma repetição por pergunta**, nenhuma falha de infraestrutura): 31/35
  execuções aprovadas. Ferramenta correta 31/32, argumentos equivalentes 27/28 (idênticos
  23/28), números 19/19, fidelidade numérica 35/35, comportamento 11/14, consistência entre
  variantes 5/5 casos. Latência do modelo: mediana 3,6 s, percentil 90 de 11,5 s (a amostra
  anterior teve 14,9 s de mediana; a causa da diferença não foi investigada). Com uma
  repetição, as taxas ainda são indícios.
- As 4 falhas: um caso mal escrito por mim (`listar-mimosa-id` pedia o número do animal, que o
  prompt proíbe mostrar); o pedido misto ignorou a parte fora do assunto, como nos testes
  manuais; no erro de digitação o agente seguiu com "Mimosa" em vez de perguntar; no nome
  ambíguo perguntou certo, mas sem fase nem lote.
- Ajustes depois da rodada (ainda não medidos com o modelo): erro de digitação com uma só
  sugestão segue com ela e avisa, com mais de uma pergunta; nome ambíguo cita a fase e o lote
  só se ajudar;
- **Busca por nome generalizada.** O primeiro limiar (0,82) tinha sido escolhido com 22
  exemplos meus; o dono do projeto apontou que isso não generalizava. Criei uma medição sem
  modelo (`python -m evals.busca_por_nome`): erros gerados para todos os animais e 40 nomes
  que não existem no rebanho. Na primeira versão do gerador (199 erros), só a comparação de
  letras perdia 27 erros, quase todos de troca de som ("sereja" para Cereja) e de letras trocadas. A busca
  passou a comparar também pelo som e a aceitar uma letra de distância (nomes de 4 letras ou
  mais). Na semente 42, com erros no meio e nas pontas da palavra: 342 de 347 erros chegam ao
  animal certo, nenhum vira sugestão única errada, e 4 dos 40 nomes inexistentes viram outra
  vaca (risco aceito, com aviso na resposta). A regra foi escolhida olhando a semente 42; nas
  sementes 1, 7 e 2024, não usadas na escolha, também não houve nenhuma sugestão única errada,
  e de 3 a 4 nomes inexistentes foram assumidos. As metas viraram
  testes (`tests/test_busca_por_nome.py`), e o teste novo pegou o animal de nome-instrução
  aparecendo como sugestão de "Dita", corrigido. Os casos de eval de erro de digitação ganharam
  variantes ("mimoza", "mimsa", "mimossa"), um nome inexistente ("caramela") e dois casos de
  várias sugestões ("estrelinah", "sereja"): 31 casos e 40 perguntas.
- **Rodada dirigida das evals (2026-11-17)**, com mudanças não commitadas sobre `3529001`, 7
  casos, 27 execuções, 3 repetições: os casos corrigidos passaram em todas (erro de digitação
  em três grafias 9/9, nome ambíguo 3/3, caso reescrito 3/3). Dois problemas novos: com mais de
  uma sugestão de nome, o agente assumiu a primeira (1 de 6 certas); e no pedido misto ele
  **inventou números** nas três repetições (44.408, 125.805 e 210.669 L, sem chamar ferramenta;
  o real é 19.639,6 L). A checagem de fidelidade numérica pegou as três. Primeira hipótese: o
  exemplo do prompt terminava em "o rebanho produziu...", e o modelo completaria a frase. O
  exemplo foi retirado, entrou a regra "nunca escreva litros sem ter chamado a ferramenta nesta
  resposta", e quem decide entre uma sugestão de nome e várias passou a ser a ferramenta
  (`nome_considerado`), e não o modelo.
- **Segunda rodada dirigida (2026-11-17)**, mesmos 7 casos, 27 execuções: 24 aprovadas. Os
  erros de digitação ficaram resolvidos (estrelinah 3/3, sereja 3/3, caramela 3/3, mimoza 9/9;
  comportamento 24/24; 63 chamadas ao modelo, contra 79). O pedido misto continuou 0/3,
  inventando (136.216, 42.138 e 136.002 L): **a hipótese do exemplo estava errada.**
- **Trava de fidelidade numérica (ADR 0008).** A regra "todo número vem de uma ferramenta" saiu
  só do prompt e foi para o código: o laço do agente não entrega litros que não vieram de uma
  ferramenta daquela pergunta. Na primeira vez pede correção ao modelo
  (`prompts/correcao_litros.md`); se ele insistir, a pessoa recebe uma mensagem sem números. A
  definição é a mesma das evals e agora mora em `app/fidelidade.py`. Aplicada às 103 respostas
  reais salvas, dispara só nas 6 invenções. O relatório das evals ganhou a linha "Trava de
  litros sem origem", para a trava não esconder a falha do modelo. A regra do pedido misto
  também foi reescrita (primeiro a ferramenta, depois o texto), com base numa segunda hipótese
  ainda não verificada. Nada disso foi medido com o modelo real ainda.
- **Rodadas depois da trava (2026-11-17).** Pedido misto isolado: 3/3, sem a trava agir (a
  reordenação do prompt resolveu; a trava fica como rede de segurança). Rodada completa, 3
  repetições: 89 de 92 execuções válidas aprovadas; ferramenta 83/83, números 53/53,
  fidelidade 92/92, consistência entre variantes 6/6, comportamento 54/57. Interrompida no fim
  pelo limite de uso (6 não executadas; `listar-mimoza-considera-mimosa` não rodou). A trava
  agiu 1 vez (`rebanho-ultima-semana`, aprovada depois), mas o texto barrado não era guardado.
- **Nome exato vence (revisão do ADR 0005).** As 3 falhas eram todas de "quanto a mel
  produziu ontem": o agente respondeu sobre a Mel em vez de perguntar. A regra estava errada:
  "mel" é trecho de "Caramelo", e a pergunta pronta "quanto a Mel produziu?" caía de novo nos
  dois, então a Mel nunca podia ser escolhida. Agora a ferramenta devolve só o nome exato e põe
  os outros em `outros_com_esse_trecho`; a ambiguidade real é medida por "estrel". Também: a
  trava guarda o texto barrado (`RespostaAgente.barradas`), e o relatório das evals o mostra,
  para distinguir invenção, arredondamento e falso positivo. Ainda não medido com o modelo.
- **Rodada com versões misturadas (2026-11-17, 11:06).** Uma rodada começou enquanto as
  mudanças acima eram aplicadas: os casos e a ferramenta vieram da versão antiga (ids antigos,
  "mel" ainda devolvendo dois animais), mas o relatório registrou o hash do prompt novo, porque
  o executor lia a versão no **fim** da rodada. Os resultados dela não valem para nenhuma das
  duas versões. Corrigido: `evals/run.py` lê a versão (prompt, arquivos alterados e o conteúdo
  deles) antes da rodada, confere de novo no fim, e o relatório avisa se ela mudou no meio.
  (O caso antigo do "mel" passou 3/3 aqui e 0/3 na rodada completa, mas não dá para comparar:
  o prompt pode ter mudado no meio desta rodada, porque ele é lido a cada pergunta.)
- **Rodada do nome exato (2026-11-17, 11:22)**, 9 execuções: `estrel-nome-ambiguo` 3/3 e
  `listar-mel-nome-exato` 3/3; `mel-nome-exato-vence` 2/3, com a Mel escolhida nas três. A
  falha foi de data: "ontem" virou 15/11 (o "hoje" dos dados) em vez de 14/11. Nos relatórios
  salvos até essa rodada, foi 1 erro em 51 execuções (recorte: perguntas com "ontem" que
  chamaram a ferramenta de produção, sem a rodada com versões misturadas). Correção: o prompt passou a trazer "hoje",
  "ontem" e "anteontem" já calculados a partir do banco, para o modelo só copiar a data.
- **Medição das datas prontas (2026-11-17, 11:43)**: `mimosa-ontem` 6/6, `mel-nome-exato-vence`
  3/3 e `mimoza-erro-de-digitacao` 7/7 (2 não executadas por falha de conexão); 16 de 16
  válidas aprovadas, trava sem agir, sem aviso de versão misturada. Latência mediana de 19 s,
  bem acima dos 3,3 s da rodada completa: a investigar.
- **Revisão de código (2026-11-17): aprovado com ressalvas, 9 achados, todos corrigidos.**
  Os de comportamento: (1) o executor das evals quebrava no Windows com diff contendo "Á", "Í"
  ou aspas curvas (a saída do git era lida em cp1252), agora lida em UTF-8, com teste num
  repositório temporário; (2) nome exato só entre os inativos virava a vaca ativa parecida sem
  aviso; (3) sugestão com dois animais do mesmo nome trazia `nome_considerado` e os dois
  juntos; (4) a trava aceitava qualquer número da pergunta ("7 dias" liberava "7 litros") e a
  checagem das evals usava outra definição. Agora a definição é uma só, e a fidelidade das
  evals olha também o texto barrado, para não dar 100% só porque a trava segurou. Também:
  ADR 0008 com o que foi medido depois da trava (incluindo o disparo não explicado em
  `rebanho-ultima-semana`); números do ADR 0005 datados por versão do gerador; testes que
  diziam mais do que testavam (um deles olhava `sugestoes`, que no contrato novo nunca tem um
  nome só, e passava sem testar nada); hash da versão gravado no relatório.
- **Achado em aberto (não corrigido):** nome inexistente que é trecho de outro animal vira
  esse animal sem aviso. "Ana" acha a Cigana como achado direto, e o agente responderia sobre
  a Cigana. É o mesmo mecanismo do "mel" em "Caramelo", mas sem nome exato para vencer.
- **Segunda revisão de código (2026-11-17): aprovado com ressalvas, sem bloqueio; 6 ajustes
  feitos.** A fidelidade das evals passou a contar qualquer texto barrado como falha direto
  (recalcular contra resultados que chegaram depois poderia esconder uma invenção que
  coincidisse com o valor real); o rótulo do relatório ficou neutro ("Execuções em que a trava
  de litros barrou uma resposta"); o registro da versão aceita nomes de arquivo com acento
  (`ls-files -z`) e grava hash nulo, com aviso, se o git falhar; o recorte do "1 em 51" e as
  versões do gerador (199 e 194 erros) ficaram explícitos. Limite registrado no ADR 0008: a
  trava aceita litros que o produtor escreveu na pergunta, então "a Mimosa deu 30 litros
  ontem?" pode ser confirmado sem consulta; o caso `confirmar-numero-do-produtor` mede isso.
- **Rodada de conferência antes do commit (2026-11-17, 12:47)**, 6 casos, 30 execuções, 3
  repetições: 30/30 aprovadas (ferramenta 27/27, números 27/27, fidelidade 30/30,
  comportamento 18/18); `confirmar-numero-do-produtor` 3/3, consultando o banco; trava sem
  barrar nada; sem aviso de versão mudada. Latência mediana de 17,5 s (percentil 90 de 42,7 s),
  ainda bem acima dos 3,3 s da rodada completa da madrugada: continua a investigar.
- Também: a regra do pedido misto foi para a seção
  "Fora do assunto", com exemplo; o caso `listar-mimosa-id` virou "a mimosa ainda está na
  fazenda?"; caso novo com várias sugestões (`estrelinah`). Revisão registrada no ADR 0005.
- Pendente: nova rodada dos casos afetados; investigar a latência; `animais_abaixo_da_media`; README; reconferir com o modelo real o prompt novo, a recusa do assunto estranho em
  pedido misto (teste 16) e o "sim" solto (teste 14). Antes do Docker: incluir `schema.sql`
  como `package-data` no `pyproject.toml`, senão o arquivo não vai na instalação não editável.
