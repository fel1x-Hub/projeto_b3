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
| modelo principal (sem eventos) | +0.1048 | 0.115 | 84% | +5.22 | +1.40% |
| modelo com eventos | +0.0982 | 0.117 | 80% | +4.94 | +1.14% |
| modelo, horizonte 5 pregões | +0.0724 | 0.126 | 72% | +8.33 | +0.62% |
| aleatório | -0.0010 | 0.060 | 50% | +0.25 | +0.62% |
| momentum (ret_63d) | +0.0384 | 0.128 | 66% | +1.67 | +1.48% |
| valor (fund_lp) | +0.1187 | 0.115 | 84% | +6.03 | -3.25% |
| eventos (evt_saldo) | +0.0222 | 0.103 | 5% | +0.16 | +0.63% |

### IC médio por ano

| Método | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|
| modelo principal (sem eventos) | +0.071 | +0.081 | +0.103 | +0.131 | +0.115 |
| modelo com eventos | +0.007 | +0.076 | +0.101 | +0.133 | +0.108 |
| modelo, horizonte 5 pregões | +0.041 | +0.051 | +0.079 | +0.087 | +0.083 |
| aleatório | -0.008 | +0.002 | +0.002 | -0.004 | -0.003 |
| momentum (ret_63d) | +0.021 | +0.001 | +0.061 | +0.066 | +0.025 |
| valor (fund_lp) | +0.174 | +0.090 | +0.125 | +0.144 | +0.093 |
| eventos (evt_saldo) | +0.045 | -0.048 | +nan | +nan | +nan |

### Por faixa de liquidez

| Método | IC médio | desvio | dias IC>0 | t (sem sobreposição) | spread top−bottom decil (21d) |
|---|---|---|---|---|---|
| ≥ R$ 5 mi/dia · modelo principal (sem eventos) | +0.0816 | 0.139 | 73% | +3.43 | +2.42% |
| ≥ R$ 5 mi/dia · valor (fund_lp) | +0.0972 | 0.135 | 79% | +4.19 | -1.17% |
| ≥ R$ 5 mi/dia · momentum (ret_63d) | +0.0163 | 0.142 | 58% | +0.56 | +0.32% |
| R$ 1–5 mi/dia · modelo principal (sem eventos) | +0.1038 | 0.166 | 74% | +3.42 | +2.34% |
| R$ 1–5 mi/dia · valor (fund_lp) | +0.1263 | 0.166 | 76% | +4.81 | +1.42% |
| R$ 1–5 mi/dia · momentum (ret_63d) | +0.0526 | 0.185 | 63% | +1.35 | +2.29% |
| R$ 0,1–1 mi/dia · modelo principal (sem eventos) | +0.1608 | 0.156 | 85% | +7.09 | -0.26% |
| R$ 0,1–1 mi/dia · valor (fund_lp) | +0.1618 | 0.175 | 81% | +5.82 | -12.11% |
| R$ 0,1–1 mi/dia · momentum (ret_63d) | +0.0785 | 0.189 | 68% | +2.71 | +6.13% |

### Sinais que mais pesam no modelo principal (último pregão)

| Sinal | Contribuição média absoluta |
|---|---|
| fund_lp | 0.0132 |
| vol_63d | 0.0130 |
| fund_pvp | 0.0105 |
| fund_margem_ebitda | 0.0069 |
| vol_21d | 0.0061 |
| fund_cresc_receita | 0.0061 |
| fund_cresc_lucro | 0.0051 |
| dist_mm200 | 0.0050 |
| fund_pl | 0.0050 |
| fund_roe | 0.0036 |
| fund_margem_liq | 0.0031 |
| fund_divliq_ebitda | 0.0029 |
| ret_63d | 0.0028 |
| ret_21d | 0.0023 |
| dist_mm50 | 0.0019 |
| ret_1d | 0.0016 |
| dist_mm21 | 0.0011 |
| rsi14 | 0.0004 |
| ret_5d | 0.0003 |
| vol_fin_rel21 | 0.0002 |

