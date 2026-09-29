"""Proventos (dividendos/JCP e desdobramentos/grupamentos) via yfinance.

O yfinance usa a API não oficial do Yahoo Finance: uso pessoal, sem garantia,
com bloqueio temporário se houver requisições demais. Por isso: uma chamada por
ativo, com pausa entre elas, e falhas por ticker viram coleta parcial.

Particularidades do Yahoo (documentadas em docs/schema.md):
- Dividendos e JCP na mesma data vêm somados numa linha só.
- Valores já vêm na escala atual de ações (divididos por desdobramentos
  posteriores); quando houver um desdobramento novo, o Yahoo reescala o
  histórico e isso aparece como revisões.
- Não há data de anúncio: `disponivel_em` = data ex às 00:00 BRT (o anúncio é
  sempre anterior à data ex, então o dado já era público nesse momento).
"""

import logging
import sqlite3
import time as _time
from datetime import date, time
from typing import Callable

import pandas as pd

from src.coleta.execucao import ColetaParcial
from src.coleta.persistencia import salvar
from src.db.tempo import iso_brt

logger = logging.getLogger(__name__)
logging.getLogger("yfinance").setLevel(logging.WARNING)

FONTE = "yfinance"
CHAVES = ["ticker", "fonte", "tipo", "data_ex"]
PAUSA_ENTRE_TICKERS = 1.0


def _buscar_yahoo(ticker: str) -> pd.DataFrame:
    import yfinance as yf
    return yf.Ticker(f"{ticker}.SA").actions


def converter(ticker: str, acoes: pd.DataFrame, desde: date) -> list[dict]:
    """DataFrame de `actions` (Dividends, Stock Splits) -> linhas de `proventos`."""
    registros = []
    if acoes is None or acoes.empty:
        return registros
    for instante, linha in acoes.iterrows():
        data_ex = pd.Timestamp(instante).date()
        if data_ex < desde:
            continue
        base = {"ticker": ticker, "data_ex": data_ex.isoformat(), "fonte": FONTE,
                "disponivel_em": iso_brt(data_ex, time(0, 0))}
        dividendo = float(linha.get("Dividends", 0) or 0)
        fator = float(linha.get("Stock Splits", 0) or 0)
        if dividendo > 0:
            registros.append({**base, "tipo": "dividendo", "valor": round(dividendo, 8), "fator": None})
        if fator > 0:
            registros.append({**base, "tipo": "desdobramento", "valor": None, "fator": fator})
    return registros


def coletar(
    conn: sqlite3.Connection,
    desde: date,
    buscar: Callable[[str], pd.DataFrame] = _buscar_yahoo,
    pausa: float = PAUSA_ENTRE_TICKERS,
) -> int:
    tickers = [r[0] for r in conn.execute("SELECT ticker FROM ativos WHERE ativo = 1 ORDER BY ticker")]
    novos, falhas = 0, []
    for i, ticker in enumerate(tickers):
        if i and pausa:
            _time.sleep(pausa)
        try:
            registros = converter(ticker, buscar(ticker), desde)
        except Exception as e:  # noqa: BLE001 - um ticker não derruba os outros
            logger.warning("Proventos de %s falharam: %s", ticker, e)
            falhas.append(ticker)
            continue
        novos += salvar(conn, "proventos", CHAVES, registros, fonte=FONTE).novos

    if falhas and len(falhas) == len(tickers):
        raise RuntimeError(f"yfinance falhou para todos os tickers ({', '.join(falhas)})")
    if falhas:
        raise ColetaParcial(novos, f"proventos não obtidos: {', '.join(falhas)}")
    return novos
