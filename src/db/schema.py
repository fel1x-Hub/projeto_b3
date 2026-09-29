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


SCHEMA_V2 = f"""
-- Termos para achar a empresa em notícias (separados por '|'; vazio = usa o nome)
-- e tipo do papel: 'benchmark' (ex: BOVA11) é coletado mas não entra no ranking.
ALTER TABLE ativos ADD COLUMN apelidos TEXT;
ALTER TABLE ativos ADD COLUMN tipo TEXT NOT NULL DEFAULT 'acao' CHECK (tipo IN ('acao', 'benchmark'));

-- Proventos, usados para ajustar os preços brutos da B3 (etapa 3).
-- dividendo: `valor` em R$ por ação (JCP incluso; eventos na mesma data vêm somados).
-- desdobramento: `fator` = ações novas por ação antiga (2 = desdobramento 2:1;
-- 0.1 = grupamento 10:1). Valores do Yahoo já vêm na escala de ações atual.
CREATE TABLE proventos (
    id            INTEGER PRIMARY KEY,
    ticker        TEXT NOT NULL REFERENCES ativos (ticker),
    tipo          TEXT NOT NULL CHECK (tipo IN ('dividendo', 'desdobramento')),
    {_data("data_ex")},
    valor         REAL,
    fator         REAL,
    fonte         TEXT NOT NULL,
    {_ts("disponivel_em")},
    {_ts("coletado_em")},
    UNIQUE (ticker, fonte, tipo, data_ex),
    -- COALESCE(... , 0): sem ele, valor NULL tornaria o CHECK NULL, e o SQLite aprova
    CHECK ((tipo = 'dividendo' AND COALESCE(valor > 0, 0) AND fator IS NULL)
        OR (tipo = 'desdobramento' AND COALESCE(fator > 0, 0) AND valor IS NULL))
);

-- Demonstrações financeiras da CVM (DFP anual e ITR trimestral), formato longo:
-- uma linha por conta. Todas as versões (reapresentações) são guardadas; cada
-- uma vale a partir do seu `disponivel_em` (data de entrega), o que permite
-- reconstruir o que se sabia em cada data. `valor` já está em reais.
-- demonstrativo 'CAPITAL' guarda a composição do capital (número de ações).
CREATE TABLE demonstracoes (
    id              INTEGER PRIMARY KEY,
    codigo_cvm      TEXT NOT NULL,
    tipo_doc        TEXT NOT NULL CHECK (tipo_doc IN ('DFP', 'ITR')),
    {_data("data_referencia")},
    versao          INTEGER NOT NULL,
    demonstrativo   TEXT NOT NULL,           -- BPA, BPP, DRE, DFC_MD, DFC_MI, DVA, CAPITAL
    consolidado     INTEGER NOT NULL CHECK (consolidado IN (0, 1)),
    {_data("data_ini", obrigatorio=False)},  -- início do período (vazio em balanço)
    {_data("data_fim", obrigatorio=False)},  -- fim do período / data do balanço
    cd_conta        TEXT NOT NULL,
    ds_conta        TEXT,
    valor           REAL,
    {_ts("disponivel_em")},
    {_ts("coletado_em")}
);
-- COALESCE porque, no SQLite, NULLs são sempre distintos em índices únicos.
CREATE UNIQUE INDEX uq_demonstracoes ON demonstracoes (
    codigo_cvm, tipo_doc, data_referencia, versao, demonstrativo, consolidado,
    cd_conta, COALESCE(data_ini, ''), COALESCE(data_fim, '')
);
CREATE INDEX idx_demonstracoes_documento ON demonstracoes (
    codigo_cvm, tipo_doc, data_referencia, versao, demonstrativo, consolidado, cd_conta
);
CREATE INDEX idx_demonstracoes_cia_disponivel ON demonstracoes (codigo_cvm, disponivel_em);
"""


SCHEMA_V3 = """
-- Assunto informado pela empresa na entrega (ex: "Relatório de Produção 4T25").
-- Resume o documento sem precisar baixar o PDF; útil para o LLM na etapa 3.
ALTER TABLE documentos ADD COLUMN assunto TEXT;
"""


SCHEMA_V4 = f"""
-- Sinais por ativo e pregão, em formato LONGO (um valor por linha).
-- Por que longo: sinal novo não exige migração, cobertura/faltantes saem de uma
-- consulta, e a etapa 4 pivota para colunas. Valor ausente = linha ausente.
-- `disponivel_em` = corte usado no cálculo (pregão às 19h BRT): o sinal só usa
-- dados com disponivel_em <= esse corte. `versao` muda quando a fórmula muda.
CREATE TABLE sinais (
    id            INTEGER PRIMARY KEY,
    ticker        TEXT NOT NULL REFERENCES ativos (ticker),
    {_data("data")},
    nome          TEXT NOT NULL,
    valor         REAL NOT NULL,
    versao        INTEGER NOT NULL,
    {_ts("disponivel_em")},
    {_ts("calculado_em")},
    UNIQUE (ticker, data, nome, versao)
);
CREATE INDEX idx_sinais_nome_data ON sinais (nome, data);

-- Sentimento de cada notícia, por modelo. score = P(positivo) - P(negativo).
CREATE TABLE sentimento_noticias (
    noticia_id    INTEGER NOT NULL REFERENCES noticias (id) ON DELETE CASCADE,
    modelo        TEXT NOT NULL,
    rotulo        TEXT NOT NULL CHECK (rotulo IN ('positivo', 'neutro', 'negativo')),
    prob_positivo REAL NOT NULL,
    prob_neutro   REAL NOT NULL,
    prob_negativo REAL NOT NULL,
    score         REAL NOT NULL,
    {_ts("calculado_em")},
    PRIMARY KEY (noticia_id, modelo)
);

-- Eventos extraídos de documentos da CVM por LLM (etapa 3.4). O LLM só
-- classifica e resume; nenhum número é calculado por ele.
CREATE TABLE eventos_documentos (
    documento_id  INTEGER NOT NULL REFERENCES documentos (id) ON DELETE CASCADE,
    modelo        TEXT NOT NULL,
    versao_prompt INTEGER NOT NULL,
    tipo_evento   TEXT NOT NULL,
    direcao       TEXT NOT NULL CHECK (direcao IN ('positiva', 'neutra', 'negativa')),
    relevancia    INTEGER NOT NULL CHECK (relevancia BETWEEN 1 AND 5),
    resumo        TEXT NOT NULL,
    {_ts("calculado_em")},
    PRIMARY KEY (documento_id, modelo, versao_prompt)
);

-- Cache de respostas do LLM: mesma entrada + modelo + versão do prompt nunca
-- é processada duas vezes. `chave` = sha256 desses três.
CREATE TABLE llm_cache (
    chave         TEXT PRIMARY KEY,
    modelo        TEXT NOT NULL,
    versao_prompt INTEGER NOT NULL,
    resposta      TEXT NOT NULL CHECK (json_valid(resposta)),
    {_ts("criado_em")}
);

-- Respostas inválidas (fora do schema) ou falhas, para auditoria.
CREATE TABLE llm_erros (
    id             INTEGER PRIMARY KEY,
    documento_id   INTEGER REFERENCES documentos (id) ON DELETE CASCADE,
    modelo         TEXT NOT NULL,
    versao_prompt  INTEGER NOT NULL,
    erro           TEXT NOT NULL,
    resposta_bruta TEXT,
    {_ts("ocorrido_em")}
);
"""
