# Especificação: Assistente de Rebanho

**Status:** rascunho para revisão do Marcos. Tudo aqui é proposta; ajuste com seu conhecimento de campo.

## 1. Problema
Quem gerencia uma fazenda leiteira precisa de respostas rápidas sobre o rebanho
("quem está produzindo menos?", "qual a produção total da semana?") e hoje depende
de planilhas ou de navegar em telas. Perguntar em linguagem natural é mais rápido.

## 2. Usuário
Produtor ou gestor de uma fazenda leiteira de pequeno e médio porte.

## 3. Escopo do MVP
- Perguntas em português sobre animais e produção de leite.
- Agente com **tool use**: o modelo escolhe e chama funções de consulta; o código as executa.
- API `POST /ask` que recebe a pergunta e devolve a resposta.
- Banco SQLite com **dados sintéticos** gerados por script com semente fixa (reproduzível).
- Conjunto de **evals** (25 perguntas) rodando automaticamente.

### Ferramentas planejadas (todas somente leitura)
| Função | O que faz |
|---|---|
| `resumo_rebanho()` | Totais: nº de animais, produção média diária |
| `listar_animais(status, lote)` | Lista animais com filtros |
| `producao_por_periodo(animal_id, dias)` | Produção de um animal ou do rebanho em N dias |
| `animais_abaixo_da_media(dias)` | Animais com produção abaixo da média do rebanho |

## 4. Modelo de dados (proposta inicial)
- `animais(id, brinco, nome, raca, data_nascimento, lote, status)`
- `producao_leite(id, animal_id, data, litros_manha, litros_tarde)`

> Marcos: revise isso com sua vivência. Que informações um produtor realmente consulta?
> (por exemplo: dias em lactação, ordens de parto, ordenhas por dia)

## 5. Fora do escopo
Autenticação, interface web, escrita no banco, RAG, previsões.

## 6. Critérios de sucesso
- O agente escolhe a ferramenta correta em pelo menos 90% das 25 perguntas das evals.
- Os números da resposta coincidem com o banco em pelo menos 90% dos casos.
- Nenhuma operação de escrita é possível.
- Custo e latência de cada requisição são registrados.

## 7. Restrições
- Dados sintéticos apenas (nenhum dado real de fazenda).
- Ferramentas somente leitura; o modelo nunca escreve SQL livre.
- Chaves de API só em variáveis de ambiente.
- Provedor de LLM trocável (ver ADR 0002).

## 8. Riscos
- **Alucinação numérica:** a resposta deve vir do resultado das ferramentas, não da "memória" do modelo.
- **Perguntas fora do escopo:** o agente deve recusar com educação.
- **Prompt injection:** textos vindos do banco (como nomes de animais) não podem ser tratados como instruções.

## 9. Perguntas em aberto
- Quais perguntas reais um produtor faria? (base para as evals)
- Quais colunas do modelo de dados são essenciais?
