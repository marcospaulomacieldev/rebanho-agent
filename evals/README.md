# Evals

Perguntas com o resultado esperado, usadas para **medir** o agente com o modelo de verdade.
O desenho, as checagens e as métricas estão no ADR 0007 (`docs/adr/0007-executor-de-evals.md`).

## Como rodar
Precisa da chave do provedor no `.env`. Cada pergunta custa de 1 a 3 chamadas ao modelo.

```
python -m evals.run --listar                      # mostra os casos, sem chamar o modelo
python -m evals.run --limite 3 --repeticoes 1     # amostra pequena
python -m evals.run                               # todos os casos, 3 vezes cada pergunta
python -m evals.run --casos mimosa-ontem,rebanho-hoje --repeticoes 2
```

Outras opções: `--intervalo` (segundos entre chamadas, padrão 4), `--max-chamadas` (teto da
rodada) e `--exigir 0.9` (sai com erro se uma métrica da spec ficar abaixo).

O resumo sai no terminal, e o relatório completo vai para `evals/resultados/` (fora do Git).
Uma taxa só vale para o modelo, o prompt e os casos daquela rodada, e o relatório registra os três.

## Casos (`casos/*.json`)
| Campo | Significado |
|---|---|
| `id` | Nome único do caso |
| `pergunta` ou `variantes` | Uma pergunta, ou várias formas de pedir a mesma coisa |
| `chamadas_esperadas` | Sequência de `{ferramenta, argumentos}`; lista vazia = não chamar nada |
| `chamadas_proibidas` | Ferramentas que não podem ser chamadas |
| `valor_esperado` | Campos do resultado da última chamada esperada (conferidos contra o banco pelo `pytest`) |
| `numeros_na_resposta` | Campos de `valor_esperado` que têm de aparecer no texto |
| `resposta_contem`, `resposta_nao_contem` | Trechos do texto, sem diferenciar acento nem maiúsculas |
| `sem_litros_na_resposta` | O texto não pode ter número de litros (recusas, "sem registro") |

O formato antigo (`ferramenta_esperada` e `argumentos_esperados`) continua valendo como uma
sequência de uma chamada.

## Na CI
O executor não roda na CI (precisa de chave). Lá, o `pytest` valida os arquivos de caso e
testa o executor com um cliente falso.
