# ADR 0004: Modelo de dados, exclusão lógica e dados para análise futura

**Status:** aceita (2026-11-14)

## Contexto
O MVP responde perguntas sobre animais e produção de leite, mas o dono do projeto já
coleta, na fazenda, dados de produção, horário de ordenha, chuva e temperatura, e pretende
analisar a produção em função desses fatores no futuro, com dados reais. A decisão é o
quanto do modelo preparar agora, sem inflar o escopo do MVP.

## Decisão
- **Quatro tabelas:** `animais`, `producao_leite`, `condicoes_dia` (clima e horários, uma
  linha por dia) e `partos` (um evento por parto). As duas últimas não são usadas por
  nenhuma ferramenta do MVP.
- **Listas fechadas** (`CHECK`) para `status`, `lote`, `raca`, `sexo` e `motivo_saida`,
  com identificadores sem acento nem barra. As combinações válidas de status e lote e a
  regra "só `corte` pode ter sexo `M`" também são `CHECK`, pois envolvem só a tabela
  `animais`. Regras que cruzam tabelas (datas de saída, parto de vaca em lactação) ficam
  no gerador e nos testes.
- **Exclusão lógica:** animal nunca é apagado; recebe `ativo = 0`, `data_saida` e
  `motivo_saida`. O histórico de produção continua válido.
- **Tabelas `STRICT`:** o SQLite recusa valor de tipo errado. Sem isso, um `CHECK` como
  "litros >= 0" deixaria passar o texto "abc", pois o SQLite considera qualquer texto maior
  que qualquer número. Exige SQLite 3.37 ou mais novo.
- **Nome único só entre animais ativos**, por índice único parcial (`WHERE ativo = 1`), com
  nome sem espaços nas pontas. O `COLLATE NOCASE` do SQLite só ignora maiúsculas em letras
  ASCII, então nomes que só diferem por acento ("Áurea" e "áurea") são aceitos pelo banco;
  o gerador evita esses nomes, e a busca por nome nas ferramentas ignora acentos.
- **Sem `brinco`:** a fazenda ainda não usa; `id` identifica no banco e `nome`, para o
  produtor.
- **Alimentação não é modelada:** com poucos lotes, a dieta é inferida pelo `lote`.
- Clima fica em tabela própria por dia, porque é dado do dia e não do animal; repeti-lo
  por animal permitiria valores diferentes para o mesmo dia.
- Dado ausente de produção (só esperado em dados reais) será estimado pela média dos dois
  últimos registros do mesmo turno do animal. A marcação do valor como estimado fica
  pendente de decisão antes de qualquer importação real.

## Alternativas
- **Só duas tabelas** (animais e produção): mais simples, mas obriga a refazer o modelo
  quando a análise futura começar. Descartada por escolha do dono do projeto.
- **Tabelas de apoio para status e lote** em vez de `CHECK`: mais fáceis de estender, porém
  mais complexas. Como os dados são sintéticos e regenerados por script, recriar a tabela
  ao mudar uma lista tem custo quase zero.
- **Manter `brinco`:** descartado por ora, pois não existe na operação.
- **Apagar o animal ao sair:** perde o histórico e quebra a chave estrangeira.

## Consequências
- O gerador de dados tem mais trabalho, sem ganho imediato para as ferramentas.
- Qualquer efeito de clima ou lactação nos dados sintéticos é uma suposição do gerador,
  e não um achado: um modelo treinado neles só redescobriria essa suposição.
- As ferramentas tratam animais inativos conforme a seção 3 da spec.
- Estado atual de `lote` e `status` apenas; sem histórico de mudanças.
- Usar dados reais exige rever o ADR 0002, pois o plano gratuito do Gemini pode usar os
  dados enviados para melhorar produtos do Google.

## Termos
- **`CHECK`:** regra que o próprio banco aplica a cada linha gravada.
- **Índice único parcial:** regra de unicidade que vale só para as linhas que atendem a uma
  condição (aqui, `ativo = 1`).
- **Exclusão lógica:** marcar o registro como inativo em vez de apagá-lo.
- **Tabela `STRICT`:** tabela em que o SQLite recusa valor de tipo errado.
