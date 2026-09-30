# Modelo de ranking (etapa 4)

Os números detalhados estão em [ranking_avaliacao.md](ranking_avaliacao.md), gerado por `python scripts/avaliar_ranking.py`. Este documento registra o desenho e a leitura honesta dos resultados.

## Desenho
- **Alvo:** retorno total dos próximos 21 pregões menos a mediana do universo no mesmo dia. O modelo ordena ações entre si; não prevê a direção do mercado.
- **Features:** 20 sinais técnicos e fundamentalistas, convertidos em percentil dentro do universo de cada dia.
  - O sentimento fica de fora até ter histórico.
  - Os eventos entram só como variação de sensibilidade, por causa do risco de look-ahead do LLM.
- **Modelo:** LightGBM com hiperparâmetros fixos e modestos (árvores rasas, 500 amostras por folha, regularização), sem busca exaustiva.
- **Validação walk-forward:** retreino no início de cada trimestre, só com alvos já realizados, o que dá um intervalo de 21 pregões entre treino e teste. Primeiro teste em 10/2022, depois de ~1 ano de treino. Nunca há divisão aleatória.
- **Ranking de uma data** (`scripts/gerar_ranking.py --data AAAA-MM-DD`): treina com o que se sabia no corte da data e grava na tabela `ranking` (versão `lgbm-v1`). O modelo fica salvo em `data/modelos/`. Um teste com dados futuros "envenenados" garante que o ranking de uma data não muda.
- **Histórico fora da amostra:** fica na tabela `ranking` com versão `wf-lgbm-v1`. É a base do backtest da etapa 5.

## Leitura dos resultados (10/2022 a 09/2026, ~280 ações por dia)

1. **O modelo tem sinal consistente, mas não supera o baseline de valor em IC.** O IC médio do modelo é +0,105, contra +0,119 de lucro/preço (`fund_lp`) sozinho. O IC ficou positivo nos 5 anos, e o modelo acertou a ordem em 84% dos dias.
2. **O ganho do modelo está nos extremos, que é o que importa para uma carteira.** O spread entre o decil do topo e o do fundo é +1,4% em 21 dias no geral e **+2,4% nas ações com mais de R$ 5 mi/dia**. O `fund_lp` sozinho tem IC alto, mas spread **negativo** (−3,25% no geral).
   - A causa é que, no decil de pior lucro/preço, a **mediana** dos 21 dias seguintes é −4,7%, mas a **média** é +4,7%. A maioria cai, e umas poucas empresas em crise disparam, como bilhete de loteria.
   - O IC mede a ordem típica; a carteira vive de médias.
3. **O resultado depende do regime.** Os sinais que mais pesam são lucro/preço, baixa volatilidade, P/VP e margens, ou seja, valor, qualidade e baixo risco. Com juros altos (Selic de 13% a 15% no período), empresas com prejuízo e muito endividadas sangraram. **Em outro regime, esse padrão pode enfraquecer.**
4. **As ações pouco líquidas inflam o IC** (+0,16 na faixa de R$ 0,1 a 1 mi/dia), mas com spread negativo e custos de negociação altos. A etapa 5 precisa separar os resultados por faixa de liquidez.
5. **Momentum é fraco** (IC +0,038) e **eventos ainda não ajudam.** A cobertura dos eventos por título ainda estava sendo classificada; reavaliar depois.
6. **Horizonte de 5 pregões:** IC menor (+0,072), mas mais estável (t = 8,3). É candidato para quem rebalanceia toda semana. Decidir na etapa 5.

## Cuidados antes de acreditar
- **Três variações testadas** (principal, com eventos e horizonte de 5), todas registradas. O modelo principal foi fixado antes de ver os resultados.
- **O t-stat usa só dias sem sobreposição** (a cada 21 pregões), porque retornos de 21 dias sobrepostos inflariam a significância.
- **Não houve sinal de vazamento de dados:**
  - o retorno de 1 dia não prevê nada, então não é vaivém de preço;
  - o efeito aparece também nas ações muito líquidas;
  - o ranking de uma data não muda com dados futuros (teste automático).
- **Ainda sem custos nem regra de carteira.** A pergunta real, "dá dinheiro depois dos custos?", é da etapa 5.
