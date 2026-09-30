"""Paper trading: a regra do backtest aplicada daqui para a frente.

Usa os rankings `lgbm-vN` gerados dia a dia (só com dados até cada dia) a
partir da data de início, simula a carteira com o MESMO motor do backtest
(execução no fechamento seguinte, custos, deriva de pesos) e grava as
carteiras montadas e o patrimônio diário. Nenhuma ordem real é enviada.
"""

import logging
import sqlite3

import pandas as pd

from src.db.tempo import agora_utc_iso
from src.ranking import gerar
from src.validacao.backtest import Custos, Regra, Resultado, simular

logger = logging.getLogger(__name__)

REGRA = Regra(n_acoes=30, intervalo=10)  # decidida pelo usuário (CLAUDE.md, etapa 5)


def inicio(conn: sqlite3.Connection, se_vazio: str | None = None) -> str | None:
    """Data de início do paper trading. Na primeira chamada com `se_vazio`, grava
    essa data como início (fica fixa daí em diante)."""
    linha = conn.execute("SELECT valor FROM paper_config WHERE chave = 'inicio'").fetchone()
    if linha:
        return linha[0]
    if se_vazio is not None:
        with conn:
            conn.execute("INSERT INTO paper_config VALUES ('inicio', ?)", (se_vazio,))
        logger.info("Paper trading iniciado em %s", se_vazio)
    return se_vazio


def atualizar(conn: sqlite3.Connection, retornos: pd.DataFrame, universo: pd.DataFrame,
              data_inicio: str, regra: Regra = REGRA, custos: Custos = Custos()) -> Resultado | None:
    """Recalcula carteiras e patrimônio desde `data_inicio` e grava."""
    scores = pd.read_sql_query(
        "SELECT data, ticker, score FROM ranking WHERE versao_modelo = ? AND data >= ?", conn,
        params=(gerar.VERSAO_MODELO, data_inicio), parse_dates=["data"])
    if scores.empty:
        logger.warning("Sem rankings %s desde %s", gerar.VERSAO_MODELO, data_inicio)
        return None
    try:
        r = simular(scores, retornos, universo, regra, custos)
    except ValueError as e:
        logger.warning("Paper trading ainda sem dados suficientes: %s", e)
        return None
    datas_ranking = sorted(set(scores["data"]))[:: regra.intervalo]
    agora = agora_utc_iso()
    with conn:
        conn.execute("DELETE FROM paper_carteira WHERE data_ranking >= ?", (data_inicio,))
        conn.execute("DELETE FROM paper_patrimonio WHERE data >= ?", (data_inicio,))
        for (execucao, tickers), d_rank in zip(sorted(r.carteiras.items()), datas_ranking):
            peso = 1.0 / len(tickers) if tickers else 0
            conn.executemany("INSERT INTO paper_carteira VALUES (?, ?, ?, ?)",
                             [(execucao.date().isoformat(), t, peso, d_rank.date().isoformat()) for t in tickers])
        conn.executemany("INSERT INTO paper_patrimonio VALUES (?, ?, ?, ?, ?)",
                         [(d.date().isoformat(), float(r.valor[d]), float(r.retorno[d]),
                           float(r.custos.get(d, 0.0)), agora) for d in r.valor.index])
    return r
