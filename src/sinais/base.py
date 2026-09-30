"""Infraestrutura comum dos sinais: corte ponto-no-tempo, leitura e gravação.

Regra única de tempo: o sinal da data D usa apenas linhas com
`disponivel_em <= corte(D)`, onde corte(D) = D às 19:00 BRT (após o fechamento).
Esse corte é gravado como `disponivel_em` do sinal.

As funções de leitura aceitam `ate` (timestamp UTC ISO): tudo que tiver
`disponivel_em` posterior é ignorado. É assim que o teste anti look-ahead
recalcula "como se estivesse em D".
"""

import logging
import sqlite3
from datetime import date, time

import pandas as pd

from src.db.tempo import agora_utc_iso, iso_brt

logger = logging.getLogger(__name__)

HORA_CORTE = time(19, 0)


def corte(dia: date) -> str:
    return iso_brt(dia, HORA_CORTE)


def _ler(conn: sqlite3.Connection, sql: str, ate: str | None, params: tuple = ()) -> pd.DataFrame:
    if ate is not None:
        sql += " AND disponivel_em <= ?"
        params = (*params, ate)
    return pd.read_sql_query(sql, conn, params=params)


def carregar_cotacoes(conn: sqlite3.Connection, ate: str | None = None) -> pd.DataFrame:
    df = _ler(conn, "SELECT ticker, data, abertura, maxima, minima, fechamento, volume, disponivel_em "
                    "FROM cotacoes WHERE fonte = 'b3_cotahist'", ate)
    df["data"] = pd.to_datetime(df["data"])
    return df.sort_values(["ticker", "data"]).reset_index(drop=True)


def carregar_proventos(conn: sqlite3.Connection, ate: str | None = None) -> pd.DataFrame:
    df = _ler(conn, "SELECT ticker, tipo, data_ex, valor, fator, disponivel_em FROM proventos WHERE 1 = 1", ate)
    df["data_ex"] = pd.to_datetime(df["data_ex"])
    return df


def gravar(conn: sqlite3.Connection, sinais: pd.DataFrame, versoes: dict[str, int],
           desde: date | None = None) -> int:
    """Substitui, para cada nome de sinal em `versoes`, as linhas daquela versão
    pelas de `sinais` (colunas: ticker, data, nome, valor). Com `desde`, só as
    datas a partir dela (gravação incremental: o histórico antigo fica intacto).
    Recalcular é idempotente: rodar duas vezes dá o mesmo resultado."""
    sinais = sinais.dropna(subset=["valor"])
    sinais = sinais[sinais["nome"].isin(versoes)]
    if desde is not None:
        sinais = sinais[sinais["data"] >= pd.Timestamp(desde)]
    agora = agora_utc_iso()
    linhas = [
        (r.ticker, r.data.date().isoformat(), r.nome, float(r.valor), versoes[r.nome],
         corte(r.data.date()), agora)
        for r in sinais.itertuples(index=False)
    ]
    with conn:
        for nome, versao in versoes.items():
            if desde is None:
                conn.execute("DELETE FROM sinais WHERE nome = ? AND versao = ?", (nome, versao))
            else:
                conn.execute("DELETE FROM sinais WHERE nome = ? AND versao = ? AND data >= ?",
                             (nome, versao, desde.isoformat()))
        conn.executemany(
            "INSERT INTO sinais (ticker, data, nome, valor, versao, disponivel_em, calculado_em) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)", linhas)
    logger.info("%d valores gravados para %d sinais", len(linhas), len(versoes))
    return len(linhas)
