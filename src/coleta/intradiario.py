"""Cotação do momento durante o pregão (regra 15), via yfinance grátis.

Decisão do usuário (30/09/2026): yfinance, com ~16 min de atraso (medido).
Isolado aqui para poder trocar por fonte paga sem mexer no resto.

Grava em `cotacao_atual` (uma linha por papel, substituída a cada ciclo).
É PROVISÓRIO: o dado oficial é o arquivo da B3 da noite (`cotacoes`).
O fechamento anterior vem do dado oficial da B3 no banco; para o Ibovespa,
do próprio yfinance.
"""

import logging
import sqlite3
from datetime import datetime, time, timezone
from typing import Callable

import pandas as pd

from src.db.tempo import FUSO_B3, para_iso_utc

logger = logging.getLogger(__name__)
logging.getLogger("yfinance").setLevel(logging.ERROR)

FONTE = "yfinance_intradia"
INDICE = {"IBOV": "^BVSP"}
LOTE = 80
ABERTURA, FECHAMENTO = time(10, 0), time(18, 0)  # janela do ciclo (inclui call de fechamento)

Baixador = Callable[[list[str]], pd.DataFrame]  # símbolos Yahoo -> DataFrame (colunas: (símbolo, campo))


def _baixar_yahoo(simbolos: list[str]) -> pd.DataFrame:
    import yfinance as yf
    return yf.download(simbolos, period="5d", interval="1m", group_by="ticker", progress=False,
                       auto_adjust=False, threads=True)


def pregao_em_andamento(agora: datetime | None = None) -> bool:
    """Dia útil entre 10h e 18h de Brasília. Feriados aparecem como 'sem cotação nova'."""
    agora = (agora or datetime.now(timezone.utc)).astimezone(FUSO_B3)
    return agora.weekday() < 5 and ABERTURA <= agora.time() <= FECHAMENTO


def papeis_acompanhados(conn: sqlite3.Connection) -> list[str]:
    """Universo do último pregão + exceções manuais ativas."""
    return [r[0] for r in conn.execute(
        "SELECT ticker FROM universo WHERE data = (SELECT MAX(data) FROM universo) "
        "UNION SELECT ticker FROM ativos WHERE ativo = 1 AND origem = 'manual' ORDER BY 1")]


def _ultimo(df: pd.DataFrame, simbolo: str) -> tuple[float, pd.Timestamp, float | None] | None:
    """(último preço, horário, fechamento do pregão anterior segundo a fonte)."""
    if simbolo not in df.columns.get_level_values(0):
        return None
    fech = df[simbolo]["Close"].dropna()
    if fech.empty:
        return None
    horario = fech.index[-1]
    anteriores = fech[fech.index.date < horario.date()]
    return float(fech.iloc[-1]), horario, (float(anteriores.iloc[-1]) if not anteriores.empty else None)


def coletar(conn: sqlite3.Connection, baixar: Baixador = _baixar_yahoo) -> int:
    """Atualiza `cotacao_atual`; devolve quantos papéis foram atualizados."""
    tickers = papeis_acompanhados(conn)
    simbolos = {f"{t}.SA": t for t in tickers} | {s: t for t, s in INDICE.items()}
    anteriores = dict(conn.execute(
        "SELECT c.ticker, c.fechamento FROM cotacoes c JOIN (SELECT ticker, MAX(data) d FROM cotacoes "
        "WHERE fonte = 'b3_cotahist' GROUP BY ticker) u ON u.ticker = c.ticker AND u.d = c.data "
        "WHERE c.fonte = 'b3_cotahist'").fetchall())
    agora = para_iso_utc(datetime.now(timezone.utc))
    linhas = []
    lista = list(simbolos)
    for i in range(0, len(lista), LOTE):
        lote = lista[i:i + LOTE]
        try:
            df = baixar(lote)
        except Exception as e:  # noqa: BLE001 - um lote ruim não para os outros
            logger.warning("Lote de cotações falhou: %s", e)
            continue
        for simbolo in lote:
            info = _ultimo(df, simbolo)
            if info is None:
                continue
            preco, horario, anterior_fonte = info
            ticker = simbolos[simbolo]
            anterior = anteriores.get(ticker) if ticker not in INDICE else anterior_fonte
            variacao = preco / anterior - 1 if anterior else None
            linhas.append((ticker, preco, anterior, variacao, para_iso_utc(horario.to_pydatetime()), FONTE, agora))
    with conn:
        conn.executemany("INSERT OR REPLACE INTO cotacao_atual VALUES (?, ?, ?, ?, ?, ?, ?)", linhas)
    logger.info("Cotação do momento: %d de %d papéis", len(linhas), len(simbolos))
    return len(linhas)
