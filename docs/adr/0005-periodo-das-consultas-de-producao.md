# ADR 0005: Período das consultas de produção (dias ou intervalo de datas)

**Status:** aceita (2026-11-16). As mudanças correspondentes na spec foram aplicadas na mesma data.

## Contexto
O produtor pergunta de forma informal por um dia específico, por exemplo "produção mimosa
21/04" ou "quanto a mimosa produziu no dia 24 de abril". Antes deste ADR,
`producao_por_periodo(dias, animal_id=None)` só aceitava "os últimos N dias até a data de
referência" (a maior data de `producao_leite`, ADR 0003), com `dias` limitado a 90. Isso gerava
cinco problemas:

1. **Conta de calendário pelo modelo.** Para chegar a um dia, o modelo teria de calcular
   `dias`. "21/04" exigiria `dias = 208`, acima do limite. Mesmo uma data dentro do limite
   devolve a **soma** de vários dias, que o modelo poderia apresentar como se fosse o dia.
2. **Nome para id.** A ferramenta recebe `animal_id`; quem traduz "mimosa" é
   `listar_animais(nome=...)`.
3. **Dia sem registro.** A spec devolvia `litros_total = 0` para animal sem produção na janela.
   Zero é uma medição; a ausência de registro é outra coisa.
4. **O agente não conhece a data de referência**, então não resolve "ontem" nem datas sem ano.
5. **Os exemplos do produtor são de abril**, e o banco sintético vai de 2026-08-18 a
   2026-11-15. "21/04" cai fora do intervalo, o que serve de caso de eval.

Têm o mesmo problema as três ferramentas que recebem `dias`: `resumo_rebanho`,
`producao_por_periodo` e `animais_abaixo_da_media`. `listar_animais` não é afetada.

## Decisão
**Opção (a):** `producao_por_periodo` ganha `data_inicio` e `data_fim` opcionais, com dois
modos mutuamente exclusivos (parâmetros que não podem ser usados juntos):

- modo 1: `dias` (janela relativa, como antes);
- modo 2: `data_inicio` e `data_fim`, as duas, em `AAAA-MM-DD`, inclusive. Um dia = as duas
  iguais.

Um único resolvedor de período (`app/tools/periodo.py`) serve as três ferramentas de produção.
O retorno ganha `litros_manha_total` e `litros_tarde_total`, para perguntas de um dia
("de manhã e de tarde"). Sem registro, os litros voltam **nulos** (e não zero), com
`dias_com_registro = 0`.

A busca de animal por nome (`listar_animais`) devolve também `sugestoes` quando nenhum nome
casa mas há nomes parecidos (erro de digitação, como "mimoza").

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

## Regras (e onde ficam)
| Caso | Regra | Onde |
|---|---|---|
| Data sem ano ("21/04") | A data **mais recente** com aquele dia e mês que **não seja posterior** à data de referência. Formato dia/mês. Com referência em 2026-11-15, "24/12" vira 2025-12-24. | Prompt, com a data de referência informada |
| Nome ambíguo | 0 resultados ativos: repetir com `incluir_inativos=true` antes de dizer que não existe. 1: seguir. Mais de 1: **perguntar sempre qual**, citando nome, status e lote, sem chamar a ferramenta de produção até a resposta e sem atalho para nome exato. | Prompt; `listar_animais` devolve os campos que distinguem |
| Nome com erro de digitação | Sem resultado, mas com `sugestoes`: perguntar "Você quis dizer X?". | `listar_animais` (sugestões) e prompt |
| Dia sem registro | `dias_com_registro = 0` e litros nulos. O agente diz "sem registro em 21/10", nunca "0 litros". | Spec/ferramenta e prompt |
| Data fora do intervalo | Erro claro citando o intervalo ("O banco tem registros de 2026-08-18 a 2026-11-15"). Data posterior à referência também é erro. Período só parcialmente dentro conta apenas os dias com registro. | Ferramenta (erro) e prompt (repassar) |
| Datas relativas | "ontem", "semana passada" e "outubro" são relativos à **data de referência**, e o agente diz a data usada. Em pergunta de um dia, responde manhã, tarde e total. | Prompt |
| Modos misturados | `dias` junto com datas, só uma data, ou nenhum modo: erro claro que diz como corrigir (`resumo_rebanho` assume `dias = 7`). | Ferramenta |

