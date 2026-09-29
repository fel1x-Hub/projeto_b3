# Rótulos manuais

## `sentimento.csv`
Esta é a amostra de 100 notícias usada para medir a qualidade do modelo de sentimento, com `scripts/avaliar_sentimento.py`.

**Amostra.** Entram todas as notícias associadas a algum ativo (12) mais 88 sorteadas das demais, com semente 42, entre as 192 coletadas até 29/09/2026.

**Quem rotulou.** Os rótulos foram feitos pelo Claude (`rotulado_por = claude`), a pedido do usuário, lendo apenas o título. Por isso as métricas medem a concordância do modelo com essa referência, não com um humano. A recomendação é revisar por amostragem e trocar `rotulado_por` para o seu nome nas linhas que você conferir ou corrigir.

**Critério.** Os títulos são avaliados do ponto de vista de um investidor em ações:
- **positivo:** notícia favorável para a empresa, o setor ou o mercado citado, como alta de preços, lucro, contrato, expansão, lançamento de produto, melhora de indicador macro ou entrada de capital.
- **negativo:** notícia desfavorável, como queda, déficit, inadimplência, derrota judicial, sanção, corte de previsão, piora de indicador ou risco.
- **neutro:** notícia factual sem direção clara, com efeitos mistos, ou sem relevância financeira (entretenimento, esportes, cultura, política eleitoral).

**Casos de fronteira.** As decisões foram estas, e os casos iguais recebem o mesmo rótulo:
- Compras e aquisições feitas pela empresa (ex.: a Petrobras comprando GNL, a Pearson comprando uma plataforma) são neutras. Novos negócios e parcerias que expandem a empresa são positivos.
- Indicadores estáveis ("desemprego fica em 5,3%") são neutros. Recordes ou mudanças são positivos ou negativos, conforme a direção.
