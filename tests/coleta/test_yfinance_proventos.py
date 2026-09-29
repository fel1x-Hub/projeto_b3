from datetime import date

import pandas as pd
import pytest

from src.coleta import yfinance_proventos as yp
from src.coleta.execucao import ColetaParcial


def _acoes(*linhas):
    """DataFrame no formato de yf.Ticker(...).actions."""
    indice = pd.DatetimeIndex([pd.Timestamp(d, tz="America/Sao_Paulo") for d, _, _ in linhas], name="Date")
    return pd.DataFrame({"Dividends": [d for _, d, _ in linhas],
                         "Stock Splits": [s for _, _, s in linhas]}, index=indice)


WEGE = _acoes(("2020-03-01", 0.05, 0.0),   # antes de `desde`
              ("2021-04-28", 0.0, 2.0),    # desdobramento 2:1
              ("2026-09-21", 0.107212, 0.0))


def test_converter():
    regs = yp.converter("WEGE3", WEGE, date(2021, 1, 1))
    assert [(r["tipo"], r["data_ex"], r["valor"], r["fator"]) for r in regs] == [
        ("desdobramento", "2021-04-28", None, 2.0),
        ("dividendo", "2026-09-21", 0.107212, None),
    ]
    assert regs[1]["disponivel_em"] == "2026-09-21T03:00:00+00:00"  # 00:00 BRT da data ex


def test_converter_vazio():
    assert yp.converter("X", pd.DataFrame(), date(2021, 1, 1)) == []
    assert yp.converter("X", None, date(2021, 1, 1)) == []


def test_coleta_incremental_e_revisao(conn):
    buscar = {"PETR4": WEGE}.__getitem__
    assert yp.coletar(conn, date(2021, 1, 1), buscar=buscar, pausa=0) == 2
    assert yp.coletar(conn, date(2021, 1, 1), buscar=buscar, pausa=0) == 0

    # Yahoo reescala o histórico (ex: após novo desdobramento) -> revisão registrada
    reescalado = _acoes(("2021-04-28", 0.0, 2.0), ("2026-09-21", 0.053606, 0.0))
    yp.coletar(conn, date(2021, 1, 1), buscar={"PETR4": reescalado}.__getitem__, pausa=0)
    rev = conn.execute("SELECT campo, valor_antigo, valor_novo FROM revisoes").fetchone()
    assert tuple(rev) == ("valor", "0.107212", "0.053606")


def test_falha_de_um_ticker_e_parcial(conn):
    with conn:
        conn.execute("INSERT INTO ativos (ticker, nome, ativo, criado_em, atualizado_em) "
                     "VALUES ('VALE3', 'Vale', 1, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')")

    def buscar(ticker):
        if ticker == "VALE3":
            raise ConnectionError("Too Many Requests")
        return WEGE

    with pytest.raises(ColetaParcial, match="VALE3") as e:
        yp.coletar(conn, date(2021, 1, 1), buscar=buscar, pausa=0)
    assert e.value.novos == 2


def test_falha_de_todos_e_erro(conn):
    def buscar(ticker):
        raise ConnectionError("bloqueado")

    with pytest.raises(RuntimeError, match="todos"):
        yp.coletar(conn, date(2021, 1, 1), buscar=buscar, pausa=0)
