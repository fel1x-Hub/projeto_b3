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


SCHEMA_V5 = f"""
-- Universo ampliado (decisão de 30/09/2026): a maior parte da B3.
-- origem: 'manual' = veio de config/ativos.csv (lista de exceções);
--         'auto'   = detectado nos arquivos da B3 (ação ou unit em lote padrão).
ALTER TABLE ativos ADD COLUMN origem TEXT NOT NULL DEFAULT 'manual' CHECK (origem IN ('manual', 'auto'));

-- Universo ponto-no-tempo: quem estava apto a entrar no ranking em cada pregão.
-- Critério: volume financeiro médio >= R$ 100 mil/dia nos últimos 63 pregões
-- do mercado (dia sem negócio conta como zero), usando só dados até o corte
-- do dia; ou inclusão manual pelo ativos.csv. Empresas que saíram da bolsa
-- continuam no histórico (sem viés de sobrevivência).
CREATE TABLE universo (
    {_data("data")},
    ticker          TEXT NOT NULL REFERENCES ativos (ticker),
    volume_medio    REAL,
    motivo          TEXT NOT NULL CHECK (motivo IN ('liquidez', 'manual')),
    {_ts("disponivel_em")},
    PRIMARY KEY (data, ticker)
);
CREATE INDEX idx_universo_ticker ON universo (ticker, data);
"""


SCHEMA_V6 = f"""
-- Ranking diário (etapa 4). versao_modelo identifica o modelo e a forma de
-- geração: 'wf-...' = previsão fora da amostra do walk-forward (histórico
-- para avaliação/backtest); demais = gerado por scripts/gerar_ranking.py.
-- posicao 1 = mais atrativo. disponivel_em = corte do pregão (dados até ele).
CREATE TABLE ranking (
    {_data("data")},
    ticker          TEXT NOT NULL REFERENCES ativos (ticker),
    score           REAL NOT NULL,
    posicao         INTEGER NOT NULL CHECK (posicao >= 1),
    versao_modelo   TEXT NOT NULL,
    {_ts("disponivel_em")},
    {_ts("calculado_em")},
    PRIMARY KEY (data, ticker, versao_modelo)
);
CREATE INDEX idx_ranking_versao_data ON ranking (versao_modelo, data, posicao);
"""


SCHEMA_V7 = f"""
-- Paper trading (etapa 5.2): a regra da carteira aplicada daqui para a frente,
-- com o ranking gerado a cada dia só com os dados daquele dia. Nenhuma ordem
-- real é enviada; é só registro.
CREATE TABLE paper_config (
    chave         TEXT PRIMARY KEY,         -- ex.: 'inicio' (data do primeiro ranking do paper trading)
    valor         TEXT NOT NULL
);
CREATE TABLE paper_carteira (
    {_data("data_execucao")},             -- fechamento em que a carteira foi montada
    ticker        TEXT NOT NULL REFERENCES ativos (ticker),
    peso_alvo     REAL NOT NULL CHECK (peso_alvo > 0 AND peso_alvo <= 1),
    {_data("data_ranking")},              -- ranking que originou a decisão
    PRIMARY KEY (data_execucao, ticker)
);
CREATE TABLE paper_patrimonio (
    {_data("data")},
    valor         REAL NOT NULL,            -- começa em 1
    retorno       REAL NOT NULL,            -- do dia, líquido de custos
    custo         REAL NOT NULL DEFAULT 0,  -- custo de rebalanceamento cobrado no dia
    {_ts("calculado_em")},
    PRIMARY KEY (data)
);
"""


SCHEMA_V8 = f"""
-- Por que cada ação ficou onde ficou no ranking (etapa 6, regra 16): os sinais
-- que mais pesaram para ela, com o percentil do sinal no dia e a contribuição
-- ao score (valores SHAP do LightGBM). Base das explicações no app e no relatório.
CREATE TABLE ranking_fatores (
    {_data("data")},
    ticker          TEXT NOT NULL REFERENCES ativos (ticker),
    versao_modelo   TEXT NOT NULL,
    sinal           TEXT NOT NULL,
    percentil       REAL,                    -- posição do sinal da ação no universo do dia (0 a 1)
    contribuicao    REAL NOT NULL,           -- efeito no score (positivo = ajudou a subir)
    PRIMARY KEY (data, ticker, versao_modelo, sinal)
);

-- Cotação do momento (ciclo intradiário, regra 15). Uma linha por papel,
-- substituída a cada ciclo. É PROVISÓRIA: o dado oficial é o arquivo da B3
-- da noite, que vai para `cotacoes`. Não tem FK porque inclui índices (ex.: IBOV).
CREATE TABLE cotacao_atual (
    ticker            TEXT PRIMARY KEY,
    preco             REAL NOT NULL CHECK (preco > 0),
    fechamento_anterior REAL,
    variacao_dia      REAL,
    {_ts("horario_cotacao")},                 -- horário da última negociação na fonte
    fonte             TEXT NOT NULL,
    {_ts("coletado_em")}
);
"""


