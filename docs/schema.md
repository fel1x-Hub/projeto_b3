# Schema do banco

Banco SQLite local em `data/b3.db` (configurável por `DB_PATH` no `.env`). O SQL está em [src/db/schema.py](../src/db/schema.py) e é aplicado pelas migrações de [src/db/migracoes.py](../src/db/migracoes.py).

Criar ou atualizar: `python scripts/init_db.py`. O comando é idempotente.

## Regra anti look-ahead

Toda tabela de dados tem duas colunas de tempo:

| Coluna | Significado |
|---|---|
| `disponivel_em` | Quando a informação **ficou pública**. |
| `coletado_em` | Quando o sistema baixou o dado. Serve só para auditoria. |

Nenhum cálculo, sinal ou modelo pode usar uma linha com `disponivel_em` posterior ao momento analisado. A consulta padrão é:

```sql
SELECT ... FROM cotacoes WHERE ticker = ? AND disponivel_em <= ?
```

Exemplos de `disponivel_em` por fonte:
- **Cotação de fechamento**: fim do pregão do dia.
- **IPCA de março**: o dia da divulgação, em abril, e não 1º de março.
- **Fato relevante**: o horário de entrega na CVM.

## Convenções de formato

| Tipo | Formato | Validação no banco |
|---|---|---|
| Data de referência | `YYYY-MM-DD` | `CHECK (col IS date(col))`, que rejeita `02/01/2026` e `2026-02-30`. |
| Timestamp | `YYYY-MM-DDTHH:MM:SS+00:00`, sempre em **UTC** | `CHECK (col GLOB ...)`, que rejeita horário local, microssegundos e outros fusos. |

Com um formato único em UTC, comparar texto é o mesmo que comparar instantes. Use sempre `src.db.tempo.para_iso_utc(dt)` para gerar timestamps. A função recusa `datetime` sem fuso para não confundir o horário de Brasília (UTC−3) com UTC.

Outras garantias:
- Chaves estrangeiras estão ligadas (`PRAGMA foreign_keys = ON`).
- O banco usa WAL, e leituras não bloqueiam escritas.

## Tabelas

### `ativos`
O universo de papéis acompanhados, sincronizado a partir de [config/ativos.csv](../config/ativos.csv).

| Coluna | Tipo | Notas |
|---|---|---|
| ticker | TEXT PK | Código B3 (ex.: PETR4, B3SA3, BPAC11). |
| nome | TEXT NOT NULL | |
| setor | TEXT | |
| cnpj | TEXT | Preenchido na etapa 2 (cadastro CVM). Um valor vazio no CSV não apaga o que já está no banco. |
| codigo_cvm | TEXT | Liga os documentos da CVM ao ticker. |
| ativo | INTEGER 0/1 | 0 = não acompanhado. |
| apelidos | TEXT | *(v2)* Termos para achar a empresa em notícias, separados por `\|`. Se vazio, usa o `nome`. |
| tipo | TEXT | *(v2)* `acao` ou `benchmark`. Benchmarks (ex.: BOVA11) são coletados, mas não entram no ranking. |
| criado_em, atualizado_em | timestamp | |

As linhas nunca são apagadas. Um ticker removido do CSV vira `ativo = 0` e mantém o histórico ligado a ele.

### `cotacoes`
Preços diários por pregão.

| Coluna | Tipo | Notas |
|---|---|---|
| id | INTEGER PK | |
| ticker | TEXT FK → ativos | |
| data | data | Data do pregão. |
| abertura, maxima, minima | REAL > 0 | Opcionais. |
| fechamento | REAL > 0 NOT NULL | |
| fechamento_ajustado | REAL > 0 | Vazio na fonte B3 (que traz preço bruto). O ajuste é calculado em código na etapa 3, a partir de `proventos`. |
| volume | INTEGER ≥ 0 | Quantidade negociada. |
| fonte | TEXT | `b3_cotahist` (arquivo oficial da B3). |
| disponivel_em, coletado_em | timestamp | |

