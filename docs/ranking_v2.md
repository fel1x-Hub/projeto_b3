# Modelo v2: pré-registro e resultados

## Pré-registro (02/10/2026, escrito ANTES de rodar qualquer variação)

**Motivação.** O v1 (LightGBM livre) tem IC +0,109 e spread de +3,60%, abaixo do fator valor sozinho (`fund_lp`: IC +0,121, spread +3,74%). Além disso, ele aprende relações contrárias à teoria econômica nos extremos. Exemplo: TUPY3, com dívida líquida/EBITDA de 103 (EBITDA perto de zero por prejuízo operacional), aparece como "percentil 100: favorece". O dado está correto; a leitura do modelo é que provavelmente é ruído.

**Hipótese.** Restrições monotônicas nos sinais com direção econômica clara reduzem o sobreajuste sem tirar do modelo o que ele acerta.

| Direção | Sinais |
|---|---|
| maior = melhor | `fund_lp`, `fund_roe`, `fund_margem_liq`, `fund_margem_ebitda` |
| maior = pior | `fund_pvp`, `fund_pl`, `fund_divliq_ebitda`, `vol_21d`, `vol_63d` (anomalia de baixa volatilidade) |
| livres | retornos, médias, RSI, volume relativo, crescimento |

**Variações.** São só estas, e todas entram no relatório:
- **A.** v1 atual (referência).
- **B.** v1 + restrições monotônicas. É a candidata a v2.
- **C.** B + sinais de eventos (`evt_saldo`, `evt_n_21d`), recalculados com 96% dos títulos classificados. Só serve como sensibilidade: o LLM pode "saber" o desfecho de fatos antigos (risco de look-ahead), então C **não pode** virar o v2.

**Mesmo protocolo do v1.** Walk-forward com retreino trimestral, alvo de 21 pregões, mesmos hiperparâmetros, mesmo período fora da amostra, e backtest com a regra do usuário: top 30, quinzenal, universo todo, custos por faixa de liquidez.

**Critério de adoção do B como v2.** Precisa cumprir **todos**:
1. IC médio ≥ o do A;
2. spread topo−fundo (21d) ≥ o do A;
3. IC médio positivo em todos os anos;
4. retorno anual do backtest, depois dos custos, ≥ o do A.

Se falhar em qualquer um, o v1 continua. Mesmo aprovado, a troca **só acontece com a autorização do usuário**, porque reinicia a contagem do paper trading (que começou em 29/09/2026 com o v1).

## Resultados

(preenchido por `scripts/avaliar_v2.py`)