A data de referência chega ao agente no prompt de sistema (`prompts/sistema.md`), calculada **do
banco**, e não do relógio. Com dados reais, "hoje" será a última ordenha registrada (ADR 0003).
O agente continua sem poder escolher a data de referência das ferramentas: ela só é informada
para ele interpretar a pergunta.

## Mudanças na spec (aplicadas em 2026-11-16)
- Tabela de ferramentas: `resumo_rebanho`, `producao_por_periodo` e `animais_abaixo_da_media`
  aceitam os dois modos de período; `producao_por_periodo` devolve `litros_manha_total` e
  `litros_tarde_total`; `listar_animais` devolve `animais`, `total` e `sugestoes`.
- A regra "Janela" virou "Período", com os dois modos, os erros acima e o tratamento de período
  parcialmente fora do intervalo.
- Em "Resultados vazios", o zero virou nulo.
- Nova subseção "Comportamento do agente" com as regras da tabela.
- Novo critério de sucesso: perguntas equivalentes devem chegar à mesma ferramenta e aos mesmos
  argumentos.

## Casos de eval que isso exige (`evals/casos/`)
Valores conferidos no banco gerado com a semente 42 (Mimosa tem id 28). Como a sequência tem
mais de uma chamada, o caso passa a listar `chamadas_esperadas`; os casos de uma chamada só
continuam válidos.

| # | Pergunta | Esperado |
|---|---|---|
| 1 | "produção mimosa 21/10" | `listar_animais(nome="mimosa")` e `producao_por_periodo(animal_id=28, data_inicio="2026-10-21", data_fim="2026-10-21")`. Manhã 9,8, tarde 9,0, total 18,8 |
| 2 | "quanto a mimosa produziu no dia 21 de outubro" | Idêntico ao 1 |
| 3 | "quanto a mimosa produziu ontem" | Data 2026-11-14: 9,2, 7,8 e 17,0 |
| 4 | "produção mimosa 21/04" | Erro com o intervalo 2026-08-18 a 2026-11-15, sem número inventado |
| 5 | "quanto a mel produziu ontem" | `listar_animais(nome="mel")` devolve Caramelo (id 14, lactação) e Mel (id 10, lactação), porque "mel" é parte de "Caramelo"; o agente pergunta qual, sem chamar a ferramenta de produção |
| 6 | "quanto a açucena produziu em 21/10" | Açucena (id 34) é seca e não tem registro: "sem registro", sem "0 litros" |
| 7 | "quanto a dona produziu em 1 de outubro" | Dona (id 56) está inativa (vendida em 2026-10-07): o agente repete com `incluir_inativos=true`; valor a calcular no banco |
| 8 | "produção da mimosa em 24/12" | Ano inferido 2025, fora do intervalo |
| 9 | "quanto a mimoza produziu em 21/10" (erro de digitação) | `listar_animais` não acha "mimoza", devolve `sugestoes` com Mimosa; o agente pergunta se quis dizer a Mimosa |

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
  animal.
- Trocar zero por nulo muda o que `producao_por_periodo` retornava para animal sem produção na
  janela (antes `litros_total = 0`).
- Uma única regra de período reduz o risco de as três ferramentas divergirem.
- Perguntar sempre quando o nome é ambíguo custa uma volta a mais na conversa. Isso só funciona
  bem com conversa com histórico; sem ela, a resposta do produtor ("a primeira") chega sem
  contexto. A conversa com histórico foi adiada para depois das evals.

## Decisões do dono do projeto (2026-11-16)
1. Nome ambíguo: o agente **sempre pergunta qual**, sem atalho para nome exato.
2. `listar_animais` entra antes de `animais_abaixo_da_media` no cronograma.
3. Conversa com histórico: fica para depois das evals, que vão mostrar se ela faz falta.

## Termos
- **Parâmetros mutuamente exclusivos:** dois modos que não podem ser usados juntos; a
  ferramenta recusa a combinação.
- **Nulo × zero:** zero é uma medição ("produziu 0 litros"); nulo é ausência de informação
  ("sem registro").
- **ISO (`AAAA-MM-DD`):** formato de data com o ano primeiro, sem ambiguidade entre dia e mês.
