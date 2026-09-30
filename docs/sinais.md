# Catálogo de sinais

Os sinais são gerados por `python scripts/gerar_sinais.py` e gravados na tabela `sinais` em formato longo, com o esquema descrito em [schema.md](schema.md). No fim, o script imprime o relatório de cobertura.

## Regra de tempo, que vale para todos os sinais
O sinal do pregão D usa **só** dados com `disponivel_em` menor ou igual a **D às 19:00 BRT**, e esse corte vira o `disponivel_em` do sinal.

O teste anti look-ahead garante essa regra para cada família, em `tests/sinais/test_*.py`:
- calcular com o banco completo e com o banco truncado no corte de D precisa dar resultados idênticos em D;
- inserir dados absurdos no futuro não pode alterar o passado.

## Técnicos (`src/sinais/tecnicos.py`, versão 1)
Todos são calculados sobre o **índice de retorno total**, montado a partir do preço bruto da B3 e da tabela `proventos`.
- Na data ex, o retorno do dia é `(P × fator + dividendo) / P_anterior − 1`.
- Evento em dia sem pregão é aplicado no pregão seguinte.
- **Validação:** o retorno acumulado de 5 anos difere do preço ajustado do Yahoo em menos de 0,5 ponto percentual em BBAS3, SBSP3, WEGE3, BBDC4 e VIVT3. Na PETR4 a diferença é de 1,5% relativo, por diferença de método com dividendos muito grandes.

| Sinal | Definição |
|---|---|
| `ret_1d`, `ret_5d`, `ret_21d`, `ret_63d` | Retorno total em n pregões. |
| `dist_mm21`, `dist_mm50`, `dist_mm200` | Índice ÷ média móvel de n pregões − 1. |
| `rsi14` | RSI de Wilder, com médias exponenciais de alfa 1/14. |
| `vol_21d`, `vol_63d` | Desvio padrão do retorno diário × √252. |
| `vol_fin_rel21` | Volume financeiro (quantidade × preço) ÷ média dos 21 pregões anteriores. Não é afetado por desdobramentos. |

Sinais sem janela completa ficam ausentes.

## Fundamentalistas (`src/sinais/fundamentalistas.py`, versão 1)
Para cada data, o cálculo usa, por documento, a **maior versão já entregue**.

**Fluxos TTM (últimos 12 meses):**
- num ITR: acumulado do ano + ano anterior − acumulado do mesmo período do ano anterior;
- numa DFP: o valor anual.

**Lucro** é o atribuído aos controladores. **Valor de mercado** = ações (menos tesouraria) × preço.

| Sinal | Definição | Bancos e holdings |
|---|---|---|
| `fund_pl` | Valor de mercado ÷ lucro TTM (só com lucro > 0). | sim |
| `fund_lp` | Lucro TTM ÷ valor de mercado. Aceita prejuízo, é contínuo e é melhor para ranking. | sim |
| `fund_pvp` | Valor de mercado ÷ PL dos controladores. | sim |
| `fund_roe` | Lucro TTM ÷ PL dos controladores. | sim |
| `fund_cresc_lucro` | Lucro TTM ÷ lucro TTM de um ano antes − 1 (só com base > 0). | sim |
| `fund_margem_liq` | Lucro TTM ÷ receita TTM. | não |
| `fund_margem_ebitda` | (EBIT + D&A da DVA) TTM ÷ receita TTM. | não |
| `fund_divliq_ebitda` | (Empréstimos e financiamentos − caixa e aplicações) ÷ EBITDA TTM. | não |
| `fund_cresc_receita` | Receita TTM ÷ receita TTM de um ano antes − 1. | não |

**Limitações e tratamentos dos dados da CVM:**
- **Última versão:** a CVM só publica os valores da última versão de cada documento. No histórico, um documento reapresentado só "existe" a partir da reapresentação. Caso extremo: o BTG reapresentou os balanços de 2020 a 2024 entre nov/2024 e jan/2025, então os sinais de lucro do **BPAC11 só começam em dez/2024**. Daqui para a frente, a coleta diária guarda cada versão quando ela sai.
- **Plano de contas:** as contas são localizadas pela **descrição**. Os bancos usam outro plano, com o lucro em 3.09.01 no Itaú e no BTG e em 3.11.01 no BB e no Bradesco.
- **Bancos e holdings:** instituições financeiras e holdings não têm margens, EBITDA, dívida nem crescimento de receita. Considero holding quando o lucro supera a receita, como na Itaúsa.
- **Ações em milhares:** Ambev, Vale, Itaú, Cemig, Itaúsa e Bradesco (2020–21) informam o número de ações em milhares, sem coluna de escala. Isso é detectado pelo P/VP implausível (< 0,03), e o número é multiplicado por 1.000.
- **Controladores zerados:** a Sabesp deixa a linha "atribuído aos controladores" zerada. Nesse caso uso a conta-mãe.
- **Consolidado ou individual:** uso o consolidado quando o documento tiver; senão, o individual.
- **Aproximações:** o valor de mercado usa o preço do ticker acompanhado para todas as classes de ação, e ON e PN costumam ter preços diferentes. Units usam o preço ÷ ações por unit (BPAC11 = 3). As ações são ajustadas por desdobramentos posteriores à data de referência.
- **Ano fiscal:** o exercício é tratado como ano civil, o que vale para todo o universo atual.

