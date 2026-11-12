---
name: nova-ferramenta
description: Procedimento para criar uma nova ferramenta (tool) do agente, de ponta a ponta. Use quando for implementar qualquer função listada na tabela de ferramentas da docs/spec.md, como producao_por_periodo ou proximas_vacinacoes.
---

# Criar uma nova ferramenta do agente

Argumento: o nome da ferramenta, como aparece na tabela da seção 3 de `docs/spec.md`.

## Antes de codar
1. Leia a linha da ferramenta na tabela da `docs/spec.md` e as tabelas do banco que ela usa (seção 4).
2. Apresente um plano curto: assinatura da função, consulta ao banco, formato do retorno, casos de borda. **Espere aprovação.**

## Implementação (nesta ordem)
1. **Repositório** (`app/db/`): função de consulta com SQL parametrizado (`?`), somente `SELECT`. Nenhum SQL fora de `app/db/`.
2. **Ferramenta** (`app/tools/<modulo>.py`): função com type hints que chama o repositório e devolve dados simples (dict/list), com unidades explícitas nos nomes dos campos (ex.: `litros_total`, `peso_medio_kg`).
3. **Registro**: adicione a ferramenta ao registro de ferramentas com nome, descrição para o modelo e esquema dos parâmetros. A descrição deve dizer **quando usar** e **quando não usar**, para o modelo não confundir ferramentas parecidas.
4. **Testes** (`tests/`): caso normal, caso sem dados, parâmetro inválido. Use um banco de teste pequeno e determinístico.
5. **Eval** (`evals/`): ao menos um caso com a pergunta em português, a ferramenta esperada, os argumentos esperados e o valor correto.

## Verificação
- Rode `pytest` e `ruff check .`. Só termine com ambos passando.
- Resuma em 3 a 5 linhas o que foi feito e por quê, explicando qualquer termo técnico novo.
- Sugira a mensagem de commit no formato `feat(<modulo>): ...`.

## Regras que não podem ser quebradas
- Somente leitura. Nada de `INSERT`, `UPDATE`, `DELETE` ou SQL montado com texto vindo do modelo.
- Respostas de recomendação (vacinar, adubar) vêm só de protocolo ou plano cadastrado; sem dados, a ferramenta retorna vazio e o agente diz que não há registro.