Chave única: `(ticker, data, fonte)`. Se outra fonte for adicionada, as duas guardam o mesmo pregão lado a lado, e quem consome escolhe a preferida.

### `macro`
Séries macroeconômicas (Selic, IPCA, câmbio).

| Coluna | Tipo | Notas |
|---|---|---|
| id | INTEGER PK | |
| serie | TEXT | Nome interno (ex.: `ipca`, `selic`, `usdbrl`). |
| data | data | Data de **referência**. |
| valor | REAL NOT NULL | |
| fonte | TEXT | |
| disponivel_em | timestamp | Data de **divulgação**. |
| coletado_em | timestamp | |

Chave única: `(serie, data, fonte)`.

### `noticias`

| Coluna | Tipo | Notas |
|---|---|---|
| id | INTEGER PK | |
| titulo | TEXT NOT NULL | |
| resumo | TEXT | |
| url | TEXT UNIQUE | Pode ser nula. |
| fonte | TEXT | |
| publicado_em | timestamp | Opcional. |
| disponivel_em | timestamp | Horário de publicação. |
| coletado_em | timestamp | |
| hash | TEXT UNIQUE | sha256 do título normalizado + fonte. |

Há duas barreiras contra duplicatas. O `hash` pega a mesma notícia publicada com URLs diferentes, e a `url` pega a mesma URL com o título editado.

Índice: `disponivel_em`.

### `noticias_ativos`
A relação N:N entre notícia e ticker.

| Coluna | Tipo | Notas |
|---|---|---|
| noticia_id | FK → noticias | Apagar a notícia apaga as associações (`ON DELETE CASCADE`). |
| ticker | FK → ativos | |
| metodo | TEXT | Como a associação foi feita (ex.: `ticker_no_texto`, `nome_no_texto`). |

PK: `(noticia_id, ticker)`. Índice: `ticker`.

O `metodo` existe porque a associação da etapa 2 é heurística, e ele permite medir a qualidade de cada método depois.

### `documentos`
Fatos relevantes, ITR, DFP e releases.

| Coluna | Tipo | Notas |
|---|---|---|
| id | INTEGER PK | |
| tipo | TEXT | `fato_relevante`, `comunicado`, `aviso_acionistas` ou `dados_economico_financeiros` (releases). |
| ticker | FK → ativos | Opcional (documento ainda não mapeado). |
| data_referencia | data | Opcional (ex.: fim do trimestre). |
| fonte | TEXT | |
| id_externo | TEXT NOT NULL | Na CVM: `protocolo-vVERSAO`. Cada reapresentação é um documento próprio. |
| url, conteudo, caminho_arquivo | TEXT | Pelo menos um dos três é obrigatório. |
| assunto | TEXT | *(v3)* Assunto informado pela empresa (ex.: "Relatório de Produção 4T25"). |
| hash_conteudo | TEXT | Detecta quando o conteúdo muda. |
| disponivel_em | timestamp | Data de entrega às 23:59:59 BRT, porque a CVM só informa o dia. |
| coletado_em | timestamp | |

Chave única: `(fonte, id_externo)`. Índice: `(ticker, disponivel_em)`.

Se os dados estruturados da CVM (as contas de DFP/ITR) pedirem uma tabela própria, ela entra como uma nova migração na etapa 2.

### `proventos` *(v2)*
Dividendos e desdobramentos. São usados na etapa 3 para ajustar os preços brutos da B3.

| Coluna | Tipo | Notas |
|---|---|---|
| id | INTEGER PK | |
| ticker | TEXT FK → ativos | |
| tipo | TEXT | `dividendo` ou `desdobramento`. |
| data_ex | data | Primeiro pregão sem direito ao provento. |
| valor | REAL > 0 | Só para `dividendo`: R$ por ação. JCP está incluído, e eventos na mesma data vêm **somados** pelo Yahoo. |
| fator | REAL > 0 | Só para `desdobramento`: ações novas por ação antiga (2 = desdobramento 2:1; 0,1 = grupamento 10:1). |
| fonte | TEXT | `yfinance`, ou `manual` para eventos de `config/eventos_manuais.csv` (ex.: cisão XP/Itaú), sempre com referência ao documento oficial. |
| disponivel_em | timestamp | Data ex às 00:00 BRT. O Yahoo não informa a data de anúncio, que é sempre anterior. |
| coletado_em | timestamp | |

