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

## Revisão (2026-11-16, depois da primeira rodada das evals)
A rodada sobre o commit `3529001` (35 execuções, uma por pergunta) mostrou dois problemas nas
regras de nome. As linhas "Nome ambíguo" e "Nome com erro de digitação" da tabela acima ficam
substituídas por:
- **Erro de digitação com uma só sugestão:** o agente segue com o nome sugerido e avisa no
  começo da resposta ("Não achei 'mimoza'; considerei a Mimosa."). Motivo: sem memória de
  conversa, a resposta "sim" do produtor a "Você quis dizer?" chega sem contexto e não serve
  para nada. Com **mais de uma** sugestão, o agente continua perguntando, sem consultar a
  produção.
- **Quando um nome vira sugestão.** Com a regra acima, uma sugestão fraca faria o agente
  responder sobre a vaca errada, então a comparação foi refeita e medida de forma sistemática
  (`evals/busca_por_nome.py`): um erro de cada tipo para todos os animais ativos da semente 42
  (letra faltando, letras trocadas de lugar, letra dobrada, troca de som, h inicial) e 40
  nomes de vaca que não existem no rebanho. O gerador de erros mudou durante o trabalho, então
  os totais abaixo não são todos comparáveis: a primeira versão (2026-11-16) gerava 199 erros, a
  segunda 194 (com a regra final, 188 chegavam ao animal certo), e a atual (2026-11-17), que
  também erra no começo e no fim da palavra, gera 347. Só os números da versão atual são
  reproduzíveis com `python -m evals.busca_por_nome`.
  - Regra adotada: semelhança de pelo menos 0,82 pela escrita **ou pelo som** (ç, ss, z e s; ch
    e x; lh e li; letras dobradas), ou estar a **uma letra** de distância do nome inteiro
    (duas letras trocadas de lugar contam como uma), para textos de 4 letras ou mais.
  - Resultado na semente 42, versão atual do gerador (347 erros): 342
    chegam ao animal certo (52 direto, 259 com uma sugestão, 31 com várias, e o agente
    pergunta), 4 ficam sem resultado (nomes de 3 letras, como "mil" para Mel), 1 cai em outro
    animal que existe com aquele nome exato ("lua" para Luna) e nenhum vira uma sugestão única
    errada.
  - **A regra foi escolhida olhando esta medição na semente 42**, e as metas dos testes são os
    valores observados nela. Para não confundir ajuste com generalização, a mesma medição foi
    repetida nas sementes 1, 7 e 2024 (outros conjuntos de nomes, não usados na escolha):
    nenhuma sugestão única errada em nenhuma delas, de 3 a 4 erros sem resultado e de 3 a 4 dos
    40 nomes inexistentes assumidos (entre eles "Dita" -> Chita e "Rosa" -> Romã, quando essas
    vacas não existem). Essas duas metas de segurança rodam nos testes para as quatro sementes.
  - A meta de no máximo 4 nomes inexistentes assumidos está **na borda**: dá exatamente 4 nas
    sementes 42, 7 e 2024, e 5 na semente 3, que não está nos testes (achado da revisão de
    2026-11-17). Ela não foi afrouxada para passar; um nome novo no gerador pode quebrá-la, e
    então é preciso decidir de novo, não só mudar o número.
  - Comparativo: o limiar antigo de 0,6 deixava o animal de nome-instrução aparecer como
    sugestão; 0,82 só pela escrita deixava 27 de 199 erros sem resultado (primeira versão do
    gerador), quase todos de troca
    de som e de letras trocadas, que são os erros de quem escreve como fala.
  - Risco que não tem solução pela semelhança: 4 dos 40 nomes inexistentes viram outra vaca
    ("Caramela" -> Caramelo, "Malhadinha" -> Malhada, "Serenata" -> Serena, "Estrelada" ->
    Estrela), porque estão tão perto quanto um erro de digitação. O aviso "considerei a
    Caramelo" na primeira frase é a proteção; o dono do projeto aceitou esse risco (opção (a),
    2026-11-16). Exigir 4 letras evita que a maioria dos nomes curtos inexistentes vire outra
    vaca ("Lia" viraria Lua, "Eva" viraria Uva), mas não todos: com 4 letras, "Luna" vira Lua
    na semente 3 e "Dita" vira Chita na semente 7.
  - A regra de uma letra vale só para o nome inteiro: aplicada a cada palavra, "Dita" casaria
    com o "diga" do animal de nome-instrução.
  - As metas estão em `tests/test_busca_por_nome.py`: nenhuma sugestão única errada, pelo menos
    95% dos erros chegando ao animal certo e no máximo 4 nomes inexistentes assumidos.
