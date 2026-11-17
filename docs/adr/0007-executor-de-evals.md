# ADR 0007: Executor de evals (`python -m evals.run`)

**Status:** aceita (2026-11-16) e implementada em `evals/`. Só uma amostra pequena foi rodada
com o modelo real (3 casos, 14 execuções, registrada no devlog); os critérios de 90% da spec
ainda não foram medidos.

## Contexto
A spec (seção 6) pede três medidas: o agente escolhe a ferramenta certa, os números da resposta
coincidem com o banco, e perguntas equivalentes chegam à mesma ferramenta e aos mesmos
argumentos, cada uma em pelo menos 90% dos casos. Os testes manuais mostraram que o modelo segue
o prompt de forma probabilística: uma execução por pergunta não mede nada
(`docs/estado-do-agente.md`). Hoje os casos em `evals/casos/` são só dados conferidos contra o
banco; falta quem rode o agente de verdade e calcule as taxas.

Restrições: plano gratuito do Gemini (limite de requisições, erro 429), chave só no ambiente do
dono do projeto, e a CI roda sem chave e sem rede.

## Decisão

### 1. Formato dos casos (JSON, em `evals/casos/*.json`)
O formato atual continua válido e ganha campos opcionais. Um caso:

```json
{
  "id": "mimosa-dia-especifico",
  "semente": 42,
  "variantes": [
    "produção mimosa 21/10",
    "quanto a mimosa produziu no dia 21 de outubro",
    "leite da mimoza dia 21/10?"
  ],
  "chamadas_esperadas": [
    {"ferramenta": "listar_animais", "argumentos": {"nome": "mimosa"}},
    {"ferramenta": "producao_por_periodo",
     "argumentos": {"animal_id": 28, "data_inicio": "2026-10-21", "data_fim": "2026-10-21"}}
  ],
  "valor_esperado": {"litros_manha_total": 9.8, "litros_tarde_total": 9.0, "litros_total": 18.8},
  "numeros_na_resposta": ["litros_manha_total", "litros_tarde_total", "litros_total"]
}
```

| Campo | Significado |
|---|---|
| `pergunta` ou `variantes` | Uma pergunta, ou várias formas de pedir a mesma coisa. Todas as variantes têm o mesmo resultado esperado, definido uma vez só. |
| `chamadas_esperadas` | Sequência de chamadas (`ferramenta`, `argumentos`). Lista vazia = o agente não deve chamar nada. O formato antigo (`ferramenta_esperada` + `argumentos_esperados`) equivale a uma sequência de uma chamada. |
| `chamadas_proibidas` | Nomes de ferramentas que não podem ser chamadas (por exemplo, `producao_por_periodo` antes de o produtor dizer qual animal). |
| `valor_esperado` | Campos do resultado da **última** chamada esperada. Um teste do `pytest` confere esses valores contra o banco, como já acontece hoje. |
| `numeros_na_resposta` | Quais campos de `valor_esperado` têm de aparecer no texto da resposta. |
| `resposta_contem` / `resposta_nao_contem` | Trechos que devem (ou não) aparecer no texto, comparados sem acento e sem diferenciar maiúsculas. Um item pode ser uma lista de alternativas (basta uma). |
| `sem_litros_na_resposta` | Verdadeiro para recusas e "sem registro": o texto não pode ter número seguido de "litro(s)" ou "L". |

Três tipos de caso saem da combinação desses campos, sem um campo "tipo":
- **resposta com dado:** `chamadas_esperadas` + `valor_esperado` + `numeros_na_resposta`;
- **recusa ou limite** ("vai chover?", "quais vacas produzem menos?"): `chamadas_esperadas: []`,
  `sem_litros_na_resposta: true`;
- **pergunta de volta** (nome ambíguo, erro de digitação): `chamadas_esperadas` só com
  `listar_animais`, `chamadas_proibidas: ["producao_por_periodo"]`,
  `resposta_contem: ["Mel", "Caramelo", "?"]`.

### 2. Como cada coisa é checada (tudo determinístico, sem outro LLM)
- **Ferramentas:** os nomes das chamadas esperadas têm de aparecer, na ordem, entre as chamadas
  que o agente fez (*subsequência*: pode haver chamadas a mais no meio, como a segunda busca
  com `incluir_inativos`). Chamadas a mais são contadas no relatório, mas só reprovam se
  estiverem em `chamadas_proibidas`.