Chave única: `(ticker, fonte, tipo, data_ex)`.

O `valor` está na **escala bruta da época**: casa com o preço bruto da B3 no mesmo dia. O Yahoo divide dividendos antigos pelos desdobramentos posteriores, e a coleta desfaz isso multiplicando pelos fatores dos desdobramentos com data ex posterior.

### `demonstracoes` *(v2)*
As demonstrações financeiras da CVM (DFP anual e ITR trimestral), em formato longo, com uma linha por conta.

| Coluna | Tipo | Notas |
|---|---|---|
| id | INTEGER PK | |
| codigo_cvm | TEXT | Liga com `ativos.codigo_cvm`. É por empresa, e não por ticker: PETR3 e PETR4 compartilham o mesmo código. |
| tipo_doc | TEXT | `DFP` ou `ITR`. |
| data_referencia | data | Fim do exercício ou do trimestre. |
| versao | INTEGER | 1 = original; valores maiores são reapresentações. |
| demonstrativo | TEXT | `BPA`, `BPP`, `DRE`, `DFC_MD`, `DFC_MI`, `DVA` ou `CAPITAL` (número de ações). |
| consolidado | INTEGER 0/1 | |
| data_ini | data | Início do período. Vazio em balanço patrimonial e em `CAPITAL`. |
| data_fim | data | Fim do período, ou data do balanço. |
| cd_conta | TEXT | Código da conta (ex.: `3.11` = lucro líquido). Em `CAPITAL`, é o nome da coluna da CVM. |
| ds_conta | TEXT | Descrição da conta. |
| valor | REAL | Em **reais**, com a escala MIL já aplicada. Em `CAPITAL`, é o número de ações. |
| disponivel_em | timestamp | Data de entrega (`DT_RECEB`) às 23:59:59 BRT. |
| coletado_em | timestamp | |

Só guardo o exercício "ÚLTIMO" de cada documento, porque o "PENÚLTIMO" é apenas a coluna comparativa.

**Versões:** os arquivos abertos da CVM só trazem os valores da **última versão** de cada documento. As anteriores aparecem só no índice.
- **No histórico:** cada documento fica disponível a partir da entrega da última versão. É conservador: nunca adianta o dado, mas pode atrasá-lo algumas semanas quando houve reapresentação.
- **Daqui para a frente:** a coleta frequente guarda a v1 quando ela sai, e a v2 entra depois sem apagar a v1. O ponto-no-tempo real se acumula com o tempo.

**Uso ponto-no-tempo:** para uma data D, use, por documento, a maior `versao` com `disponivel_em <= D`.

Índice único: sobre a identidade completa da linha, com `COALESCE` nas datas, porque no SQLite dois NULLs nunca colidem num índice único.

### `sinais` *(v4)*
Sinais por ativo e pregão, em **formato longo**, com um valor por linha. Um valor ausente é uma linha ausente.

| Coluna | Tipo | Notas |
|---|---|---|
| ticker | FK → ativos | |
| data | data | Pregão. |
| nome | TEXT | Ex.: `ret_21d`, `rsi14`, `fund_pvp`, `sent_media_dia`. Catálogo em `docs/sinais.md`. |
| valor | REAL NOT NULL | |
| versao | INTEGER | Versão da fórmula. Muda quando o cálculo muda. |
| disponivel_em | timestamp | Corte usado no cálculo: o pregão às 19h BRT. O sinal só usa dados com `disponivel_em` menor ou igual a esse corte. |
| calculado_em | timestamp | |

Chave única: `(ticker, data, nome, versao)`.

Escolhi o formato longo porque:
- um sinal novo não exige migração;
- cobertura e faltantes saem de uma consulta;
- a etapa 4 transforma em colunas quando precisar.

