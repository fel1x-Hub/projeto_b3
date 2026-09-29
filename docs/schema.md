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
| fechamento_ajustado | REAL > 0 | Ajustado por proventos e desdobramentos; é a base dos retornos na etapa 3. |
| volume | INTEGER ≥ 0 | Quantidade negociada. |
| fonte | TEXT | brapi, yfinance... |
| disponivel_em, coletado_em | timestamp | |

Chave única: `(ticker, data, fonte)`. As duas fontes podem guardar o mesmo pregão lado a lado, e quem consome escolhe a preferida.

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
| tipo | TEXT | Ex.: `fato_relevante`, `itr`, `dfp`. |
| ticker | FK → ativos | Opcional (documento ainda não mapeado). |
| data_referencia | data | Opcional (ex.: fim do trimestre). |
| fonte | TEXT | |
| id_externo | TEXT NOT NULL | Identificador na fonte (ex.: protocolo CVM). |
| url, conteudo, caminho_arquivo | TEXT | Pelo menos um dos três é obrigatório. |
| hash_conteudo | TEXT | Detecta quando o conteúdo muda. |
| disponivel_em | timestamp | Data/hora de entrega ou divulgação. |
| coletado_em | timestamp | |

Chave única: `(fonte, id_externo)`. Índice: `(ticker, disponivel_em)`.

Se os dados estruturados da CVM (as contas de DFP/ITR) pedirem uma tabela própria, ela entra como uma nova migração na etapa 2.

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
