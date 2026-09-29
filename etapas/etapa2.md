# Etapa 2 — Coleta de dados

## Objetivo
Scripts que coletam dados de várias fontes e salvam no banco da Etapa 1, de forma incremental e resiliente.

## Fontes (verificar documentação, limites e necessidade de chave ANTES de implementar)
| Dado | Fonte principal | Alternativa |
|------|-----------------|-------------|
| Cotações diárias | brapi.dev | yfinance (tickers com `.SA`) |
| Macro (Selic, IPCA, câmbio) | API SGS do Banco Central | — |
| Documentos e fatos relevantes | Portal de dados abertos da CVM | Sites de RI (só se permitido) |
| Notícias | Feeds RSS de portais financeiros | NewsAPI ou similar |

Apresente uma tabela com o que descobriu de cada fonte (limites, chave, formato, atraso dos dados) antes de codar.

## Tarefas
1. Um módulo por fonte em `src/coleta/`, todos com a mesma interface (ex: `coletar(desde: date) -> int` retornando registros novos).
2. Cliente HTTP comum com timeout, retry com backoff e respeito a rate limit.
3. Coleta incremental: buscar só a partir do último dado salvo de cada ativo/série.
4. Preencher `disponivel_em` corretamente em cada fonte:
   - Cotação de fechamento: disponível no fim do pregão daquele dia.
   - Macro: data de divulgação, não a data de referência (IPCA de março sai em abril).
   - Notícias: horário de publicação.
   - Documentos CVM: data/hora de entrega/divulgação.
5. Associação notícia → ativos (começar simples: ticker e nome da empresa no texto; documentar limitações).
6. Deduplicação de notícias por hash/URL.
7. Registrar cada execução em `execucoes_coleta`.
8. `scripts/coletar.py` com opções: todas as fontes ou uma específica, e data inicial para carga histórica.
9. Testes com respostas de API mockadas (incluindo erro, timeout e resposta vazia).

## Cuidados
- Falha em uma fonte não pode interromper as outras.
- Nunca sobrescrever silenciosamente dados já salvos; se a fonte corrigir um valor, registrar.

## Critério de pronto
- Carga histórica de pelo menos 2 anos de cotações e macro para os ativos da lista.
- Rodar `scripts/coletar.py` duas vezes seguidas: a segunda traz 0 (ou poucos) registros novos.
- Resumo mostrado ao usuário: registros por tabela, período coberto por ativo, falhas.
- `pytest` passa.
