"""Universo ponto-no-tempo: quais papéis estavam aptos a entrar no ranking em
cada pregão (decisão do usuário, 30/09/2026).

Critério para o pregão D, usando só cotações com disponivel_em <= corte(D):
- ação ou unit (tipo 'acao') não excluída no ativos.csv;
- volume financeiro médio >= R$ 100 mil/dia nos últimos 63 pregões do
  mercado (dia sem negócio conta como zero; mínimo de 21 pregões de histórico);
- ou inclusão manual no ativos.csv (motivo 'manual'), a partir da 1ª cotação.

Volume financeiro = quantidade x preço de fechamento (aproximação do volume
financeiro exato do arquivo da B3, suficiente para um filtro de liquidez).
Empresas que saíram da bolsa continuam no histórico: sem viés de sobrevivência.
"""

import logging
import sqlite3

import pandas as pd

from src.sinais import base

logger = logging.getLogger(__name__)

VOLUME_MINIMO = 100_000.0
JANELA, MINIMO_PREGOES = 63, 21


def calcular(conn: sqlite3.Connection, ate: str | None = None) -> pd.DataFrame:
    """Colunas: data, ticker, volume_medio, motivo."""
    cotacoes = base.carregar_cotacoes(conn, ate)
    ativos = pd.read_sql_query("SELECT ticker, origem FROM ativos WHERE ativo = 1 AND tipo = 'acao'", conn)
    vazio = pd.DataFrame(columns=["data", "ticker", "volume_medio", "motivo"])
    if cotacoes.empty or ativos.empty:
        return vazio
    calendario = pd.DatetimeIndex(sorted(cotacoes["data"].unique()))  # pregões do mercado
    acoes = cotacoes[cotacoes["ticker"].isin(ativos["ticker"])]
    financeiro = (acoes.assign(vf=acoes["volume"] * acoes["fechamento"])
                  .pivot_table(index="data", columns="ticker", values="vf", aggfunc="sum")
                  .reindex(calendario).fillna(0.0))
    media = financeiro.rolling(JANELA, min_periods=MINIMO_PREGOES).mean()

    longo = media.stack().rename("volume_medio").reset_index()
    longo.columns = ["data", "ticker", "volume_medio"]
    liquidos = longo[longo["volume_medio"] >= VOLUME_MINIMO].assign(motivo="liquidez")

    manuais = set(ativos.loc[ativos["origem"] == "manual", "ticker"])
    primeira = acoes[acoes["ticker"].isin(manuais)].groupby("ticker")["data"].min()
    partes = [liquidos]
    if not primeira.empty:
        forcados = longo[longo["ticker"].isin(primeira.index)]
        forcados = forcados[forcados["data"] >= forcados["ticker"].map(primeira)]
        forcados = forcados.merge(liquidos[["data", "ticker"]], how="left", indicator=True)
        partes.append(forcados[forcados["_merge"] == "left_only"].drop(columns="_merge").assign(motivo="manual"))

    resultado = pd.concat(partes, ignore_index=True)
    return resultado.sort_values(["data", "ticker"]).reset_index(drop=True)[["data", "ticker", "volume_medio", "motivo"]]


def gravar(conn: sqlite3.Connection, universo: pd.DataFrame) -> int:
    """Substitui a tabela `universo` inteira (dado derivado, recalculável)."""
    linhas = [(r.data.date().isoformat(), r.ticker, float(r.volume_medio), r.motivo, base.corte(r.data.date()))
              for r in universo.itertuples(index=False)]
    with conn:
        conn.execute("DELETE FROM universo")
        conn.executemany("INSERT INTO universo (data, ticker, volume_medio, motivo, disponivel_em) "
                         "VALUES (?, ?, ?, ?, ?)", linhas)
    logger.info("Universo: %d linhas (%d papéis distintos)", len(linhas), universo["ticker"].nunique() if len(universo) else 0)
    return len(linhas)
