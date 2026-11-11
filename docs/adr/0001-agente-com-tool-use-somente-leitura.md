# ADR 0001: Agente com tool use e ferramentas somente leitura

**Status:** aceita

## Contexto
O sistema precisa responder perguntas sobre dados do rebanho. O modelo de linguagem
(LLM) pode inventar números se responder sozinho, e dar a ele acesso livre ao banco
traz risco de segurança.

## Decisão
O modelo recebe uma lista de funções Python bem definidas (tool use / function calling)
e escolhe qual chamar. Nosso código executa a função e devolve o resultado; o modelo
só redige a resposta. Todas as funções são **somente leitura**.

## Alternativas consideradas
- **Text-to-SQL** (o modelo escreve a consulta SQL): mais flexível, mas difícil de
  validar, arriscado (consultas inesperadas ou destrutivas) e difícil de testar.
- **Contexto completo** (colar todos os dados no prompt): não escala e aumenta o custo.

## Consequências
- Cada ferramenta pode ser testada isoladamente com testes normais.
- O que o agente consegue responder é limitado pelas ferramentas que existirem.
- A qualidade passa a ser medida por evals: escolheu a ferramenta certa? Os números batem?
