"""SQL do schema. Documentação completa em docs/schema.md.

Convenções (valem para todas as tabelas):
- Datas de referência: TEXT 'YYYY-MM-DD', validadas com `x IS date(x)`.
- Timestamps: TEXT ISO-8601 em UTC, formato único (ver src/db/tempo.py),
  validados com GLOB, para que comparar texto equivalha a comparar instantes.
- `disponivel_em` = quando a informação ficou pública. Nenhum cálculo pode usar
  linha com `disponivel_em` posterior à data analisada (anti look-ahead).
- `coletado_em` = quando o sistema baixou o dado (auditoria).
- Chaves únicas impedem duplicatas; a coleta faz INSERT ... ON CONFLICT.
"""

_TS_GLOB = "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]+00:00"


def _ts(coluna: str, obrigatorio: bool = True) -> str:
    """Definição de coluna de timestamp UTC com validação de formato."""
    if obrigatorio:
        return f"{coluna} TEXT NOT NULL CHECK ({coluna} GLOB '{_TS_GLOB}')"
    return f"{coluna} TEXT CHECK ({coluna} IS NULL OR {coluna} GLOB '{_TS_GLOB}')"


def _data(coluna: str, obrigatorio: bool = True) -> str:
    """Definição de coluna de data (YYYY-MM-DD) com validação.

    Usa IS e não '=': date() devolve NULL para texto inválido, e um CHECK que
    resulta em NULL é considerado aprovado pelo SQLite.
    """
    nulo = "NOT NULL " if obrigatorio else ""
    return f"{coluna} TEXT {nulo}CHECK ({coluna} IS date({coluna}))"


SCHEMA_V1 = f"""
-- Universo de papéis acompanhados. Linhas nunca são apagadas (preserva o
-- histórico ligado ao ticker); para parar de acompanhar, ativo = 0.
CREATE TABLE ativos (
    ticker        TEXT PRIMARY KEY,          -- código de negociação B3 (ex: PETR4)
    nome          TEXT NOT NULL,
    setor         TEXT,
    cnpj          TEXT,                      -- preenchido pela etapa 2 (cadastro CVM)
    codigo_cvm    TEXT,                      -- liga documentos da CVM ao ticker
    ativo         INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1)),
    {_ts("criado_em")},
    {_ts("atualizado_em")}
);

-- Cotações diárias. Uma linha por (ticker, pregão, fonte): brapi e yfinance
-- convivem; quem consome escolhe a fonte preferida.
CREATE TABLE cotacoes (
    id                  INTEGER PRIMARY KEY,
    ticker              TEXT NOT NULL REFERENCES ativos (ticker),
    {_data("data")},                         -- data do pregão
    abertura            REAL CHECK (abertura > 0),
    maxima              REAL CHECK (maxima > 0),
    minima              REAL CHECK (minima > 0),
    fechamento          REAL NOT NULL CHECK (fechamento > 0),
    fechamento_ajustado REAL CHECK (fechamento_ajustado > 0),  -- por proventos/desdobramentos
    volume              INTEGER CHECK (volume >= 0),
    fonte               TEXT NOT NULL,
    {_ts("disponivel_em")},                  -- fim do pregão do dia
    {_ts("coletado_em")},
    UNIQUE (ticker, data, fonte)
);

-- Séries macroeconômicas (Selic, IPCA, câmbio...). `data` é a data de
-- referência; `disponivel_em` é a data de divulgação (IPCA de março sai em abril).
CREATE TABLE macro (
    id            INTEGER PRIMARY KEY,
    serie         TEXT NOT NULL,             -- nome interno da série (ex: ipca)
    {_data("data")},
    valor         REAL NOT NULL,
    fonte         TEXT NOT NULL,
    {_ts("disponivel_em")},
    {_ts("coletado_em")},
    UNIQUE (serie, data, fonte)
);

-- Notícias. Deduplicação por hash (título normalizado + fonte) e por URL.
CREATE TABLE noticias (
    id            INTEGER PRIMARY KEY,
    titulo        TEXT NOT NULL,
    resumo        TEXT,
    url           TEXT UNIQUE,
    fonte         TEXT NOT NULL,
    {_ts("publicado_em", obrigatorio=False)},
    {_ts("disponivel_em")},
    {_ts("coletado_em")},
    hash          TEXT NOT NULL UNIQUE
);
CREATE INDEX idx_noticias_disponivel_em ON noticias (disponivel_em);

-- Relação notícia <-> ativo. `metodo` registra como a associação foi feita
-- (ex: ticker_no_texto, nome_no_texto) para avaliar a qualidade depois.
CREATE TABLE noticias_ativos (
    noticia_id    INTEGER NOT NULL REFERENCES noticias (id) ON DELETE CASCADE,
    ticker        TEXT NOT NULL REFERENCES ativos (ticker),
    metodo        TEXT NOT NULL,
    PRIMARY KEY (noticia_id, ticker)
);
CREATE INDEX idx_noticias_ativos_ticker ON noticias_ativos (ticker);

-- Documentos (fatos relevantes, ITR, DFP, releases). `id_externo` é o
-- identificador na fonte (ex: protocolo CVM). Precisa de ao menos uma forma
-- de chegar ao conteúdo: texto, arquivo local ou URL.
CREATE TABLE documentos (
    id              INTEGER PRIMARY KEY,
    tipo            TEXT NOT NULL,
    ticker          TEXT REFERENCES ativos (ticker),
    {_data("data_referencia", obrigatorio=False)},
    fonte           TEXT NOT NULL,
    id_externo      TEXT NOT NULL,
    url             TEXT,
    conteudo        TEXT,
    caminho_arquivo TEXT,
    hash_conteudo   TEXT,
    {_ts("disponivel_em")},                  -- data/hora de entrega/divulgação
    {_ts("coletado_em")},
    UNIQUE (fonte, id_externo),
    CHECK (conteudo IS NOT NULL OR caminho_arquivo IS NOT NULL OR url IS NOT NULL)
);
CREATE INDEX idx_documentos_ticker_disponivel ON documentos (ticker, disponivel_em);

-- Registro de cada execução de coleta (uma linha por fonte por execução).
CREATE TABLE execucoes_coleta (
    id              INTEGER PRIMARY KEY,
    fonte           TEXT NOT NULL,
    {_ts("inicio")},
    {_ts("fim", obrigatorio=False)},
    status          TEXT NOT NULL CHECK (status IN ('em_andamento', 'sucesso', 'parcial', 'falha')),
    registros_novos INTEGER NOT NULL DEFAULT 0 CHECK (registros_novos >= 0),
    erro            TEXT
);
CREATE INDEX idx_execucoes_fonte_inicio ON execucoes_coleta (fonte, inicio);

-- Correções feitas pela fonte em dados já salvos. A coleta nunca sobrescreve
-- em silêncio: grava aqui o valor antigo e o novo.
CREATE TABLE revisoes (
    id              INTEGER PRIMARY KEY,
    tabela          TEXT NOT NULL,
    chave_registro  TEXT NOT NULL CHECK (json_valid(chave_registro)),  -- ex: {{"ticker":"PETR4","data":"2026-01-02","fonte":"brapi"}}
    campo           TEXT NOT NULL,
    valor_antigo    TEXT,
    valor_novo      TEXT,
    fonte           TEXT,
    {_ts("detectado_em")}
);
"""
