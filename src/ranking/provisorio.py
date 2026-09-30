"""Score PROVISÓRIO durante o pregão (regra 15).

Usa o modelo treinado no último ranking oficial (arquivo em data/modelos) e
monta as features de "hoje" com a cotação do momento:
- sinais técnicos recalculados com o preço atual como fechamento provisório
  (volume do dia ainda desconhecido: vol_fin_rel21 fica ausente);
- P/L, L/P e P/VP reescalados pela variação do preço desde o último fechamento;
- os demais sinais (margens, ROE, crescimento...) repetem os do último pregão.

Gravado na tabela `ranking` com versão `<modelo>-provisorio` e data de hoje.
À noite, o ranking oficial (dados da B3) é gerado normalmente e prevalece.
"""

import logging
import sqlite3
from datetime import date

import lightgbm as lgb
import pandas as pd

from config import settings
from src.ranking import dados, gerar
from src.db.tempo import agora_utc_iso, hoje_brt
from src.sinais import base, tecnicos

logger = logging.getLogger(__name__)

VERSAO = gerar.VERSAO_MODELO + "-provisorio"
PASTA_MODELOS = settings.BASE_DIR / "data" / "modelos"
JANELA_HISTORICO = 260  # pregões de histórico para os técnicos (MM200 + folga)


def carregar_ultimo_modelo(pasta=PASTA_MODELOS) -> tuple[lgb.Booster, str] | None:
    arquivos = sorted(pasta.glob(f"{gerar.VERSAO_MODELO}_*.txt"))
    if not arquivos:
        return None
    ultimo = arquivos[-1]
    # lê via Python: o LightGBM (C) não abre caminhos com acento no Windows
    return lgb.Booster(model_str=ultimo.read_text(encoding="utf-8")), ultimo.stem.split("_")[-1]


def features_provisorias(conn: sqlite3.Connection, hoje: date, colunas: list[str]) -> pd.DataFrame:
    """Features (em percentil do dia) do universo do último pregão, com a cotação do momento."""
    ultimo = conn.execute("SELECT MAX(data) FROM universo").fetchone()[0]
    universo = [r[0] for r in conn.execute("SELECT ticker FROM universo WHERE data = ?", (ultimo,))]
    atual = pd.read_sql_query("SELECT ticker, preco FROM cotacao_atual", conn).set_index("ticker")["preco"]
    anteriores = pd.read_sql_query(
        "SELECT ticker, valor, nome FROM sinais WHERE data = ?", conn, params=(ultimo,)
    ).pivot(index="ticker", columns="nome", values="valor").reindex(universo)

    cot = base.carregar_cotacoes(conn)
    prov = base.carregar_proventos(conn)
    cot = cot[cot["ticker"].isin(universo)]
    linhas = {}
    for ticker, c in cot.groupby("ticker"):
        c = c.tail(JANELA_HISTORICO)
        preco_ontem = c["fechamento"].iloc[-1]
        preco = atual.get(ticker)
        if preco is None or pd.isna(preco):
            continue
        nova = pd.DataFrame({"ticker": [ticker], "data": [pd.Timestamp(hoje)], "fechamento": [preco], "volume": [pd.NA]})
        s = tecnicos.sinais_ativo(pd.concat([c, nova], ignore_index=True), prov[prov["ticker"] == ticker])
        valores = anteriores.loc[ticker].copy() if ticker in anteriores.index else pd.Series(dtype=float)
        for nome in tecnicos.NOMES:
            valores[nome] = s[nome].iloc[-1]
        razao = preco / preco_ontem
        for nome, efeito in (("fund_pl", razao), ("fund_pvp", razao), ("fund_lp", 1 / razao)):
            if nome in valores and pd.notna(valores[nome]):
                valores[nome] = valores[nome] * efeito
        linhas[ticker] = valores
    matriz = pd.DataFrame(linhas).T.reindex(columns=colunas).astype(float)
    matriz.index = pd.MultiIndex.from_product([[pd.Timestamp(hoje)], matriz.index], names=["data", "ticker"])
    return matriz.groupby(level="data").rank(pct=True)


def gerar_provisorio(conn: sqlite3.Connection, hoje: date | None = None,
                     colunas: list[str] | None = None, modelo_carregado=None) -> gerar.RankingDoDia | None:
    colunas = colunas or dados.FEATURES_BASE
    hoje = hoje or hoje_brt()
    carregado = modelo_carregado or carregar_ultimo_modelo()
    if carregado is None:
        logger.warning("Sem modelo salvo: rode gerar_ranking.py (ou o pipeline noturno) antes")
        return None
    m, data_modelo = carregado if isinstance(carregado, tuple) else (carregado, "?")
    X = features_provisorias(conn, hoje, colunas)
    if X.empty:
        return None
    scores = X.reset_index()[["data", "ticker"]].assign(score=m.predict(X[colunas]))
    resultado = gerar.RankingDoDia(gerar.com_posicao(scores), pd.Series(dtype=float), gerar.fatores(m, X, colunas), m)
    gerar.gravar(conn, resultado.ranking, VERSAO, disponivel_em=agora_utc_iso())  # disponível agora, não às 19h
    gerar.gravar_fatores(conn, resultado.fatores, VERSAO)
    logger.info("Ranking provisório de %s: %d ações (modelo de %s)", hoje, len(resultado.ranking), data_modelo)
    return resultado