SCHEMA_V9 = f"""
-- Carteira real do usuário (etapa 7, regras 11 e 16). A posição nunca é
-- gravada: é recalculada das operações. `ticker` sem FK porque a carteira
-- pode ter papéis fora do universo do modelo (FII, ETF, BDR...).
-- `referencia` identifica a linha de origem de uma importação (hash do
-- arquivo + linha), para reimportar o mesmo extrato sem duplicar.
CREATE TABLE carteira_operacoes (
    id            INTEGER PRIMARY KEY,
    ticker        TEXT NOT NULL CHECK (ticker GLOB '[A-Z][A-Z0-9][A-Z0-9][A-Z0-9]*'),
    tipo          TEXT NOT NULL CHECK (tipo IN ('compra', 'venda')),
    {_data("data")},
    quantidade    REAL NOT NULL CHECK (quantidade > 0),
    preco         REAL NOT NULL CHECK (preco > 0),
    custos        REAL NOT NULL DEFAULT 0 CHECK (custos >= 0),   -- corretagem + emolumentos
    origem        TEXT NOT NULL CHECK (origem IN ('manual', 'importacao')),
    referencia    TEXT UNIQUE,
    {_ts("criado_em")}
);
CREATE INDEX idx_carteira_operacoes_ticker ON carteira_operacoes (ticker, data);

-- Foto das posições sincronizadas da corretora (Meu Pluggy / Open Finance).
-- Substituída a cada sincronização; a instituição atualiza ~1 vez por dia.
CREATE TABLE carteira_sincronizada (
    ticker          TEXT PRIMARY KEY,
    quantidade      REAL NOT NULL CHECK (quantidade >= 0),
    valor_aplicado  REAL,                        -- custo informado pela corretora, se houver
    valor_corretora REAL,                        -- valor de mercado segundo a corretora
    instituicao     TEXT NOT NULL,
    {_ts("data_corretora", obrigatorio=False)},  -- data de referência do dado na corretora
    {_ts("sincronizado_em")}
);
"""


SCHEMA_V10 = f"""
-- Relatório diário em Markdown (etapa 8): a API lê daqui, e não da pasta
-- relatorios/, para funcionar igual na nuvem (onde não há pasta). Os arquivos
-- continuam sendo gravados para leitura direta.
CREATE TABLE relatorios (
    {_data("data")} PRIMARY KEY,
    markdown      TEXT NOT NULL,
    {_ts("gerado_em")}
);
"""


SCHEMA_V11 = f"""
-- Login por usuário e senha (etapa 8). Só o hash PBKDF2 da senha, nunca o texto.
CREATE TABLE usuarios (
    usuario       TEXT PRIMARY KEY,          -- normalizado (minúsculas, espaços simples)
    senha_hash    TEXT NOT NULL,
    {_ts("criado_em")}
);
"""


SCHEMA_V12 = f"""
-- Previsões calibradas no histórico fora da amostra (scripts/calibrar.py):
-- o que aconteceu, por faixa de pontuação de compra e prazo. Não é promessa.
CREATE TABLE calibracao (
    versao_modelo   TEXT NOT NULL,
    horizonte       INTEGER NOT NULL,           -- pregões (21, 126, 252)
    prazo           TEXT NOT NULL,
    faixa_min       INTEGER NOT NULL,           -- pontuação de compra (0, 10, ..., 90)
    faixa_max       INTEGER NOT NULL,
    n               INTEGER NOT NULL,
    janelas_independentes INTEGER NOT NULL,
    retorno_medio   REAL, retorno_mediano REAL, p25 REAL, p75 REAL,
    excesso_medio   REAL,                       -- contra o BOVA11 no mesmo período
    chance_superar  REAL,
    t               REAL,
    sinal           TEXT NOT NULL,
    comportamento   TEXT NOT NULL,
    {_data("periodo_inicio")}, {_data("periodo_fim")},
    {_ts("calculado_em")},
    PRIMARY KEY (versao_modelo, horizonte, faixa_min)
);
-- Efeito histórico de cada padrão gráfico (medido antes de ser mostrado).
CREATE TABLE padroes_efeito (
    padrao          TEXT NOT NULL,
    horizonte       INTEGER NOT NULL,
    n               INTEGER NOT NULL,
    excesso_medio   REAL, chance_superar REAL, t REAL,
    conclusao       TEXT NOT NULL,
    {_data("periodo_inicio")}, {_data("periodo_fim")},
    {_ts("calculado_em")},
    PRIMARY KEY (padrao, horizonte)
);
"""


SCHEMA_V13 = f"""
-- Nota de venda por "chance de cair" (docs/venda.md).
CREATE TABLE venda (
    {_data("data")},
    ticker          TEXT NOT NULL,
    versao          TEXT NOT NULL,
    prob            REAL NOT NULL,              -- probabilidade do modelo (bruta)
    chance_cair     REAL,                       -- calibrada: taxa de queda observada em casos parecidos
    nota            INTEGER NOT NULL,           -- 0–100 (100 = maior chance de queda do universo no dia)
    {_ts("disponivel_em")},
    PRIMARY KEY (data, ticker, versao)
);
CREATE TABLE venda_calibracao (
    versao          TEXT NOT NULL,
    fonte           TEXT NOT NULL CHECK (fonte IN ('modelo', 'nota_atual')),
    ordem           INTEGER NOT NULL,
    prob_min        REAL NOT NULL, prob_max REAL NOT NULL, prob_media REAL NOT NULL,
    taxa_real       REAL NOT NULL,
    n               INTEGER NOT NULL,
    {_ts("calculado_em")},
    PRIMARY KEY (versao, ordem)
);
"""
