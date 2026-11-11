# ADR 0002: Provedor de LLM

**Status:** proposta (aguardando decisão do Marcos)

## Contexto
O projeto precisa de um modelo com suporte a tool use. Há opções gratuitas com limites
de uso (como o plano gratuito da API do Gemini) e opções pagas (como a API do Claude,
cobrada à parte da assinatura Pro). Planos gratuitos mudam com frequência, e no plano
gratuito do Gemini os dados enviados podem ser usados para melhorar produtos do Google.

## Decisão proposta
- Desenvolver e iterar usando o plano gratuito de um provedor, por trás de uma
  interface própria (`app/llm/client.py`).
- Usar **apenas dados sintéticos**, o que elimina o risco de privacidade do plano gratuito.
- Rodar as evals também em um segundo modelo e publicar a comparação no README.

## Alternativas
- Usar só um provedor pago: simples, mas custa desde o primeiro dia.
- Modelo local: sem custo de API, mas depende do hardware disponível.

## Consequências
- Trocar de provedor deve exigir mudança em um único arquivo.
- A comparação entre modelos vira um resultado concreto e documentado.
- Limites do plano gratuito podem exigir tratamento de erros 429 (excesso de requisições).
