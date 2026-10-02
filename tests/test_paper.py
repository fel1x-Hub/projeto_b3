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
        gerar.gravar(conn, gerar.ranking_da_data(conn, d, ["x"]).ranking, gerar.VERSAO_MODELO)
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


def test_troca_de_modelo_arquiva_e_reinicia(conn):
    import json
    from src.validacao import paper
    with conn:
        conn.execute("INSERT INTO paper_config VALUES ('inicio', '2026-09-29')")   # sem 'versao' = v1 antigo
        conn.execute("INSERT INTO paper_patrimonio VALUES ('2026-10-01', 0.9994, 0.001, 0, '2026-10-01T22:00:00+00:00')")
    assert paper.inicio(conn, se_vazio="2026-10-02", versao="lgbm-v1") == "2026-09-29"   # mesma versão: nada muda
    assert paper.inicio(conn, se_vazio="2026-10-02", versao="lgbm-v2") == "2026-10-02"   # versão nova: recomeça
    cfg = dict(conn.execute("SELECT chave, valor FROM paper_config"))
    assert cfg["versao"] == "lgbm-v2" and conn.execute("SELECT COUNT(*) FROM paper_patrimonio").fetchone()[0] == 0
    assert json.loads(cfg["historico:lgbm-v1"]) == {"inicio": "2026-09-29", "fim": "2026-10-01", "patrimonio_final": 0.9994}
    assert paper.inicio(conn, se_vazio="2026-10-05", versao="lgbm-v2") == "2026-10-02"   # depois fica fixo
