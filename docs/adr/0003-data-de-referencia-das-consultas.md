# ADR 0003: Data de referência das consultas

**Status:** aceita (2026-11-14)

## Contexto
As ferramentas recebem `dias`, que significa "os últimos N dias". Se "hoje" for a data do
relógio do computador (`date.today()`), as respostas mudam a cada dia, mesmo com o gerador
de dados usando semente fixa. Isso quebraria as evals, que comparam números do banco com
a resposta do agente.

## Decisão
- A data de referência ("hoje") é a **maior `data` de `producao_leite`**.
- A janela de `dias` termina nessa data, inclusive: de `ref - dias + 1` até `ref`.
- As funções de consulta em `app/db/` aceitam uma `data_referencia` opcional, usada em
  testes. Ela **não aparece** no esquema das ferramentas mostrado ao modelo: o modelo não
  escolhe a data.

## Alternativas
- **`date.today()`:** simples, mas as respostas esperadas das evals envelhecem a cada dia.
- **Data de referência fixa em configuração:** estável, mas precisa ser atualizada à mão
  quando os dados forem regenerados ou, no futuro, importados.
- **Parâmetro da ferramenta, escolhido pelo modelo:** abre espaço para o modelo errar ou
  inventar a data.

## Consequências
- Os testes e as evals dão o mesmo resultado em qualquer dia.
- Com dados reais, "hoje" será a última ordenha registrada, o que é razoável, mas pode
  diferir do dia atual se a coleta atrasar. Isso deve ser avisado na resposta do agente.
- Banco sem nenhuma linha de produção não tem data de referência; as ferramentas devem
  tratar esse caso com um resultado vazio e claro.
