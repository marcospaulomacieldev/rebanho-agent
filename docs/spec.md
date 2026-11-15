# Especificação: Assistente de Rebanho

**Status:** em revisão. O modelo de dados (seção 4) e as regras das ferramentas (seção 3)
foram aprovados pelo dono do projeto em 2026-11-14. O restante é proposta; ajuste com seu
conhecimento de campo.

## 1. Problema
Quem gerencia uma fazenda leiteira precisa de respostas rápidas sobre o rebanho
("quem está produzindo menos?", "qual a produção total da semana?") e hoje depende
de planilhas ou de navegar em telas. Perguntar em linguagem natural é mais rápido.

## 2. Usuário
Produtor ou gestor de uma fazenda leiteira de pequeno e médio porte.

## 3. Escopo do MVP
- Perguntas em português sobre animais e produção de leite.
- Agente com **tool use**: o modelo escolhe e chama funções de consulta; o código as executa.
- API `POST /ask` que recebe a pergunta e devolve a resposta.
- Banco SQLite com **dados sintéticos** gerados por script com semente fixa (reproduzível).
- Conjunto de **evals** (25 perguntas) rodando automaticamente.

### Ferramentas planejadas (todas somente leitura)
| Função | O que faz | Retorno |
|---|---|---|
| `resumo_rebanho(dias=7)` | Totais do rebanho ativo e produção nos últimos `dias` | `animais_ativos`, `animais_por_status`, `litros_media_dia_total_rebanho`, `litros_media_dia_por_vaca_lactacao` |
| `listar_animais(status=None, lote=None, nome=None, incluir_inativos=False)` | Lista animais com filtros (todos opcionais) | lista com `id`, `nome`, `sexo`, `raca`, `data_nascimento`, `status`, `lote`, `ativo`, `data_saida`, `motivo_saida` |
| `producao_por_periodo(dias, animal_id=None)` | Produção de um animal ou, sem `animal_id`, do rebanho em N dias | `litros_total`, `litros_media_dia`, `dias_com_registro`, `data_inicio`, `data_fim` |
| `animais_abaixo_da_media(dias)` | Animais com produção abaixo da média do rebanho | `litros_media_dia_por_animal` (a média do rebanho, por animal) e lista com `id`, `nome`, `litros_media_dia`, `diferenca_litros` |

### Regras comuns das ferramentas
- **Data de referência ("hoje"):** é a maior `data` de `producao_leite`. Assim as respostas
  das evals não mudam com o passar do tempo (ver ADR 0003).
- **Janela:** `dias = 7` significa os 7 dias que terminam na data de referência, inclusive
  (de `ref - 6` até `ref`). `dias` vai de 1 a 90; fora disso a ferramenta retorna erro claro.
- **Valores inválidos:** `status` ou `lote` fora das listas fechadas, ou `id` inexistente,
  retornam erro claro.
- **Resultados vazios:** combinação de valores válidos mas impossível (por exemplo,
  `lactacao` com `recria`) ou `nome` sem correspondência retornam lista vazia. Animal que
  existe mas não produziu na janela retorna `litros_total = 0`, `dias_com_registro = 0` e
  `litros_media_dia` nulo. Em `animais_abaixo_da_media`, se ninguém tem registro na janela,
  a lista vem vazia e `litros_media_dia_por_animal` nulo. Banco sem nenhuma linha de
  produção (portanto sem data de referência): `producao_por_periodo` retorna
  `litros_total = 0`, `dias_com_registro = 0` e datas e médias nulas; `resumo_rebanho`
  retorna as contagens de animais e as médias de produção nulas.
- **Médias:** para um animal, `litros_media_dia` é `litros_total` dividido por
  `dias_com_registro`. Para o rebanho em `producao_por_periodo`, é a média dos totais
  diários. Em `animais_abaixo_da_media`, a **média do rebanho** (`litros_media_dia_por_animal`)
  é a média das médias diárias
  dos animais ativos que têm registro na janela, qualquer que seja o `status`. Em
  `resumo_rebanho`, `litros_media_dia_total_rebanho` é a média dos totais diários na janela,
  e `litros_media_dia_por_vaca_lactacao` é a média das médias diárias das vacas ativas com
  `status = 'lactacao'`. Os campos `litros_media_dia_total_rebanho` (total do rebanho, em
  centenas de litros) e `litros_media_dia_por_animal` (média por animal, em dezenas de
  litros) têm nomes diferentes de propósito, para não serem confundidos.
- **Arredondamento:** `litros_total` sai com 1 casa decimal e as médias com 2, para não
  aparecerem restos de soma de decimais (como `123.00000000001`).
