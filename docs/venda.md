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

## Resultados

(preenchido por `scripts/avaliar_venda.py`)
