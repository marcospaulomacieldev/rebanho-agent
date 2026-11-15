# ADR 0005: Período das consultas de produção (dias ou intervalo de datas)

**Status:** proposta (rascunho; ainda não aprovada). A spec e o código **não** foram alterados
por este texto.

## Contexto
O produtor pergunta de forma informal por um dia específico, por exemplo "produção mimosa
21/04" ou "quanto a mimosa produziu no dia 24 de abril". Hoje `producao_por_periodo(dias,
animal_id=None)` só aceita "os últimos N dias até a data de referência" (a maior data de
`producao_leite`, ADR 0003), com `dias` limitado a 90. Isso gera cinco problemas:

1. **Conta de calendário pelo modelo.** Para chegar a um dia, o modelo teria de calcular
   `dias`. "21/04" exigiria `dias = 208`, acima do limite. Mesmo uma data dentro do limite
   devolve a **soma** de vários dias, que o modelo poderia apresentar como se fosse o dia.
2. **Nome para id.** A ferramenta recebe `animal_id`; quem traduz "mimosa" é
   `listar_animais(nome=...)`, que ainda não existe.
3. **Dia sem registro.** A spec atual manda devolver `litros_total = 0` para animal sem
   produção na janela. Zero é uma medição; a ausência de registro é outra coisa.
4. **O agente não conhece a data de referência**, então não resolve "ontem" nem datas sem ano.
5. **Os exemplos do produtor são de abril**, e o banco sintético vai de 2026-08-18 a
   2026-11-15. "21/04" cai fora do intervalo, o que serve de caso de eval.

Afetam o mesmo problema as três ferramentas que recebem `dias`: `resumo_rebanho`,
`producao_por_periodo` e `animais_abaixo_da_media`. `listar_animais` não é afetada.

## Decisão proposta
**Opção (a):** `producao_por_periodo` ganha `data_inicio` e `data_fim` opcionais, com dois
modos mutuamente exclusivos (parâmetros que não podem ser usados juntos):

- modo 1: `dias` (janela relativa, como hoje);
- modo 2: `data_inicio` e `data_fim`, as duas, em `AAAA-MM-DD`, inclusive. Um dia = as duas
  iguais.

Um único resolvedor de período (`app/tools/periodo.py`) serve as três ferramentas de produção.
O retorno ganha `litros_manha_total` e `litros_tarde_total`, para perguntas de um dia
("de manhã e de tarde"). Sem registro, os litros voltam **nulos** (e não zero), com
`dias_com_registro = 0`.

## Alternativas
| Critério | (a) datas em `producao_por_periodo` | (b) ferramenta `producao_do_dia(animal_id, data)` |
|---|---|---|
| Número de ferramentas | 4 (nenhuma nova) | 5 |
| Escolha pelo modelo | Uma ferramenta para qualquer período; risco de combinar parâmetros errado | Duas ferramentas que se sobrepõem ("ontem", "semana passada") |
| Retrocompatibilidade | `dias` continua; deixa de ser obrigatório | Total |
| `dias` e datas juntos | Erro claro | Não se aplica |
| Intervalo qualquer ("outubro") | Cobre | Não cobre (pediria uma terceira ferramenta) |
| Manhã e tarde | Campos novos no retorno | Natural |
| Outras ferramentas | Reaproveitam o resolvedor | Ficam sem |

Também descartadas: aceitar "21/04" dentro da ferramenta (esconde a interpretação do ano; o
modelo traduz datas bem se souber a referência) e um parâmetro `data` único (não cobre
intervalo).

## Regras propostas (e onde ficam)
| Caso | Regra | Onde |
|---|---|---|
| Data sem ano ("21/04") | A data **mais recente** com aquele dia e mês que **não seja posterior** à data de referência. Formato dia/mês. Com referência em 2026-11-15, "24/12" vira 2025-12-24. | Prompt, com a data de referência injetada |
| Nome ambíguo | 0 resultados ativos: repetir com `incluir_inativos=true` antes de dizer que não existe. 1: seguir. Mais de 1: **perguntar qual**, citando nome, status e lote, sem chamar a ferramenta de produção até a resposta. Sem atalho para nome exato. | Prompt; `listar_animais` devolve os campos que distinguem |
| Dia sem registro | `dias_com_registro = 0` e litros nulos. O agente diz "sem registro em 21/10", nunca "0 litros". | Spec/ferramenta e prompt |
| Data fora do intervalo | Erro claro citando o intervalo ("O banco tem registros de 2026-08-18 a 2026-11-15"). Data posterior à referência também é erro. Período só parcialmente dentro conta apenas os dias com registro. | Ferramenta (erro) e prompt (repassar) |
| Datas relativas | "ontem", "semana passada" e "outubro" são relativos à **data de referência**, e o agente diz a data usada. Em pergunta de um dia, responde manhã, tarde e total. | Prompt |
| Modos misturados | `dias` junto com datas, só uma data, ou nenhum modo: erro claro que diz como corrigir (`resumo_rebanho` assume `dias = 7`). | Ferramenta |

A data de referência chega ao agente no prompt de sistema (`prompts/sistema.md`), calculada **do
banco**, e não do relógio. Com dados reais, "hoje" será a última ordenha registrada (ADR 0003).

## Mudanças propostas na spec (não aplicadas)
- Tabela de ferramentas: `resumo_rebanho(dias=None, data_inicio=None, data_fim=None)`,
  `producao_por_periodo(dias=None, data_inicio=None, data_fim=None, animal_id=None)` com
  retorno `litros_total`, `litros_manha_total`, `litros_tarde_total`, `litros_media_dia`,
  `dias_com_registro`, `data_inicio`, `data_fim`, e `animais_abaixo_da_media` com os mesmos
  modos de período.
- A regra "Janela" vira "Período", com os dois modos, os erros acima e o tratamento de
  período parcialmente fora do intervalo.
- Em "Resultados vazios", o zero vira nulo.
- Nova subseção "Comportamento do agente" com as regras da tabela.

## Casos de eval que isso exige (`evals/casos/producao_por_periodo.json`)
Valores conferidos no banco gerado com a semente 42 (Mimosa tem id 28). Como a sequência tem
mais de uma chamada, o caso passa a listar `chamadas_esperadas`; os casos atuais, de uma
chamada só, continuam válidos.

| # | Pergunta | Esperado |
|---|---|---|
| 1 | "produção mimosa 21/10" | `listar_animais(nome="mimosa")` e `producao_por_periodo(animal_id=28, data_inicio="2026-10-21", data_fim="2026-10-21")`. Manhã 9,8, tarde 9,0, total 18,8 |
| 2 | "quanto a mimosa produziu no dia 21 de outubro" | Idêntico ao 1 |
| 3 | "quanto a mimosa produziu ontem" | Data 2026-11-14: 9,2, 7,8 e 17,0 |
| 4 | "produção mimosa 21/04" | Erro com o intervalo 2026-08-18 a 2026-11-15, sem número inventado |
| 5 | "quanto a estrela produziu ontem" | `listar_animais` devolve Estrela (id 44, novilha) e Estrelinha (id 29, lactação); o agente pergunta qual, sem chamar a ferramenta de produção |
| 6 | "quanto a açucena produziu em 21/10" | Açucena (id 34) é seca e não tem registro: "sem registro", sem "0 litros" |
| 7 | "quanto a dona produziu em 1 de outubro" | Dona (id 56) está inativa (vendida em 2026-10-07): o agente repete com `incluir_inativos=true`; valor a calcular no banco |
| 8 | "produção da mimosa em 24/12" | Ano inferido 2025, fora do intervalo |

Exemplo de caso:
```json
{
  "id": "mimosa-dia-especifico",
  "pergunta": "produção mimosa 21/10",
  "semente": 42,
  "chamadas_esperadas": [
    {"ferramenta": "listar_animais", "argumentos": {"nome": "mimosa"}},
    {"ferramenta": "producao_por_periodo",
     "argumentos": {"animal_id": 28, "data_inicio": "2026-10-21", "data_fim": "2026-10-21"}}
  ],
  "valor_esperado": {"litros_manha_total": 9.8, "litros_tarde_total": 9.0, "litros_total": 18.8}
}
```
Os casos 5 e 6 dependem dos nomes que a semente 42 gera; um teste deve falhar se o gerador
mudar e eles deixarem de valer.

## Consequências
- O modelo precisa traduzir datas informais, e as evals medem isso. Expressões como "outubro"
  exigem que ele saiba o tamanho do mês.
- A busca por nome (`listar_animais`) passa a ser pré-requisito de qualquer pergunta sobre um
  animal; sem ela, essas perguntas não têm resposta.
- Trocar zero por nulo muda o que `producao_por_periodo` retorna hoje para animal sem
  produção na janela (hoje `litros_total = 0`).
- Uma única regra de período reduz o risco de as três ferramentas divergirem.

## Pontos em aberto
1. Confirmar a regra "perguntar sempre que houver mais de um animal", sem atalho para nome
   exato (por exemplo, "estrela" casa com Estrela e Estrelinha).
2. Decidir se `listar_animais` (filtros `nome` e `incluir_inativos`) entra antes de
   `animais_abaixo_da_media` no cronograma, já que as perguntas reais são sobre um animal em
   um dia.

## Termos
- **Parâmetros mutuamente exclusivos:** dois modos que não podem ser usados juntos; a
  ferramenta recusa a combinação.
- **Nulo × zero:** zero é uma medição ("produziu 0 litros"); nulo é ausência de informação
  ("sem registro").
- **ISO (`AAAA-MM-DD`):** formato de data com o ano primeiro, sem ambiguidade entre dia e mês.
