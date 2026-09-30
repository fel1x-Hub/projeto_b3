from datetime import date

import pandas as pd
import pytest

from src.ranking import gerar
from src.validacao import paper
from tests.test_ranking import N_ACOES, conn_mercado  # noqa: F401 (fixture)


def test_paper_trading_registra_carteira_e_patrimonio(conn_mercado):
    conn, dias = conn_mercado
    from scripts.backtest import matriz_retornos
    from src.ranking import dados
    # três rankings diários "ao vivo"
    for d in dias[300:303]:
        ranking, _ = gerar.ranking_da_data(conn, d, ["x"])
        gerar.gravar(conn, ranking, gerar.VERSAO_MODELO)
    inicio = paper.inicio(conn, se_vazio=dias[300].isoformat())
    assert paper.inicio(conn, se_vazio="2099-01-01") == inicio          # início fica fixo
    regra = paper.Regra(n_acoes=5, intervalo=10)
    r = paper.atualizar(conn, matriz_retornos(conn), dados.carregar_universo(conn), inicio, regra)
    carteira = conn.execute("SELECT data_execucao, data_ranking, COUNT(*), SUM(peso_alvo) FROM paper_carteira "
                            "GROUP BY 1, 2").fetchall()
    assert [tuple(c) for c in carteira] == [(dias[301].isoformat(), dias[300].isoformat(), 5, pytest.approx(1.0))]
    patrimonio = conn.execute("SELECT data, valor FROM paper_patrimonio ORDER BY data").fetchall()
    assert patrimonio[0]["data"] == dias[301].isoformat()               # monta no fechamento seguinte
    assert len(patrimonio) == len(r.valor)
    # rodar de novo não duplica
    paper.atualizar(conn, matriz_retornos(conn), dados.carregar_universo(conn), inicio, regra)
    assert conn.execute("SELECT COUNT(*) FROM paper_patrimonio").fetchone()[0] == len(patrimonio)
