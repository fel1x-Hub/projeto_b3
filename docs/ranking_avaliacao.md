# Avaliação do ranking (30/09/2026)

- Período fora da amostra: 03/10/2022 a 29/09/2026 (walk-forward com retreino trimestral; treino só com alvos já realizados).
- Universo: 279 ações/dia em média.
- IC = correlação de Spearman entre score e retorno futuro, por dia. t usa só dias sem sobreposição do horizonte.
- Spread = retorno médio do decil de maior score menos o de menor, nos próximos 21 pregões (sem custos).
- **Variações do modelo testadas: 3** — modelo principal (sem eventos); modelo com eventos; modelo, horizonte 5 pregões.
- O modelo principal foi escolhido ANTES de ver os resultados (sem eventos, por causa do risco de look-ahead do LLM); as outras variações são sensibilidade.

### Período completo

| Método | IC médio | desvio | dias IC>0 | t (sem sobreposição) | spread top−bottom decil (21d) |
|---|---|---|---|---|---|
| modelo principal (sem eventos) | +0.1087 | 0.119 | 84% | +5.54 | +3.60% |
| modelo com eventos | +0.1019 | 0.118 | 81% | +5.23 | +3.23% |
| modelo, horizonte 5 pregões | +0.0725 | 0.128 | 72% | +8.20 | +1.10% |
| aleatório | -0.0010 | 0.060 | 50% | +0.27 | -0.21% |
| momentum (ret_63d) | +0.0408 | 0.127 | 67% | +1.81 | +1.34% |
| valor (fund_lp) | +0.1214 | 0.115 | 84% | +6.27 | +3.74% |
| eventos (evt_saldo) | +0.0222 | 0.103 | 5% | +0.16 | +0.63% |

### IC médio por ano

| Método | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|
| modelo principal (sem eventos) | +0.068 | +0.086 | +0.111 | +0.135 | +0.115 |
| modelo com eventos | +0.007 | +0.083 | +0.105 | +0.136 | +0.109 |
| modelo, horizonte 5 pregões | +0.047 | +0.052 | +0.078 | +0.087 | +0.082 |
| aleatório | -0.008 | +0.002 | +0.002 | -0.004 | -0.003 |
| momentum (ret_63d) | +0.022 | +0.011 | +0.060 | +0.066 | +0.025 |
| valor (fund_lp) | +0.180 | +0.096 | +0.128 | +0.144 | +0.093 |
| eventos (evt_saldo) | +0.045 | -0.048 | +nan | +nan | +nan |

### Por faixa de liquidez

| Método | IC médio | desvio | dias IC>0 | t (sem sobreposição) | spread top−bottom decil (21d) |
|---|---|---|---|---|---|
| ≥ R$ 5 mi/dia · modelo principal (sem eventos) | +0.0821 | 0.141 | 73% | +3.61 | +2.59% |
| ≥ R$ 5 mi/dia · valor (fund_lp) | +0.0975 | 0.135 | 79% | +4.19 | +3.56% |
| ≥ R$ 5 mi/dia · momentum (ret_63d) | +0.0176 | 0.141 | 58% | +0.64 | +0.32% |
| R$ 1–5 mi/dia · modelo principal (sem eventos) | +0.1122 | 0.168 | 75% | +3.94 | +3.99% |
| R$ 1–5 mi/dia · valor (fund_lp) | +0.1292 | 0.168 | 76% | +4.92 | +3.66% |
| R$ 1–5 mi/dia · momentum (ret_63d) | +0.0566 | 0.184 | 65% | +1.50 | +2.58% |
| R$ 0,1–1 mi/dia · modelo principal (sem eventos) | +0.1695 | 0.156 | 86% | +7.47 | +4.41% |
| R$ 0,1–1 mi/dia · valor (fund_lp) | +0.1707 | 0.174 | 83% | +6.25 | +2.82% |
| R$ 0,1–1 mi/dia · momentum (ret_63d) | +0.0838 | 0.188 | 71% | +2.93 | +2.63% |

### Sinais que mais pesam no modelo principal (último pregão)

| Sinal | Contribuição média absoluta |
|---|---|
| fund_lp | 0.0141 |
| vol_63d | 0.0127 |
| fund_pvp | 0.0101 |
| vol_21d | 0.0064 |
| fund_margem_ebitda | 0.0061 |
| fund_cresc_receita | 0.0060 |
| dist_mm200 | 0.0052 |
| fund_cresc_lucro | 0.0051 |
| fund_pl | 0.0042 |
| fund_roe | 0.0038 |
| fund_margem_liq | 0.0030 |
| fund_divliq_ebitda | 0.0029 |
| ret_63d | 0.0026 |
| ret_21d | 0.0023 |
| dist_mm50 | 0.0018 |
| ret_1d | 0.0017 |
| dist_mm21 | 0.0011 |
| rsi14 | 0.0005 |
| ret_5d | 0.0001 |
| vol_fin_rel21 | 0.0001 |

