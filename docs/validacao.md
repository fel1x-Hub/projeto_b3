# Validação da estratégia (etapa 5)

Os números estão em [backtest.md](backtest.md), gerado por `python scripts/backtest.py`. Este documento registra a leitura e as decisões.

## Regra testada
Fixada pelo usuário **antes** de ver qualquer resultado:
- top 30 do ranking, com pesos iguais;
- rebalanceamento a cada 10 pregões;
- universo todo (≥ R$ 100 mil/dia);
- só comprada.

Condições do teste:
- **Execução:** no fechamento do pregão seguinte ao ranking.
- **Retornos:** incluem dividendos, JCP e desdobramentos.
- **Custos:** emolumentos de 0,03% mais meio spread por faixa de liquidez.
- **Imposto:** não entra.

## Conclusão honesta (10/2022 a 09/2026)
**A estratégia empatou com o Ibovespa e com o CDI depois dos custos.** Ela ainda não demonstrou vantagem.

| | ao ano | Sharpe (sobre o CDI) | queda máxima | giro anual |
|---|---|---|---|---|
| Regra do usuário | +12,4% | 0,05 | −23,9% | 9,4x |
| Ibovespa (BOVA11) | +12,8% | 0,07 | −18,8% | — |
| CDI | +13,1% | — | 0% | — |

- **O modelo ordena bem, mas a carteira não converte isso em ganho líquido.** O IC é de +0,109, e o spread entre o decil do topo e o do fundo é de +3,6% em 21 dias. O giro de ~9x por ano custa ~2,3% ao ano. Antes dos custos, a regra ficaria ~2 pontos acima do Ibovespa.
- **As sensibilidades ficam em torno do índice**, entre +9% e +14,5% ao ano. O melhor caso (top 20, +14,5%) não deve ser adotado só por ter sido o melhor, porque escolher depois de ver é a forma clássica de se enganar.
- **Só as ações líquidas (≥ R$ 1 mi/dia) renderam menos:** +9,0% ao ano. Parte do resultado vem das pouco negociadas, que são mais difíceis de operar de verdade.
- **O momentum vira negativo** (−3,3% ao ano) quando os erros de dados são corrigidos.
- **Os eventos por LLM não ajudaram** (+10,9% contra +12,4%). A cobertura ainda estava incompleta.

## Correção de dados que mudou o resultado
Grupamentos de ações que o Yahoo não registrou apareciam como altas de +900% a +4.400% num dia (NEXP3, BRPR3, OIBR3, KRSA3, TRAD3 e outros) e inflavam o momentum e o backtest.

Correção, causal e conservadora:
- saltos com razão de preço quase inteira (×10, ÷3...) sem provento registrado são tratados como eventos contábeis;
- altas de mais de 3x num dia também;
- quedas reais, como AMER3 −77% e GOLL4 −69%, continuam contando.

Detalhes em `src/sinais/precos.py`.

## O que isso significa para o uso no app (regra 16)
- As indicações do top 30 devem ser vistas como **ponto de partida para análise**, não como fonte de retorno acima do mercado. É o que o histórico mostra até agora.
- A **regra com folga** (só vender quando a ação sai do top 60) teve metade do giro (4,7x) e +13,0% ao ano. Ela casa com a ideia do app de "vender o que caiu" sem trocar a carteira toda. Fica como candidata a regra do paper trading **depois** de algumas semanas de observação, e não como troca agora.
- Caminhos para melhorar, a testar com cuidado e registrando cada variação:
  - reduzir o giro;
  - completar os eventos;
  - acumular histórico de sentimento;
  - reavaliar fora do regime de juros altos.

## Paper trading
- Começou em 29/09/2026, com a mesma regra e o mesmo motor do backtest, e roda com `python scripts/paper_trading.py`. Na etapa 6 passa a ser automático.
- Nenhuma conclusão antes de **algumas semanas**. Depois, comparar com o que o backtest indicava para um período de mesmo tamanho.
