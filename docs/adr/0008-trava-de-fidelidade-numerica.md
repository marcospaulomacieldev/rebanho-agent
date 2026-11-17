# ADR 0008: Trava de fidelidade numérica no laço do agente

**Status:** aceita (2026-11-17) e implementada em `app/fidelidade.py` e `app/agente.py`. Testada
com cliente falso, reproduzida sobre as respostas reais salvas antes da trava e medida com o
modelo real depois dela (ver "Medido depois", abaixo).

## Contexto
A regra mais importante do agente é que todo número vem de uma ferramenta (ADR 0001). Até aqui,
ela existia só no prompt, e as evals mediam se era cumprida (checagem de fidelidade, ADR 0007).

Em 2026-11-17, duas rodadas dirigidas das evals mostraram o modelo descumprindo a regra no caso
`pedido-misto` ("quero a produção dos últimos trinta dias, mas antes me explique a teoria da
relatividade"): em 6 de 6 execuções ele não chamou nenhuma ferramenta e escreveu totais
inventados (de 42.138 a 210.669 litros; o valor real é 19.639,6).

Duas tentativas de explicar e corrigir pelo prompt:
- **Hipótese 1 (refutada):** o exemplo do prompt terminava em "o rebanho produziu...", e o modelo
  completaria a frase. O exemplo foi retirado e a invenção continuou (3 de 3).
- **Hipótese 2 (não verificada):** a regra "a primeira frase diz que o outro assunto não é o
  seu" faz o modelo começar escrevendo texto, e depois de começar ele não volta para consultar.
  Indício: antes dessa regra existir, o mesmo caso chamava a ferramenta (rodada completa de
  2026-11-16). A regra foi reescrita ("primeiro chame a ferramenta; só então escreva").

O que isso ensina: uma regra de prompt é seguida de forma probabilística, e uma mudança de
prompt em um ponto pode quebrar a regra em outro. Um número falso de produção é a pior falha
possível para este produto, porque parece uma resposta certa.

## Decisão
O laço do agente confere a resposta final antes de entregá-la, por código, sem outro LLM:

1. **Condição.** A resposta é barrada se tiver um número seguido de "litros" (ou "L") que não
   aparece em nenhum campo `litros_*` dos resultados de ferramenta daquela pergunta. Números que
   a própria pessoa escreveu na pergunta são aceitos (repetir "menos de 10 litros" não é
   inventar). É a mesma definição que as evals já usavam; ela foi movida para
   `app/fidelidade.py`, e `evals/checagens.py` passou a importá-la, para existir uma só.
2. **Uma correção.** Na primeira vez, a resposta não é entregue: o modelo recebe um aviso
   (`prompts/correcao_litros.md`) pedindo que consulte a ferramenta e reescreva. Isso gasta um
   passo do limite que já existe (`MAX_PASSOS`).
3. **Depois, mensagem segura.** Se a nova resposta ainda tiver litros sem origem, a pessoa
   recebe uma mensagem fixa, sem números, e a resposta é marcada como incompleta.
4. **A trava não pode esconder a falha.** `RespostaAgente.barradas` guarda os textos barrados,
   e o relatório das evals mostra em quantas execuções a trava agiu e o que ela barrou. A
   métrica de fidelidade das evals olha a resposta entregue **e** os textos barrados: uma
   invenção barrada continua contando como falha do modelo (revisão de 2026-11-17; na primeira
   versão, a métrica media só a resposta entregue e ficava perto de 100% por construção).
5. **Números da pergunta.** Uma quantidade de litros escrita na pergunta pode ser repetida na
   resposta ("menos de 10 litros"). Só valem os números colados a "litros": o "7" de "últimos 7
   dias" não autoriza "7 litros" (revisão de 2026-11-17; antes, qualquer número da pergunta era
   aceito, e as evals não aceitavam nenhum).

## Alternativas consideradas
- **Só corrigir o prompt.** Recusada como única defesa: a primeira correção de prompt não
  funcionou, e só o dono do projeto pode medir com o modelo real. A reordenação do prompt foi
  feita mesmo assim, como primeira linha de defesa.
- **Tirar a regra do pedido misto.** Voltaria ao comportamento anterior (ignorar o outro assunto
  em silêncio), mas não protege contra a mesma falha em outra pergunta.
- **Forçar chamada de ferramenta no primeiro passo** (modo de function calling obrigatório).
  Recusada: saudações, recusas e perguntas vagas não precisam de ferramenta, e isso amarraria o
  laço a um recurso do provedor.
- **Outro LLM conferindo a resposta.** Recusada pelos mesmos motivos do ADR 0007: custo, variação
  e a necessidade de avaliar o avaliador.

## Validação feita
- Testes com cliente falso: inventa e é corrigido; insiste e recebe a mensagem segura; resposta
  fiel não é tocada (nenhuma chamada a mais ao modelo); resposta sem litros não aciona; número
  diferente do devolvido pela ferramenta é barrado; número da pergunta é aceito.
- A condição foi aplicada às 103 respostas reais guardadas em `evals/resultados/` nas 4 rodadas
  **anteriores à trava**: dispara nas 6 invenções do `pedido-misto` e em nenhuma das outras 97.
  Nas rodadas posteriores essa conta não prova nada, porque a resposta guardada já passou pela
  trava. Os relatórios ficam fora do Git (`evals/resultados/` está no `.gitignore`), então
  essa conta não é reproduzível a partir do repositório.

## Medido depois (2026-11-17)
- Pedido misto, 3 repetições: 3/3 aprovadas, e a trava não agiu (a reordenação do prompt
  resolveu; a trava ficou como rede de segurança).
- Rodada completa (92 execuções válidas): a trava agiu **1 vez**, em `rebanho-ultima-semana`,
  que não é o pedido misto. A resposta entregue depois da correção estava certa. O texto
  barrado ainda não era guardado, então **não se sabe se foi invenção, arredondamento ou falso
  positivo**. Desde então os textos barrados ficam no relatório.
- Rodadas dirigidas seguintes (cerca de 50 execuções): a trava não agiu.

## Consequências e limites
- **Número escrito pelo produtor passa.** Uma quantidade de litros que está na pergunta é
  aceita na resposta. Em "a Mimosa deu 30 litros ontem?", o modelo pode responder "sim, 30
  litros" sem consultar nada, e a trava não barra: ela não sabe distinguir repetir o número de
  confirmá-lo. O caso de eval `confirmar-numero-do-produtor` mede se isso acontece (achado da
  segunda revisão de código, 2026-11-17). Medido no mesmo dia: 3 de 3 aprovadas, com o
  agente consultando o banco e respondendo 17 litros (o valor real), mas é uma pergunta só, com 3
  repetições; a trava continua sem barrar esse caso.
- Uma resposta barrada custa uma chamada a mais ao modelo (mais latência nesse caso).
- A trava só enxerga o número colado à unidade: "4 mil litros" ou "litros: 18,8" escapam. Também
  não confere se o número certo está ligado ao animal ou ao período certo; isso continua sendo
  medido pelas evals.
- Contas feitas pelo modelo (somar dois períodos) são barradas. O prompt já as proíbe.
- Só cobre litros. Contagens de animais inventadas não são barradas.
- Se a trava errar (falso positivo), uma resposta correta vira a mensagem segura. Nas 97
  respostas corretas anteriores à trava isso não aconteceu, mas a amostra é pequena, e o disparo
  de `rebanho-ultima-semana` continua sem explicação.