### `sentimento_noticias` *(v4)*
Uma linha por notícia e modelo. Guarda o rótulo (`positivo`, `neutro` ou `negativo`), as três probabilidades e `score = P(positivo) − P(negativo)`.

### `eventos_documentos`, `llm_cache` e `llm_erros` *(v4)*
São da extração de eventos com LLM (etapa 3.4).
- **`eventos_documentos`:** tipo do evento, direção, relevância (1 a 5) e resumo, por documento, modelo e versão do prompt.
- **`llm_cache`:** as respostas, indexadas por um hash da entrada, do modelo e da versão do prompt, para nunca reprocessar.
- **`llm_erros`:** respostas fora do schema e falhas.

### `carteira_operacoes` *(v9)*
Compras e vendas da carteira real, manuais ou importadas de extrato. A posição **nunca é gravada**: é recalculada destas linhas (preço médio pela regra da Receita, desdobramentos de `proventos`). Ver [src/carteira/posicoes.py](../src/carteira/posicoes.py).

| Coluna | Tipo | Notas |
|---|---|---|
| id | INTEGER PK | |
| ticker | TEXT | Sem FK: a carteira pode ter papéis fora do universo (FII, ETF). |
| tipo | TEXT | `compra` ou `venda`. |
| data | date | Data do negócio. |
| quantidade, preco | REAL > 0 | |
| custos | REAL ≥ 0 | Corretagem e emolumentos. |
| origem | TEXT | `manual` ou `importacao`. |
| referencia | TEXT UNIQUE | Na importação, é o hash do conteúdo da linha mais a ordem entre linhas idênticas. Reimportar não duplica. |
| criado_em | timestamp | |

### `carteira_sincronizada` *(v9)*
Foto das posições da corretora via Meu Pluggy (Open Finance). É substituída inteira a cada sincronização. Quando existe, a quantidade vem daqui.

| Coluna | Tipo | Notas |
|---|---|---|
| ticker | TEXT PK | Fracionário somado ao lote (PETR4F → PETR4). |
| quantidade | REAL | |
| valor_aplicado | REAL | Custo informado pela corretora (`amountOriginal`). |
| valor_corretora | REAL | Valor de mercado segundo a corretora (`amount`). |
| instituicao | TEXT | |
| data_corretora | timestamp | Data de referência do dado na corretora. |
| sincronizado_em | timestamp | |

### `execucoes_coleta`
Uma linha por fonte a cada execução da coleta.

| Coluna | Tipo | Notas |
|---|---|---|
| id | INTEGER PK | |
| fonte | TEXT | |
| inicio | timestamp | |
| fim | timestamp | Opcional. |
| status | TEXT | `em_andamento`, `sucesso`, `parcial` ou `falha`. |
| registros_novos | INTEGER ≥ 0 | |
| erro | TEXT | |

Índice: `(fonte, inicio)`.

### `revisoes`
Guarda as correções que a fonte faz em dados já salvos. A coleta nunca sobrescreve em silêncio: quando um valor muda, a mudança fica registrada aqui.

| Coluna | Tipo | Notas |
|---|---|---|
| id | INTEGER PK | |
| tabela | TEXT | Ex.: `cotacoes`. |
| chave_registro | TEXT (JSON válido) | Ex.: `{"ticker":"PETR4","data":"2026-01-02","fonte":"brapi"}`. |
| campo | TEXT | |
| valor_antigo, valor_novo | TEXT | |
| fonte | TEXT | |
| detectado_em | timestamp | |

### `schema_versao`
O controle das migrações aplicadas: `versao` (PK) e `aplicada_em`.

## Como alterar o schema
1. Acrescente `(N+1, "SQL...")` ao fim de `MIGRACOES` em [src/db/migracoes.py](../src/db/migracoes.py).
2. Nunca edite uma migração que já foi aplicada.
3. Rode `python scripts/init_db.py`.

Cada migração roda numa transação: ou é aplicada inteira, ou não é aplicada.