- **Argumentos numéricos:** a ferramenta aceita número inteiro ou decimal de valor inteiro
  (`7.0`, que alguns modelos enviam) e recusa o resto com erro claro, inclusive inteiros
  maiores que o SQLite aceita (acima de 2^63 - 1). `animal_id` nulo equivale a omitido
  (rebanho inteiro).
- **Animais inativos:** `resumo_rebanho` e `animais_abaixo_da_media` consideram só
  `ativo = 1`. `listar_animais` também, a menos que `incluir_inativos` seja verdadeiro.
  `producao_por_periodo` do rebanho inclui o histórico de quem saiu dentro da janela (o
  leite foi produzido); com `animal_id` explícito, aceita animal inativo.
- **Filtro por `nome`:** busca por trecho, sem diferenciar maiúsculas nem acentos. O texto
  vindo do modelo é sempre passado como parâmetro vinculado (`?`), nunca montado dentro do
  SQL, e curingas (`%`, `_`) são escapados. É por esse filtro que o agente descobre o
  `animal_id` a partir do nome que o produtor usa.

## 4. Modelo de dados (revisado em 2026-11-14)

O MVP só consulta animais e produção de leite. `condicoes_dia` e `partos` são tabelas de
apoio: nenhuma ferramenta do MVP as usa. Elas existem para guardar desde já os dados
mínimos de uma análise futura de produção x fatores (clima, fase da lactação). Essa
análise está fora do escopo (seção 5) e só fará sentido com dados reais.

Termos: `CHECK` é uma regra que o próprio banco aplica a cada linha gravada; índice único
parcial é uma regra de unicidade que vale só para as linhas que atendem a uma condição;
exclusão lógica é marcar o registro como inativo em vez de apagá-lo; tabela `STRICT` é uma
tabela em que o SQLite recusa valor de tipo errado (sem isso, ele aceitaria o texto "abc"
numa coluna de litros).

### Tabelas
| Tabela | Colunas |
|---|---|
| `animais` | `id`, `nome`, `sexo`, `raca`, `data_nascimento`, `status`, `lote`, `ativo`, `data_saida`, `motivo_saida` |
| `producao_leite` | `id`, `animal_id`, `data`, `litros_manha`, `litros_tarde` |
| `condicoes_dia` | `data` (chave primária), `hora_ordenha_manha`, `hora_ordenha_tarde`, `chuva_manha`, `chuva_tarde`, `temp_min_c`, `temp_max_c` |
| `partos` | `id`, `animal_id`, `data_parto` |

### Valores permitidos (listas fechadas)
Os valores são identificadores sem acento nem barra (por isso `lactacao`, `mestica`),
para funcionarem sem surpresa em filtros e nos parâmetros das ferramentas.
- `status`: `lactacao`, `seca`, `novilha`, `corte`.
- `lote`: `alta_producao`, `media_producao`, `pre_parto`, `seca`, `recria`, `pasto`,
  `confinamento_inicial`, `confinamento_final`.
- `raca`: `gir`, `girolando_1_2`, `girolando_5_8`, `girolando_3_4`, `holandesa`, `tabapua`,
  `nelore`, `mestica`.
- `sexo`: `F` ou `M`, sempre preenchido. Só `status = 'corte'` pode ter `M`.
- `motivo_saida`: `morte`, `venda`, `abate`, `outro`.

### Combinações válidas de status e lote
| status | lotes possíveis |
|---|---|
| `lactacao` | `alta_producao`, `media_producao` |
| `seca` | `pre_parto`, `seca`, `pasto` |
| `novilha` | `recria`, `pasto` |
| `corte` | `pasto`, `confinamento_inicial`, `confinamento_final` |

`seca` aparece como status (a fase da vaca) e como lote (o grupo de manejo onde ela
fica). `pasto` é um lote, isto é, onde o animal está, e não uma fase produtiva.

### Onde cada regra mora
- **No banco** (`CHECK`, `UNIQUE`, chaves estrangeiras, tabelas `STRICT`): o tipo de cada
  coluna; as listas fechadas; as combinações de status e lote; "só `corte` pode ter sexo
  `M`"; a consistência entre `ativo`, `data_saida` e `motivo_saida`; `data_saida` não
  anterior a `data_nascimento`; nome sem espaços nas pontas; nome único entre ativos
  (índice único parcial); datas reais (AAAA-MM-DD) e horas reais (HH:MM); litros maiores
  ou iguais a zero; uma linha por animal e data em `producao_leite`; um parto por animal e
  data em `partos`; uma linha por dia em `condicoes_dia`; `temp_min_c` menor ou igual a
  `temp_max_c`; chuva só 0 ou 1.
