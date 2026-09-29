"""Dados sintéticos para testar sinais, gravados no banco com disponivel_em reais."""

from datetime import date, time, timedelta

import numpy as np
import pytest

from src.db.tempo import iso_brt

TS = "2026-01-01T00:00:00+00:00"


def dias_uteis(inicio: date, n: int) -> list[date]:
    dias, d = [], inicio
    while len(dias) < n:
        if d.weekday() < 5:
            dias.append(d)
        d += timedelta(days=1)
    return dias


def inserir_cotacoes(conn, ticker: str, dias: list[date], precos, volumes=None):
    volumes = volumes if volumes is not None else [1000] * len(dias)
    with conn:
        conn.executemany(
            "INSERT INTO cotacoes (ticker, data, fechamento, volume, fonte, disponivel_em, coletado_em) "
            "VALUES (?, ?, ?, ?, 'b3_cotahist', ?, ?)",
            [(ticker, d.isoformat(), float(p), int(v), iso_brt(d, time(19, 0)), TS)
             for d, p, v in zip(dias, precos, volumes)],
        )


def inserir_provento(conn, ticker: str, data_ex: date, valor=None, fator=None):
    tipo = "dividendo" if valor is not None else "desdobramento"
    with conn:
        conn.execute(
            "INSERT INTO proventos (ticker, tipo, data_ex, valor, fator, fonte, disponivel_em, coletado_em) "
            "VALUES (?, ?, ?, ?, ?, 'yfinance', ?, ?)",
            (ticker, tipo, data_ex.isoformat(), valor, fator, iso_brt(data_ex, time(0, 0)), TS),
        )


@pytest.fixture
def conn_precos(conn):
    """(conn, dias): PETR4 com 320 pregões de passeio aleatório, um dividendo e um desdobramento 2:1."""
    rng = np.random.default_rng(42)
    dias = dias_uteis(date(2024, 1, 2), 320)
    precos = 30 * np.cumprod(1 + rng.normal(0, 0.02, len(dias)))
    precos[200:] = precos[200:] / 2  # desdobramento 2:1 no pregão 200
    volumes = rng.integers(1_000, 5_000, len(dias))
    volumes[200:] *= 2
    inserir_cotacoes(conn, "PETR4", dias, precos, volumes)
    inserir_provento(conn, "PETR4", dias[150], valor=0.8)
    inserir_provento(conn, "PETR4", dias[200], fator=2.0)
    return conn, dias
