"""Sinais técnicos (código puro, pandas), calculados sobre o índice de retorno
total (preço ajustado por proventos, sem saltos em desdobramentos).

Todos os cálculos são causais (janelas móveis olhando só para trás). Valores
sem janela completa ficam ausentes (não gravados).
"""

import sqlite3

import numpy as np
import pandas as pd

from src.sinais import base
from src.sinais.precos import indice_retorno_total

VERSAO = 1
JANELAS_RETORNO = (1, 5, 21, 63)
JANELAS_MEDIA = (21, 50, 200)
JANELAS_VOL = (21, 63)
JANELA_RSI = 14
JANELA_VOLUME = 21

NOMES = (
    [f"ret_{n}d" for n in JANELAS_RETORNO]
    + [f"dist_mm{n}" for n in JANELAS_MEDIA]
    + [f"rsi{JANELA_RSI}"]
    + [f"vol_{n}d" for n in JANELAS_VOL]
    + [f"vol_fin_rel{JANELA_VOLUME}"]
)
VERSOES = {nome: VERSAO for nome in NOMES}


def rsi(indice: pd.Series, n: int) -> pd.Series:
    """RSI de Wilder (médias exponenciais com alfa = 1/n)."""
    delta = indice.diff()
    ganho = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    perda = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    resultado = 100 - 100 / (1 + ganho / perda)
    return resultado.where(perda != 0, 100.0).where(ganho.notna())


def sinais_ativo(cotacoes: pd.DataFrame, proventos: pd.DataFrame) -> pd.DataFrame:
    """Sinais de um ativo em formato largo (índice = data, colunas = NOMES)."""
    indice = indice_retorno_total(cotacoes, proventos)
    retorno = indice.pct_change()
    cot = cotacoes.sort_values("data").set_index("data")
    volume_fin = cot["volume"] * cot["fechamento"]  # invariante a desdobramentos

    s = pd.DataFrame(index=indice.index)
    for n in JANELAS_RETORNO:
        s[f"ret_{n}d"] = indice / indice.shift(n) - 1
    for n in JANELAS_MEDIA:
        s[f"dist_mm{n}"] = indice / indice.rolling(n, min_periods=n).mean() - 1
    s[f"rsi{JANELA_RSI}"] = rsi(indice, JANELA_RSI)
    for n in JANELAS_VOL:
        s[f"vol_{n}d"] = retorno.rolling(n, min_periods=n).std() * np.sqrt(252)
    media_anterior = volume_fin.shift(1).rolling(JANELA_VOLUME, min_periods=JANELA_VOLUME).mean()
    s[f"vol_fin_rel{JANELA_VOLUME}"] = (volume_fin / media_anterior).to_numpy()
    return s


def calcular(conn: sqlite3.Connection, ate: str | None = None) -> pd.DataFrame:
    """Sinais técnicos de todos os ativos em formato longo (ticker, data, nome, valor),
    usando só dados com disponivel_em <= `ate`."""
    cotacoes = base.carregar_cotacoes(conn, ate)
    proventos = base.carregar_proventos(conn, ate)
    partes = []
    for ticker, cot in cotacoes.groupby("ticker"):
        largo = sinais_ativo(cot, proventos[proventos["ticker"] == ticker])
        longo = largo.rename_axis("data").reset_index().melt(id_vars="data", var_name="nome", value_name="valor")
        longo["ticker"] = ticker
        partes.append(longo.dropna(subset=["valor"]))
    if not partes:
        return pd.DataFrame(columns=["ticker", "data", "nome", "valor"])
    return pd.concat(partes, ignore_index=True)[["ticker", "data", "nome", "valor"]]
