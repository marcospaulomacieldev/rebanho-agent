# ADR 0006: O MVP não usa RAG, embeddings nem banco vetorial

**Status:** aceita (2026-11-15)

## Contexto
O agente responde perguntas sobre o rebanho, como "qual a produção total da semana?". Essas
perguntas pedem **números exatos** (litros, datas, contagens) guardados em tabelas. Ao desenhar
como o modelo de linguagem (LLM) "conhece" o sistema, havia a opção de usar RAG, embeddings e um
banco vetorial, técnicas comuns em assistentes com LLM.

O modelo conhece o sistema por três caminhos, nenhum deles uma busca por similaridade:
1. o **prompt de sistema** (`prompts/sistema.md`): papel, tom e regras;
2. as **definições das ferramentas** (nome, descrição e parâmetros, em `app/tools/registro.py`),
   que ele lê para decidir qual chamar;
3. a **conversa**, incluindo os resultados das ferramentas que ele mesmo pediu.

Ele não recebe a base de dados. Só vê o que as ferramentas devolvem em cada pergunta.

## Decisão
Usar **tool use** com consultas exatas, somente leitura (ADR 0001), e **não** usar RAG,
embeddings nem banco vetorial no MVP. Isso já consta como fora do escopo na spec (seção 5).

## Alternativas consideradas
- **RAG com embeddings e banco vetorial:** recupera os trechos de texto mais parecidos com a
  pergunta. É a técnica certa para achar *texto* num acervo grande, mas aqui a resposta é um
  cálculo (soma, média, contagem) sobre dados estruturados. Uma busca por semelhança pode
  trazer um valor vizinho e errado, e não há como somar litros "por parecido".
- **Colocar todos os dados no prompt:** não escala e aumenta o custo (ADR 0001).
- **O modelo escrever SQL (text-to-SQL):** mais flexível, porém difícil de validar e de
  proteger contra consultas destrutivas (ADR 0001).

## Quando reconsiderar
- **Recomendações de manejo, sanidade ou vacinação a partir de protocolos e manuais em texto.**
  A skill `nova-ferramenta` (`.claude/skills/nova-ferramenta/SKILL.md`) define que respostas de
  recomendação (vacinar, adubar) vêm só de protocolo ou plano cadastrado. Quando esses
  protocolos forem documentos de texto longos, esse é o caso clássico de RAG. Nesse caso, o RAG
  entraria **ao lado** das ferramentas, e nunca no lugar delas para números.
- **Muitos documentos** que não caibam no prompt.

## Casos que parecem pedir RAG, mas não pedem
- **Nomes de animais com erro de digitação:** embeddings funcionariam, mas são exagero. Um
  casamento aproximado de letras (por exemplo, sugerir "Mimosa" para "mimoza") resolve, sem modelo
  de embeddings nem banco novo.
- **Entender o jeito de falar do produtor** ("tirada", "gado", "quanto deu"): o próprio LLM faz
  isso, com as descrições das ferramentas e o vocabulário do prompt, e a qualidade é medida pelas
  evals.

## Consequências
- Cada resposta numérica vem de uma consulta exata que pode ser testada e comparada com o banco.
- Menos peças para manter e menos custo: não há modelo de embeddings, índice vetorial nem
  etapa de ingestão de documentos.
- O agente só responde o que as ferramentas cobrem. Perguntas sobre documentos em texto ficam
  fora do MVP.
- Se o RAG entrar depois, será por uma ferramenta própria de busca em documentos, com um novo ADR.

## Termos
- **Tool use (chamada de ferramentas):** o modelo escolhe uma função pelo nome e pelos parâmetros;
  nosso código a executa e devolve o resultado.
- **RAG (geração aumentada por busca):** buscar antes os textos mais relevantes de um acervo e dá-los
  ao modelo para ele responder com base neles.
- **Embedding:** lista de números (vetor) que representa o sentido de um texto; textos parecidos
  têm vetores próximos.
- **Banco vetorial:** banco que guarda embeddings e encontra rápido os mais próximos de uma pergunta.