- **No gerador e nos testes:** regras que cruzam tabelas, porque um `CHECK` não olha outra
  tabela: `data_saida` não pode ser anterior à última produção ou ao último parto do
  animal, e todo animal em `lactacao` tem ao menos um parto.

### Convenções
- **Exclusão lógica:** animal nunca é apagado. Ao sair da fazenda recebe `ativo = 0`,
  `data_saida` e `motivo_saida`. `ativo = 1` exige `data_saida` e `motivo_saida` vazios;
  `ativo = 0` exige os dois preenchidos. `ativo` é redundante com `data_saida`, mas é
  mantido por clareza e para simplificar os filtros.
- **Nome único só entre animais ativos** (um nome pode ser reaproveitado depois que o
  animal sai). A unicidade ignora maiúsculas e minúsculas só em letras ASCII; "Áurea" e
  "áurea" (com acento) contam como nomes diferentes no banco. Como a busca por nome nas
  ferramentas ignora acentos, o gerador evita nomes que só diferem por acento.
- Datas em texto ISO (`2026-11-12`); horários em `HH:MM`; litros em L; temperaturas em °C.
- `chuva_manha` e `chuva_tarde` (0 ou 1) valem para o momento do início de cada ordenha
  (`hora_ordenha_manha` e `hora_ordenha_tarde`). `temp_min_c` e `temp_max_c` são do dia,
  registradas no fim do dia.
- **Ordenhas:** toda vaca em lactação é ordenhada nos dois turnos, todos os dias.
  `litros_manha` e `litros_tarde` são obrigatórios. Dia sem produção = sem linha
  (por exemplo, animal que não está em lactação). Dado ausente, que só deve ocorrer em
  dados reais, será estimado pela média dos dois últimos registros do mesmo turno do
  animal (ver pergunta em aberto na seção 9).
- **Produção e status:** só animais em `lactacao` têm produção recente. Quem hoje está
  `seca`, `novilha` ou `corte` pode ter produção antiga, de quando estava em lactação.
- `partos` guarda todos os partos (não só o último); da tabela saem os dias em lactação e
  a ordem de parto.
- **Alimentação:** não é modelada. Por ora a dieta é inferida pelo `lote`.
- `lote` e `status` são o estado atual; não há histórico de mudanças de lote.
- Bezerros e reprodutores não têm `status` e estão fora do MVP.

## 5. Fora do escopo
Autenticação, interface web, escrita no banco, RAG, previsões, análise de produção x
fatores (clima, fase da lactação) e treino de modelos. O modelo de dados apenas guarda
os dados necessários para essa análise futura.

## 6. Critérios de sucesso
- O agente escolhe a ferramenta correta em pelo menos 90% das 25 perguntas das evals.
- Os números da resposta coincidem com o banco em pelo menos 90% dos casos.
- Nenhuma operação de escrita é possível.
- Custo e latência de cada requisição são registrados.

## 7. Restrições
- Dados sintéticos apenas (nenhum dado real de fazenda).
- Ferramentas somente leitura; o modelo nunca escreve SQL livre.
- Chaves de API só em variáveis de ambiente.
- Provedor de LLM trocável (ver ADR 0002).

## 8. Riscos
- **Alucinação numérica:** a resposta deve vir do resultado das ferramentas, não da "memória" do modelo.
- **Perguntas fora do escopo:** o agente deve recusar com educação.
- **Prompt injection:** textos vindos do banco (como nomes de animais) não podem ser tratados como instruções.

## 9. Perguntas em aberto
- Quais perguntas reais um produtor faria? (base para as evals)
- Nas raças `girolando_*`, a fração se refere ao sangue holandês (convenção do
  Girolando) ou ao sangue Gir? Confirmar com o produtor.
- Ao estimar um dado ausente (média dos dois últimos registros do turno), o valor
  estimado deve ser marcado como estimado? Recomendação: sim, para não misturar dado
  medido com dado inventado na análise futura. Decidir antes de importar dados reais.
- Dados reais não podem passar pelo plano gratuito do Gemini (ver ADR 0002). Antes de
  usá-los, é preciso rever o provedor e a restrição da seção 7.

## 10. Evolução futura (fora do MVP)
- Análise de produção x fatores com dados reais.
- Importador da planilha real da fazenda.
- Alimentação como dado próprio, se houver mais lotes ou dietas diferentes.
- Histórico de lote e de status.
- Controle de confinamento, novilhas e vacas secas.
- Bezerros e reprodutores.
