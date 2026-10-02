"""Esquema do Postgres na nuvem (Neon, 0,5 GB grátis) — etapa 8.

Só o "modelo de leitura" que a API consulta, mais a carteira e os relatórios.
As colunas e nomes são os mesmos do SQLite (o mesmo SQL da API roda nos dois).
Tabelas de mercado são espelhadas pelo pipeline (scripts/publicar_nuvem.py);
`carteira_*` só é escrita pela API (e pela sincronização com a XP) e NUNCA sai
da nuvem para o repositório público.

Idempotente: `garantir(conn)` cria o que faltar. Mudanças futuras: acrescentar
ALTER TABLE ... ADD COLUMN IF NOT EXISTS no fim de SQL.
"""

SQL = """
CREATE TABLE IF NOT EXISTS ativos (
    ticker TEXT PRIMARY KEY, nome TEXT NOT NULL, setor TEXT, cnpj TEXT, codigo_cvm TEXT,
    ativo INTEGER NOT NULL DEFAULT 1);

CREATE TABLE IF NOT EXISTS cotacoes (
    ticker TEXT NOT NULL, data TEXT NOT NULL, abertura DOUBLE PRECISION, maxima DOUBLE PRECISION,
    minima DOUBLE PRECISION, fechamento DOUBLE PRECISION NOT NULL, volume BIGINT,
    PRIMARY KEY (ticker, data));
CREATE INDEX IF NOT EXISTS idx_cotacoes_data ON cotacoes (data);

CREATE TABLE IF NOT EXISTS macro (
    serie TEXT NOT NULL, data TEXT NOT NULL, valor DOUBLE PRECISION NOT NULL, disponivel_em TEXT NOT NULL,
    PRIMARY KEY (serie, data));

CREATE TABLE IF NOT EXISTS proventos (
    ticker TEXT NOT NULL, tipo TEXT NOT NULL, data_ex TEXT NOT NULL, valor DOUBLE PRECISION, fator DOUBLE PRECISION,
    fonte TEXT NOT NULL, PRIMARY KEY (ticker, fonte, tipo, data_ex));

CREATE TABLE IF NOT EXISTS universo (
    data TEXT NOT NULL, ticker TEXT NOT NULL, PRIMARY KEY (data, ticker));

CREATE TABLE IF NOT EXISTS sinais (
    ticker TEXT NOT NULL, data TEXT NOT NULL, nome TEXT NOT NULL, valor DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (ticker, data, nome));
CREATE INDEX IF NOT EXISTS idx_sinais_nome_data ON sinais (nome, data);

CREATE TABLE IF NOT EXISTS ranking (
    data TEXT NOT NULL, ticker TEXT NOT NULL, score DOUBLE PRECISION NOT NULL, posicao INTEGER NOT NULL,
    versao_modelo TEXT NOT NULL, disponivel_em TEXT NOT NULL, calculado_em TEXT NOT NULL,
    PRIMARY KEY (data, ticker, versao_modelo));
CREATE INDEX IF NOT EXISTS idx_ranking_versao_data ON ranking (versao_modelo, data, posicao);
CREATE INDEX IF NOT EXISTS idx_ranking_ticker ON ranking (ticker, versao_modelo, data);

CREATE TABLE IF NOT EXISTS ranking_fatores (
    data TEXT NOT NULL, ticker TEXT NOT NULL, versao_modelo TEXT NOT NULL, sinal TEXT NOT NULL,
    percentil DOUBLE PRECISION, contribuicao DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (data, ticker, versao_modelo, sinal));

CREATE TABLE IF NOT EXISTS cotacao_atual (
    ticker TEXT PRIMARY KEY, preco DOUBLE PRECISION NOT NULL, fechamento_anterior DOUBLE PRECISION,
    variacao_dia DOUBLE PRECISION, horario_cotacao TEXT NOT NULL, fonte TEXT NOT NULL, coletado_em TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS noticias (
    id BIGINT PRIMARY KEY, titulo TEXT NOT NULL, url TEXT, fonte TEXT NOT NULL, disponivel_em TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_noticias_disponivel ON noticias (disponivel_em);
CREATE TABLE IF NOT EXISTS noticias_ativos (
    noticia_id BIGINT NOT NULL, ticker TEXT NOT NULL, PRIMARY KEY (noticia_id, ticker));
CREATE INDEX IF NOT EXISTS idx_noticias_ativos_ticker ON noticias_ativos (ticker);
CREATE TABLE IF NOT EXISTS sentimento_noticias (
    noticia_id BIGINT NOT NULL, modelo TEXT NOT NULL, score DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (noticia_id, modelo));

CREATE TABLE IF NOT EXISTS documentos (
    id BIGINT PRIMARY KEY, tipo TEXT NOT NULL, ticker TEXT, assunto TEXT, url TEXT, disponivel_em TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_documentos_ticker ON documentos (ticker, disponivel_em);
CREATE TABLE IF NOT EXISTS eventos_documentos (
    documento_id BIGINT NOT NULL, modelo TEXT NOT NULL, versao_prompt INTEGER NOT NULL, tipo_evento TEXT NOT NULL,
    direcao TEXT NOT NULL, resumo TEXT NOT NULL, PRIMARY KEY (documento_id, modelo, versao_prompt));

CREATE TABLE IF NOT EXISTS execucoes_coleta (
    id BIGINT PRIMARY KEY, fonte TEXT NOT NULL, inicio TEXT NOT NULL, fim TEXT, status TEXT NOT NULL,
    registros_novos INTEGER, erro TEXT);

CREATE TABLE IF NOT EXISTS relatorios (
    data TEXT PRIMARY KEY, markdown TEXT NOT NULL, gerado_em TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS publicacoes (
    tabela TEXT PRIMARY KEY, publicado_em TEXT NOT NULL, linhas INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS calibracao (
    versao_modelo TEXT NOT NULL, horizonte INTEGER NOT NULL, prazo TEXT NOT NULL, faixa_min INTEGER NOT NULL,
    faixa_max INTEGER NOT NULL, n INTEGER NOT NULL, janelas_independentes INTEGER NOT NULL,
    retorno_medio DOUBLE PRECISION, retorno_mediano DOUBLE PRECISION, p25 DOUBLE PRECISION, p75 DOUBLE PRECISION,
    excesso_medio DOUBLE PRECISION, chance_superar DOUBLE PRECISION, t DOUBLE PRECISION, sinal TEXT NOT NULL,
    comportamento TEXT NOT NULL, periodo_inicio TEXT NOT NULL, periodo_fim TEXT NOT NULL, calculado_em TEXT NOT NULL,
    PRIMARY KEY (versao_modelo, horizonte, faixa_min));
CREATE TABLE IF NOT EXISTS padroes_efeito (
    padrao TEXT NOT NULL, horizonte INTEGER NOT NULL, n INTEGER NOT NULL, excesso_medio DOUBLE PRECISION,
    chance_superar DOUBLE PRECISION, t DOUBLE PRECISION, conclusao TEXT NOT NULL, periodo_inicio TEXT NOT NULL,
    periodo_fim TEXT NOT NULL, calculado_em TEXT NOT NULL, PRIMARY KEY (padrao, horizonte));

CREATE TABLE IF NOT EXISTS usuarios (
    usuario TEXT PRIMARY KEY, senha_hash TEXT NOT NULL, criado_em TEXT NOT NULL);

-- Só a API escreve aqui (dados pessoais: nunca vão para o repositório público)
CREATE TABLE IF NOT EXISTS carteira_operacoes (
    id BIGSERIAL PRIMARY KEY, ticker TEXT NOT NULL, tipo TEXT NOT NULL CHECK (tipo IN ('compra', 'venda')),
    data TEXT NOT NULL, quantidade DOUBLE PRECISION NOT NULL CHECK (quantidade > 0),
    preco DOUBLE PRECISION NOT NULL CHECK (preco > 0), custos DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (custos >= 0),
    origem TEXT NOT NULL CHECK (origem IN ('manual', 'importacao')), referencia TEXT UNIQUE, criado_em TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS carteira_sincronizada (
    ticker TEXT PRIMARY KEY, quantidade DOUBLE PRECISION NOT NULL, valor_aplicado DOUBLE PRECISION,
    valor_corretora DOUBLE PRECISION, instituicao TEXT NOT NULL, data_corretora TEXT, sincronizado_em TEXT NOT NULL);
"""


def garantir(conn) -> None:
    """Cria as tabelas que faltarem (conn = ConexaoPG ou psycopg com autocommit)."""
    for comando in (c.strip() for c in SQL.split(";")):
        if comando and not all(l.strip().startswith("--") for l in comando.splitlines() if l.strip()):
            conn.execute(comando)