- **Argumentos:** para cada chamada esperada, a chamada correspondente do agente passa se:
  (a) os argumentos forem iguais depois de normalizar (nulo e texto vazio = omitido; `7.0` = `7`;
  `nome` sem acento e sem maiúsculas), ou (b) o **resultado** que ela devolveu for igual ao da
  chamada esperada executada no mesmo banco (*equivalência por resultado*). O item (b) existe
  porque `dias = 1` e `data_inicio = data_fim = último dia` são o mesmo pedido. O relatório
  mostra as duas taxas: "argumentos idênticos" e "argumentos equivalentes".
- **Números no texto:** o executor extrai os números do texto no formato brasileiro
  (`4.479,1`, `18,8`, `639,87`) e também no formato com ponto decimal (`4479.1`), e converte
  para decimal exato. Um campo de `numeros_na_resposta` passa se o valor esperado aparecer
  **exatamente** (`18,80` conta como `18,8`; `18,7` e "cerca de 19" não contam).
- **Fidelidade numérica** (alucinação): todo número seguido de "litro(s)" ou "L" no texto tem de
  existir em algum resultado de ferramenta daquela execução. É checada em todos os casos.
- **Texto:** `resposta_contem`, `resposta_nao_contem` e `sem_litros_na_resposta`.

Uma execução **passa** se passar em todos os critérios que o caso define.

### 3. Repetições
Cada pergunta (cada variante) roda `--repeticoes` vezes (padrão: 3). O banco é gerado da
semente do caso em um arquivo temporário e aberto em modo somente leitura, como em produção.
O agente é o mesmo código (`app.agente.responder`), com o prompt real.

### 4. Erro 429 e limite de uso
Um invólucro do cliente (`ClienteComEspera`, dentro de `evals/`, que cumpre a interface
`ClienteLLM`) faz três coisas:
- **Ritmo:** espera `--intervalo` segundos entre chamadas ao modelo (padrão: 4 s).
- **Nova tentativa:** em erro 429 (limite de requisições) ou 503 (sobrecarga), espera e tenta
  de novo, com espera crescente (15, 30, 60, 120 s), até 4 vezes. Para isso, `ErroLLM` ganha o
  atributo `codigo` (hoje o código só existe dentro do texto da mensagem).
- **Teto:** `--max-chamadas` limita o total de chamadas ao modelo na rodada.

Só contam como falha de infraestrutura: rede fora do ar, chave recusada (401, 403), limite de
uso (429) e falha do servidor do provedor (5xx). Resposta vazia ou bloqueada e erro 400 são
comportamento do modelo e contam como **reprovação**.

Se as tentativas se esgotarem, a execução é marcada como **não executada** (falha de
infraestrutura). Ela **não conta como erro nem como acerto do modelo** e fica fora dos
denominadores, listada à parte. Três execuções seguidas não executadas encerram a rodada (sinal
de limite diário), e o relatório parcial é gravado mesmo assim.

Para rodar pouco: `--casos id1,id2`, `--limite N` e `--repeticoes 1`.

### 5. Métricas
Sempre como **k/n** (acertos sobre execuções válidas) e porcentagem; com menos de 30 execuções o
relatório avisa que a amostra é pequena.

| Métrica | Critério da spec |
|---|---|
| Ferramenta correta | "escolhe a ferramenta correta" (90%) |
| Argumentos equivalentes (e idênticos, à parte) | parte do critério de perguntas equivalentes |
| Números corretos na resposta | "os números coincidem com o banco" (90%) |
| Fidelidade numérica | risco de alucinação numérica |
| Comportamento (recusa, pergunta de volta) | riscos da seção 8 |
| Execução aprovada (tudo junto) | visão geral |
| Consistência entre variantes: casos em que **todas** as variantes passaram em todas as repetições | "perguntas equivalentes" (90%) |

Também: latência por pergunta (mediana e percentil 90), passos por pergunta, chamadas ao modelo,
novas tentativas e execuções não executadas. **Custo em tokens fica de fora**: o cliente ainda
não expõe a contagem de tokens.

