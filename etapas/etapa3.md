# Etapa 3 — Extração de sinais

## Objetivo
Transformar os dados brutos em sinais numéricos por ativo e por data, respeitando sempre `disponivel_em`.

## Tarefas
### 3.1 Sinais técnicos (código puro)
- Retornos (1, 5, 21, 63 dias), médias móveis e distância do preço até elas, RSI, volatilidade, volume relativo à média.
- Usar pandas (ou biblioteca como `ta`, se justificado).

### 3.2 Sinais fundamentalistas (código puro)
- A partir dos documentos da CVM: P/L, P/VP, ROE, margem líquida, margem EBITDA, dívida líquida/EBITDA, crescimento de receita e lucro.
- Cada indicador só passa a valer a partir do `disponivel_em` do documento que o originou.

### 3.3 Sentimento de notícias
- Começar com um modelo pronto de sentimento em português (ou classificação via LLM) e medir qualidade numa amostra rotulada à mão (mín. 100 notícias).
- Fine-tuning (LoRA/QLoRA ou modelo tipo BERT) só se a qualidade inicial for insuficiente. Justificar antes.
- Agregar por ativo e dia: média de sentimento, número de notícias, variação vs. média recente.

### 3.4 Extração de eventos com LLM
- LLM lê fatos relevantes e releases e devolve JSON estruturado (tipo de evento, direção esperada, resumo curto).
- Validar o JSON com schema; descartar e registrar respostas inválidas.
- O LLM NÃO calcula números; só classifica e resume.
- Cache das respostas para não reprocessar o mesmo documento.

### 3.5 Armazenamento
- Tabela `sinais` (ticker, data, nome_sinal, valor, `disponivel_em`, versão do cálculo) ou formato largo, justificando a escolha.

## Testes obrigatórios
- Teste anti look-ahead: para uma data D, calcular sinais e garantir que nenhum dado com `disponivel_em` > D foi usado.
- Testes dos indicadores contra valores calculados à mão em casos pequenos.

## Critério de pronto
- `scripts/gerar_sinais.py` gera sinais para todo o histórico disponível.
- Relatório de cobertura: quais sinais existem para cada ativo e período, e percentual de valores faltantes.
- Qualidade do sentimento medida e reportada na amostra rotulada.
- `pytest` passa, incluindo o teste anti look-ahead.