## Sentimento (`src/sinais/sentimento.py`, versão 1)
O modelo é o [FinBERT-PT-BR](https://huggingface.co/lucas-leme/FinBERT-PT-BR), em CPU. Ele classifica o **título** de cada notícia, e `score = P(positivo) − P(negativo)`.

Cada notícia associada ao ativo entra no primeiro pregão cujo corte é igual ou posterior à sua disponibilidade. Uma notícia de sábado, por exemplo, vai para segunda.

| Sinal | Definição |
|---|---|
| `sent_n_dia` | Número de notícias no pregão (0 quando não houve). |
| `sent_media_dia` | Score médio do pregão (só com notícias). |
| `sent_media_21d` | Score médio das notícias dos últimos 21 pregões. |
| `sent_delta` | `sent_media_dia − sent_media_21d`. |

**Limitação:** o RSS não tem histórico, então há sinais só a partir do início da coleta de notícias (29/09/2026).

**Qualidade** (detalhes em [sentimento_avaliacao.md](sentimento_avaliacao.md)). Medida em 100 notícias rotuladas pelo Claude:

| | Acurácia | F1 macro |
|---|---|---|
| Modelo | 69% | 0,67 |
| Linha de base "sempre neutro" | 58% | 0,245 |

O modelo passa do limite de 0,6 combinado, mas tem um **viés para o negativo**: acerta 96% dos negativos, porém só 48% do que chama de negativo é mesmo negativo. Ele lê verbos de queda sem o contexto de mercado:
- "juros recuam" e "dólar recua" são bons para a bolsa, e ele marca como negativos;
- "IGP-M sobe" é inflação subindo, e ele marca como positivo.

Um viés constante afeta pouco o `sent_delta`, que compara com a média recente do próprio ativo. Se na etapa 4 o sentimento pesar no ranking, vale testar a classificação dos títulos pelo LLM (Gemini), que entende esse contexto.

## Eventos (`src/sinais/eventos.py`, versão 1, prompt versão 1)
O LLM é o **Gemini** (`gemini-3.5-flash-lite`, plano grátis), configurado por `GEMINI_MODELO` no `.env`. Ele lê:
- todos os fatos relevantes;
- os releases de resultado em português, só nas primeiras 4 páginas, que trazem os destaques.

São ~1.400 documentos. O modelo devolve JSON validado por schema (pydantic) com tipo do evento, direção (positiva, neutra ou negativa), relevância (1 a 5) e resumo. **Ele não calcula números.** As respostas inválidas vão para `llm_erros`, e as válidas ficam em `llm_cache`, sem reprocessar.

A extração roda em `python scripts/extrair_eventos.py`, que é retomável: para quando a cota grátis acaba e continua na próxima execução. O ritmo é de ~9 requisições por minuto (`GEMINI_PAUSA`).

Cada evento vale `s = direção (+1, 0 ou −1) × relevância`.

| Sinal | Definição |
|---|---|
| `evt_saldo` | Soma de `s × 0,5^(idade/10)`, com idade em pregões e janela de 63 pregões (meia-vida de 10). |
| `evt_n_21d` | Número de eventos nos últimos 21 pregões. |

**Cobertura.** Um pregão só recebe sinal se todos os documentos da sua janela já foram processados. Assim, um documento pendente não vira um falso "sem evento". Documentos com erro permanente, como um arquivo que não é PDF, contam como processados sem evento.

**Risco residual de look-ahead.** O modelo conhece fatos posteriores à data de cada documento. O prompt manda julgar só pelo texto e pelo que se sabia na data, mas isso não é garantido. Trate este sinal com cautela no backtest da etapa 5, por exemplo comparando o desempenho com e sem ele.