### 6. Relatório
- **Terminal:** resumo das métricas, uma linha por caso (`k/n`) e a lista das falhas com a
  pergunta, o que era esperado e o que o agente fez.
- **JSON** em `evals/resultados/<data-hora>-<modelo>.json` (pasta fora do Git): metadados
  (modelo, provedor, repetições, commit, *hash* do prompt, versão do formato), resumo, e cada
  execução com pergunta, chamadas feitas, texto da resposta, resultado de cada checagem e
  latência. A chave da API nunca entra.
- **Código de saída:** 0 se a rodada terminou; 1 se nada foi medido, se a rodada foi
  interrompida (limite de uso, teto de chamadas ou Ctrl+C; o relatório parcial é gravado) ou
  se, com `--exigir 0.9`, alguma métrica da spec ficou abaixo.

### 8. Limites conhecidos das checagens
- A fidelidade numérica só vê número colado à unidade: "4 mil litros" e "litros: 18,8" escapam.
- Números que fazem parte de datas (`17/11/2026`) são ignorados na busca pelos valores esperados.
- Um caso só entra na consistência entre variantes se todas as variantes foram executadas.
- Os casos de formato antigo checam a chamada e, quando definido, o número no texto; não
  avaliam a redação.

### 7. Onde roda
O executor **não roda na CI** (precisa de chave e é probabilístico). Na CI, o `pytest` continua
validando os arquivos de caso (formato e valores contra o banco) e testa o executor inteiro com
um cliente falso, sem rede.

## Alternativas
| Decisão | Alternativa | Por que não |
|---|---|---|
| Checagens determinísticas | Outro LLM como juiz da resposta | Custa requisições do plano gratuito, varia entre execuções e precisa ser avaliado também. Pode entrar depois, só para tom e clareza. |
| Executor próprio (poucas centenas de linhas) | Framework pronto (promptfoo, DeepEval) | Dependência nova, e os pontos difíceis daqui (números em português, equivalência por resultado, ritmo do plano gratuito) teriam de ser escritos de qualquer jeito. Custo: manter o código. |
| Módulo separado (`evals.run`) | Rodar as evals dentro do `pytest` | Teste tem de dar sempre o mesmo resultado e rodar sem chave; eval é uma medição com taxa. |
| Argumentos idênticos **ou** equivalentes por resultado | Só igualdade exata | Reprovaria respostas certas (`dias = 1` × data do dia). O risco de duas chamadas diferentes darem o mesmo resultado por acaso é pequeno, e a taxa de idênticos fica visível. |
| Ordem por subsequência | Sequência exata | A segunda busca com inativos, prevista no prompt, reprovaria. |
| `variantes` dentro do caso | Um caso por variante, ligados por `grupo` | Repetiria o resultado esperado em cada um, com risco de divergirem. |
| JSON | YAML | Dependência nova; os casos atuais já são JSON. |
| Falha de infraestrutura fora do denominador | Contar como erro | Mediria o limite do plano, e não o agente. |

## Consequências
- As taxas passam a existir, mas só valem para o modelo, o prompt e os casos daquela rodada; o
  relatório guarda os três.
- Uma rodada completa é lenta no plano gratuito: cada pergunta custa de 1 a 3 chamadas ao modelo,
  com intervalo entre elas.
- A equivalência por resultado e a subsequência tornam a aprovação um pouco mais permissiva; por
  isso o relatório mostra também argumentos idênticos e chamadas a mais.
- Checagem de texto por trechos é frágil a sinônimos; os casos devem usar trechos curtos e
  alternativas.
- `ErroLLM` ganha o atributo `codigo`, e o pacote `evals` passa a ser importável nos testes
  (ajuste no `pyproject.toml`).
- Conversa com histórico (casos com mais de um turno) fica fora deste formato.

## Termos
- **Eval:** pergunta com resultado esperado, usada para medir o agente.
- **Subsequência:** os itens esperados aparecem na ordem, mas pode haver outros entre eles.
- **Equivalência por resultado:** duas chamadas contam como iguais se devolvem o mesmo resultado.
- **Erro 429:** resposta do provedor quando o limite de requisições foi atingido.
- **Mediana e percentil 90:** o valor do meio e o valor abaixo do qual ficam 90% das medidas.
- **Hash:** código curto calculado do conteúdo de um arquivo; muda se o arquivo mudar.
