# Etapa 5 — Backtest e paper trading

## Objetivo
Verificar se o ranking teria gerado resultado em condições realistas e depois acompanhá-lo em tempo real sem dinheiro.

## 5.1 Backtest walk-forward
1. Janela deslizante: treina no passado, gera ranking, simula a carteira no período seguinte, avança a janela, re-treina.
2. Regra de carteira simples e fixada ANTES de ver os resultados (ex: top N ativos, pesos iguais, rebalanceamento semanal ou mensal).
3. Custos realistas: corretagem, emolumentos da B3, spread e slippage. Parametrizar em config.
4. Considerar dividendos e eventos corporativos (desdobramentos/grupamentos) nos preços.
5. Métricas: retorno acumulado e anualizado, volatilidade, Sharpe, drawdown máximo, turnover, comparação com Ibovespa e com os baselines da Etapa 4.
6. Gráfico da curva de patrimônio e do drawdown.
7. Análise de sensibilidade: mudar levemente N, frequência e custos. Resultado bom que some com pequenas mudanças é sinal de overfitting.

## 5.2 Paper trading
1. `scripts/paper_trading.py` roda diariamente: gera ranking, simula decisões da carteira e registra tudo em tabela própria.
2. Nenhum envio de ordem real. Apenas registro.
3. Comparar periodicamente o paper trading com o que o backtest previa para o mesmo período.

## Critério de pronto
- Relatório de backtest com métricas, gráficos, custos e análise de sensibilidade.
- Paper trading rodando e registrando por pelo menos algumas semanas antes de qualquer conclusão.
- Conclusão honesta: a estratégia supera os baselines após custos? Com que consistência?
