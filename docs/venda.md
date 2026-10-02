# Nota de venda por "chance de cair": pré-registro e resultados

## Pré-registro (02/10/2026, escrito ANTES de rodar)

**Pedido do usuário.** A nota de venda (0 a 100) deve indicar se é hora de vender. Hoje ela é 100 − compra, mais metade da queda no ranking; isso mostra que a ação está mal colocada, não que vai cair. Ninguém identifica o topo exato. O que se mede aqui é a **chance de o preço cair**, um alvo absoluto e não relativo ao mercado.

**Alvo.** O retorno total da ação nos próximos 21 pregões é negativo, com execução no fechamento do pregão seguinte. O mesmo cálculo é feito para 63 pregões, só como informação.

**Modelo.** LightGBM de classificação binária, com walk-forward e retreino trimestral, e os mesmos hiperparâmetros regularizados do ranking. Nada de busca de parâmetros. Sinais usados:
- os mesmos do ranking (técnicos e fundamentalistas, em percentil do dia);
- sinais de "esticada", calculados só com preços até a data:
  - distância da máxima de 252 pregões;
  - retorno de 5 e 21 pregões;
  - RSI;
  - volume contra a média;
  - variação da nota de compra em 10 pregões (histórico fora da amostra do ranking).

**Comparação (fora da amostra, mesmo período).**
- **N.** O modelo novo.
- **A.** A nota de venda atual.
- **B.** 100 − nota de compra.

**Critério para N substituir A.** Precisa cumprir **todos**:
1. AUC de N ≥ AUC de A + 0,01 (separa melhor quem cai de quem sobe);
2. a taxa de queda real no decil de maior nota de N é maior que a do decil de maior nota de A;
3. a probabilidade é calibrada: em cada decil, o previsto e o realizado diferem em no máximo 5 p.p.

Se N falhar, a nota atual continua. Mesmo assim, a tela passa a mostrar a **chance de cair** calibrada por faixa da nota atual, porque é uma tradução honesta do que ela significa.

**Na tela.**
- **Nota de venda (0 a 100):** 100 = maior chance de queda entre as ações do universo hoje.
- **Chance de cair:** "chance de cair no próximo mês: X%", em valor absoluto e calibrado.
- **Na sua carteira:** ao lado, o seu lucro ou prejuízo. Ele não entra na nota. Também aparece um aviso de IR quando a venda gera lucro e as vendas de ações no mês passam de R$ 20 mil.

## Resultados (02/10/2026)

- Período fora da amostra: 03/10/2022 a 31/08/2026. 272.642 casos. Taxa de queda em 1 mês no período: 49.1%.

| Nota | AUC | queda real no decil de maior nota |
|---|---|---|
| N · modelo novo | 0.527 | 58.6% |
| A · nota atual | 0.544 | 58.7% |
| B · 100 − compra | 0.545 | 59.1% |

### Calibração do modelo novo (por decil de probabilidade)

| prob. prevista | queda real | casos |
|---|---|---|
| 29.1% | 41.6% | 27265 |
| 42.5% | 49.3% | 27264 |
| 45.3% | 47.7% | 27264 |
| 47.4% | 48.6% | 27264 |
| 49.4% | 49.4% | 27264 |
| 51.6% | 50.5% | 27264 |
| 54.0% | 51.0% | 27264 |
| 57.2% | 51.2% | 27264 |
| 62.4% | 48.9% | 27264 |
| 76.4% | 53.0% | 27265 |

### Critério pré-registrado

- ❌ AUC de N ≥ AUC de A + 0,01
- ❌ taxa de queda no decil de maior nota: N > A
- ❌ calibração: previsto vs realizado ≤ 5 p.p. em todo decil

**Decisão: a nota atual continua.** A chance de cair mostrada no app vem da calibração de A (tabela venda_calibracao).
