# Avaliação do ranking (02/10/2026)

- Período fora da amostra: 03/10/2022 a 01/10/2026 (walk-forward com retreino trimestral; treino só com alvos já realizados).
- Universo: 279 ações/dia em média.
- IC = correlação de Spearman entre score e retorno futuro, por dia. t usa só dias sem sobreposição do horizonte.
- Spread = retorno médio do decil de maior score menos o de menor, nos próximos 21 pregões (sem custos).
- **Variações do modelo testadas: 3** — modelo principal (sem eventos); modelo com eventos; modelo, horizonte 5 pregões.
- O modelo principal foi escolhido ANTES de ver os resultados (sem eventos, por causa do risco de look-ahead do LLM); as outras variações são sensibilidade.

### Período completo

| Método | IC médio | desvio | dias IC>0 | t (sem sobreposição) | spread top−bottom decil (21d) |
|---|---|---|---|---|---|
| modelo principal (sem eventos) | +0.1224 | 0.127 | 86% | +5.79 | +3.92% |
| modelo com eventos | +0.1229 | 0.125 | 86% | +5.92 | +4.03% |
| modelo, horizonte 5 pregões | +0.0778 | 0.134 | 73% | +8.33 | +1.20% |
| aleatório | -0.0009 | 0.060 | 50% | +0.27 | -0.21% |
| momentum (ret_63d) | +0.0406 | 0.127 | 67% | +1.81 | +1.34% |
| valor (fund_lp) | +0.1213 | 0.115 | 84% | +6.27 | +3.74% |
| eventos (evt_saldo) | +0.0222 | 0.090 | 54% | +1.27 | +0.50% |

### IC médio por ano

| Método | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|
| modelo principal (sem eventos) | +0.168 | +0.093 | +0.129 | +0.144 | +0.107 |
| modelo com eventos | +0.174 | +0.092 | +0.135 | +0.139 | +0.108 |
| modelo, horizonte 5 pregões | +0.102 | +0.054 | +0.085 | +0.090 | +0.075 |
| aleatório | -0.008 | +0.002 | +0.002 | -0.004 | -0.003 |
| momentum (ret_63d) | +0.022 | +0.011 | +0.060 | +0.066 | +0.024 |
| valor (fund_lp) | +0.180 | +0.096 | +0.128 | +0.144 | +0.093 |
| eventos (evt_saldo) | +0.113 | +0.039 | +0.035 | -0.034 | +0.028 |

### Por faixa de liquidez

| Método | IC médio | desvio | dias IC>0 | t (sem sobreposição) | spread top−bottom decil (21d) |
|---|---|---|---|---|---|
| ≥ R$ 5 mi/dia · modelo principal (sem eventos) | +0.1001 | 0.152 | 77% | +3.80 | +2.74% |
| ≥ R$ 5 mi/dia · valor (fund_lp) | +0.0976 | 0.135 | 79% | +4.19 | +3.56% |
| ≥ R$ 5 mi/dia · momentum (ret_63d) | +0.0175 | 0.141 | 58% | +0.64 | +0.32% |
| R$ 1–5 mi/dia · modelo principal (sem eventos) | +0.1110 | 0.177 | 76% | +4.04 | +4.54% |
| R$ 1–5 mi/dia · valor (fund_lp) | +0.1288 | 0.168 | 76% | +4.92 | +3.64% |
| R$ 1–5 mi/dia · momentum (ret_63d) | +0.0562 | 0.184 | 65% | +1.50 | +2.59% |
| R$ 0,1–1 mi/dia · modelo principal (sem eventos) | +0.1839 | 0.158 | 87% | +7.92 | +4.67% |
| R$ 0,1–1 mi/dia · valor (fund_lp) | +0.1707 | 0.173 | 83% | +6.25 | +2.82% |
| R$ 0,1–1 mi/dia · momentum (ret_63d) | +0.0835 | 0.188 | 70% | +2.93 | +2.62% |

### Sinais que mais pesam no modelo principal (último pregão)

| Sinal | Contribuição média absoluta |
|---|---|
| vol_63d | 0.0152 |
| fund_lp | 0.0124 |
| fund_pvp | 0.0116 |
| fund_cresc_receita | 0.0080 |
| fund_margem_ebitda | 0.0073 |
| fund_cresc_lucro | 0.0071 |
| vol_21d | 0.0061 |
| dist_mm200 | 0.0061 |
| fund_roe | 0.0058 |
| fund_pl | 0.0048 |
| fund_divliq_ebitda | 0.0038 |
| ret_63d | 0.0037 |
| fund_margem_liq | 0.0030 |
| ret_1d | 0.0021 |
| ret_21d | 0.0019 |
| dist_mm50 | 0.0017 |
| dist_mm21 | 0.0017 |
| vol_fin_rel21 | 0.0008 |
| rsi14 | 0.0006 |
| ret_5d | 0.0003 |

