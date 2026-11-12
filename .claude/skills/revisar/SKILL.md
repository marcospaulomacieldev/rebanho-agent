---
name: revisar
description: Revisão independente das mudanças pendentes antes de um commit, usando o subagente revisor. Use quando o usuário pedir para revisar, ou ao final de uma tarefa antes de sugerir o commit.
disable-model-invocation: true
---

# Revisar antes do commit

1. Delegue a revisão ao subagente `revisor`, pedindo que analise as mudanças pendentes (`git diff` e `git diff --staged`).
2. Mostre o veredito e os achados do revisor sem suavizá-los.
3. Para cada achado, proponha a correção, mas **não aplique nada sem aprovação**.
4. Se o veredito for `APROVADO`, sugira a mensagem de commit no padrão do `CLAUDE.md`. Não faça o commit: o dono do projeto faz.
