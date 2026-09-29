# Etapa 4 — Modelo de ranking

## Objetivo
Combinar os sinais da Etapa 3 em um score por ativo e por dia, que ordene os ativos pela atratividade esperada.

## Tarefas
1. Definir o alvo (target) e justificar. Sugestão inicial: retorno dos próximos 5 ou 21 pregões, relativo ao Ibovespa ou à média dos ativos da lista.
2. Montar a matriz de features a partir da tabela `sinais`, só com dados disponíveis na data.
3. Baselines simples primeiro, para ter com o que comparar:
   - Ranking aleatório
   - Ranking só por momentum
   - Ranking só por sentimento
4. Modelo principal: LightGBM (regressão ou ranking). Hiperparâmetros modestos; nada de busca exaustiva.
5. Validação temporal: divisão por tempo, com intervalo (gap) entre treino e teste do tamanho do horizonte do alvo. NUNCA divisão aleatória.
6. Métricas: correlação de ranking (Spearman/IC) entre score e retorno futuro, média e estabilidade ao longo do tempo; retorno do top N vs. bottom N.
7. Importância das features (ex: SHAP) para entender o que o modelo está usando.
8. Salvar modelo versionado e scores na tabela `ranking` (ticker, data, score, posição, versão do modelo).

## Alertas
- Com poucos ativos, o sinal estatístico é fraco. Reportar isso com honestidade; considerar ampliar o universo de ativos.
- Se o modelo for muito melhor que os baselines, desconfie primeiro de vazamento de dados antes de comemorar.
- Registrar quantas variações foram testadas (quanto mais testes, maior o risco de overfitting).

## Critério de pronto
- Comparação modelo vs. baselines apresentada em tabela, período a período.
- `scripts/gerar_ranking.py` gera o ranking de uma data qualquer usando só dados disponíveis até ela.
- `pytest` passa.
