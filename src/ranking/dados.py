"""Matriz de features e alvo do modelo de ranking.

Features: sinais da tabela `sinais`, só para (data, ticker) do universo
daquele dia, convertidos em PERCENTIL dentro do dia (0 a 1). Isso tira a
escala (P/L e RSI ficam comparáveis), reduz o peso de outliers e deixa o
modelo focado em ordenar as ações entre si. Valor ausente fica NaN (o LightGBM
trata faltantes).

Alvo: retorno total dos próximos HORIZONTE pregões menos a mediana do
universo no mesmo dia (retorno relativo). Para treinar usamos o percentil
desse retorno no dia; para avaliar, o retorno em si.

Ponto-no-tempo: com `ate`, só entram sinais, universo e cotações com
disponivel_em <= ate. O alvo do dia t só existe quando o pregão t+HORIZONTE
já ocorreu (`data_alvo`); o treino filtra por isso.
"""

import sqlite3

import numpy as np
import pandas as pd

from src.sinais import base, fundamentalistas, tecnicos
from src.sinais.precos import retornos_totais

HORIZONTE = 21
# sentimento fica de fora até ter histórico (começou em 29/09/2026)
FEATURES_BASE = list(tecnicos.NOMES) + list(fundamentalistas.NOMES)
FEATURES_EVENTOS = ["evt_saldo", "evt_n_21d"]


def carregar_universo(conn: sqlite3.Connection, ate: str | None = None) -> pd.DataFrame:
    df = base._ler(conn, "SELECT data, ticker, volume_medio FROM universo WHERE 1 = 1", ate)
    df["data"] = pd.to_datetime(df["data"])
    return df


def carregar_features(conn: sqlite3.Connection, nomes: list[str], ate: str | None = None,
                      percentil: bool = True) -> pd.DataFrame:
    """DataFrame indexado por (data, ticker) do universo, uma coluna por sinal."""
    universo = carregar_universo(conn, ate).set_index(["data", "ticker"])
    matriz = pd.DataFrame(index=universo.index)
    for nome in nomes:
        # corte aplicado depois da consulta (a coluna disponivel_em existe nas duas tabelas)
        s = base._ler(conn, "SELECT s.data, s.ticker, s.valor, s.disponivel_em FROM sinais s "
                            "JOIN universo u ON u.data = s.data AND u.ticker = s.ticker "
                            "WHERE s.nome = ?", None, (nome,))
        if ate is not None:
            s = s[s["disponivel_em"] <= ate]
        s["data"] = pd.to_datetime(s["data"])
        matriz[nome] = s.set_index(["data", "ticker"])["valor"].reindex(matriz.index)
    if percentil:
        matriz = matriz.groupby(level="data").rank(pct=True)
    return matriz.sort_index()


def calcular_alvo(conn: sqlite3.Connection, ate: str | None = None, horizonte: int = HORIZONTE) -> pd.DataFrame:
    """Colunas: data, ticker, retorno_futuro, retorno_relativo, data_alvo.
    Só para (data, ticker) do universo e com o pregão futuro já ocorrido."""
    cotacoes = base.carregar_cotacoes(conn, ate)
    proventos = base.carregar_proventos(conn, ate)
    universo = carregar_universo(conn, ate)
    if cotacoes.empty or universo.empty:
        return pd.DataFrame(columns=["data", "ticker", "retorno_futuro", "retorno_relativo", "data_alvo"])
    calendario = pd.DatetimeIndex(sorted(cotacoes["data"].unique()))
    data_alvo = pd.Series(calendario, index=calendario).shift(-horizonte)

    tickers = set(universo["ticker"])
    partes = []
    for ticker, cot in cotacoes[cotacoes["ticker"].isin(tickers)].groupby("ticker"):
        r = retornos_totais(cot, proventos[proventos["ticker"] == ticker]).fillna(0.0)
        indice = (1 + r).cumprod().reindex(calendario).ffill()  # dia sem negócio: preço parado
        futuro = indice.shift(-horizonte) / indice - 1
        partes.append(pd.DataFrame({"data": calendario, "ticker": ticker, "retorno_futuro": futuro.to_numpy()}))
    alvo = pd.concat(partes, ignore_index=True).merge(universo[["data", "ticker"]], on=["data", "ticker"])
    alvo = alvo.dropna(subset=["retorno_futuro"])
    alvo["retorno_relativo"] = alvo["retorno_futuro"] - alvo.groupby("data")["retorno_futuro"].transform("median")
    alvo["data_alvo"] = alvo["data"].map(data_alvo)
    return alvo.dropna(subset=["data_alvo"]).reset_index(drop=True)
