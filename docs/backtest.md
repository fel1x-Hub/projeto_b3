# Backtest (30/09/2026)

- Período: 04/10/2022 a 29/09/2026 (ranking fora da amostra do walk-forward).
- **Regra fixada pelo usuário antes dos resultados:** top 30 do ranking, pesos iguais, rebalanceamento a cada 10 pregões, universo todo (≥ R$ 100 mil/dia), só comprada.
- Execução no fechamento do pregão seguinte ao ranking; retornos com dividendos/JCP/desdobramentos; custos = emolumentos 0,03% + meio spread (0,05% ≥ R$ 5 mi/dia, 0,15% R$ 1–5 mi, 0,50% abaixo) sobre o giro.
- Não considera imposto de renda.

## Resultado

| Estratégia | Retorno total | ao ano | Volatilidade | Sharpe (sobre CDI) | Queda máxima | Giro anual |
|---|---|---|---|---|---|---|
| **Regra principal (top 30, quinzenal, universo todo)** | +43.0% | +9.5% | 16.9% | -0.11 | -24.2% | 9.2x |
| valor (fund_lp), mesma regra | +57.6% | +12.2% | 17.8% | 0.04 | -25.5% | 3.4x |
| momentum (ret_63d), mesma regra | +58.4% | +12.4% | 49.0% | 0.16 | -30.5% | 9.7x |
| aleatório, mesma regra | -16.3% | -4.4% | 23.0% | -0.62 | -34.4% | 22.5x |
| Ibovespa (BOVA11, comprar e segurar) | +61.1% | +12.8% | 17.1% | 0.07 | -18.8% | nanx |
| CDI | +62.8% | +13.1% | 0.1% | 0.00 | 0.0% | nanx |

![Patrimônio](img/backtest_patrimonio.png)

![Drawdown](img/backtest_drawdown.png)

## Por ano

| | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|
| Modelo | -8.8% | +19.7% | -6.3% | +36.3% | +2.5% |
| BOVA11 | -5.7% | +23.1% | -10.1% | +34.7% | +14.6% |
| CDI | +3.1% | +13.0% | +10.8% | +14.2% | +10.5% |

## Sensibilidade (mudanças pequenas na regra; resultado bom que some aqui é sinal de sorte)

| Estratégia | Retorno total | ao ano | Volatilidade | Sharpe (sobre CDI) | Queda máxima | Giro anual |
|---|---|---|---|---|---|---|
| N = 20 | +42.7% | +9.4% | 17.0% | -0.11 | -25.8% | 10.1x |
| N = 40 | +48.6% | +10.6% | 16.9% | -0.05 | -22.0% | 8.7x |
| rebalanceamento semanal (5 pregões) | +30.1% | +6.9% | 16.9% | -0.25 | -24.7% | 14.5x |
| rebalanceamento mensal (21 pregões) | +80.4% | +16.1% | 16.6% | 0.24 | -20.3% | 6.1x |
| custos em dobro | +23.3% | +5.5% | 16.9% | -0.33 | -25.4% | 9.2x |
| só ações ≥ R$ 1 mi/dia | +43.2% | +9.5% | 19.2% | -0.07 | -22.9% | 8.8x |
| com folga (vende só se sair do top 60) | +53.6% | +11.5% | 16.7% | -0.00 | -25.3% | 4.8x |
| modelo com eventos | +34.6% | +7.8% | 17.9% | -0.18 | -29.8% | 10.0x |

Material de estudo, não recomendação de investimento.