- **Quem decide entre uma sugestão e várias (2026-11-17):** a rodada dirigida das evals (27
  execuções, 3 repetições) mostrou que o modelo não respeita essa distância: com duas ou três
  sugestões, ele assumiu a primeira em 5 de 6 execuções. A decisão passou para a ferramenta:
  com um só nome parecido, `listar_animais` já devolve o animal e o nome em
  `nome_considerado`; com mais de um, devolve só `sugestoes`, sem nenhum animal (e, portanto,
  sem id para o modelo consultar por conta própria).
- **Nome ambíguo:** o agente cita o nome de cada animal e, se ajudar a diferenciar, a fase e o
  lote. Quem conhece as vacas pelo nome não precisa do lote para escolher entre Mel e Caramelo.

## Revisão (2026-11-17): nome exato vence
A decisão 1 de 2026-11-16 ("sempre pergunta qual, sem atalho para nome exato") foi revertida
pelo dono do projeto. Na rodada completa das evals (92 execuções válidas, 3 repetições), o
caso "quanto a mel produziu ontem" falhou 3 de 3: o agente respondeu sobre a Mel em vez de
perguntar. A análise mostrou que o defeito estava na regra, e não no agente: "mel" é trecho de
"Caramelo", então a pergunta pronta que o agente sugeria ("quanto a Mel produziu ontem?") caía
de novo nos dois animais. **Pela regra antiga, a Mel nunca podia ser escolhida pelo nome.**

Regra nova, aplicada na ferramenta (e não no prompt, pela mesma lição da revisão anterior):
- se o texto digitado, sem acento e sem diferença de maiúscula, for exatamente o nome de algum
  animal, `listar_animais` devolve só os de nome exato em `animais`; os outros que contêm o
  trecho vão em `outros_com_esse_trecho`, só como informação;
- sem nome exato, nada muda: "estrel" devolve Estrela e Estrelinha, e o agente pergunta qual;
- dois animais de nome exato (por exemplo, uma Mimosa ativa e outra que saiu, com
  `incluir_inativos`) continuam voltando juntos, e o agente pergunta.

Na semente 42, "mel" é o único nome ativo que também é trecho de outro, então a regra só muda
esse caso. O caso de eval `mel-nome-ambiguo` virou `mel-nome-exato-vence`, e a ambiguidade
real passou a ser medida por `estrel-nome-ambiguo`.

Ajustes da revisão de código (2026-11-17), cobertos por testes com bancos montados à mão,
porque nenhum dos dois acontece no banco da semente 42:
- **Nome exato só entre os que saíram:** se a Mel tivesse saído e a Caramelo estivesse ativa,
  "mel" devolveria só a Caramelo, sem aviso. Agora a ferramenta não devolve animal nenhum,
  informa `encontrados_entre_inativos` e põe a Caramelo em `outros_com_esse_trecho`; repetindo
  com `incluir_inativos`, o nome exato vence e vem a Mel.
- **Sugestão com dois animais do mesmo nome:** com `incluir_inativos`, "mimoza" achava a
  Mimosa ativa e a que saiu e devolvia as duas com `nome_considerado`, e o prompt mandava ao
  mesmo tempo seguir e perguntar. Agora `nome_considerado` só vem quando há um único animal.

Custo: quem digitar "mel" querendo a Caramelo recebe a Mel. Como o nome da vaca é a forma de
o produtor chamá-la, esse uso é improvável; o campo `outros_com_esse_trecho` fica no resultado
caso o modelo precise dele.

## Termos
- **Parâmetros mutuamente exclusivos:** dois modos que não podem ser usados juntos; a
  ferramenta recusa a combinação.
- **Nulo × zero:** zero é uma medição ("produziu 0 litros"); nulo é ausência de informação
  ("sem registro").
- **ISO (`AAAA-MM-DD`):** formato de data com o ano primeiro, sem ambiguidade entre dia e mês.
