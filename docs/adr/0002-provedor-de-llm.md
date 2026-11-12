# ADR 0002: Provedor de LLM

**Status:** aceita (2026-11-12)

## Contexto
O projeto precisa de um modelo com suporte a tool use. Há opções gratuitas com limites
de uso (como o plano gratuito da API do Gemini) e opções pagas (como a API do Claude,
cobrada à parte da assinatura Pro). Planos gratuitos mudam com frequência, e no plano
gratuito do Gemini os dados enviados podem ser usados para melhorar produtos do Google.

## Decisão
- O provedor de desenvolvimento é o **plano gratuito da API do Gemini** (Google AI Studio),
  com um modelo da família Flash. O modelo exato fica em configuração, não no código.
- Todo acesso ao modelo passa por uma interface própria (`app/llm/client.py`); o provedor
  é escolhido pela variável `LLM_PROVIDER`.
- O projeto usa **apenas dados sintéticos**, o que elimina o risco de privacidade do plano gratuito.
- Ao final, as evals também serão rodadas em um modelo do Claude, e a comparação será publicada no README.

## Alternativas
- Usar só um provedor pago: simples, mas custa desde o primeiro dia.
- Modelo local: sem custo de API, mas depende do hardware disponível.

## Consequências
- Trocar de provedor deve exigir mudança em um único arquivo.
- A comparação entre modelos nas mesmas evals vira um resultado concreto e documentado.
- Limites do plano gratuito podem exigir tratamento de erros 429 (excesso de requisições), com espera e nova tentativa.
