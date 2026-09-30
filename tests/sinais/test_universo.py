from datetime import date

import pandas as pd
import pytest

from src.db.ativos import registrar_automaticos, sincronizar_ativos
from src.sinais import base, universo
from tests.sinais.conftest import dias_uteis, inserir_cotacoes


@pytest.fixture
def conn_univ(conn):
    """PETR4: R$ 200 mil/dia; VALE3: R$ 50 mil/dia; WEGE3 (auto): começa líquida e seca."""
    dias = dias_uteis(date(2024, 1, 2), 150)
    registrar_automaticos(conn, {"VALE3": "VALE", "WEGE3": "WEG"})
    with conn:  # PETR4 da fixture base é manual; aqui testa só o critério automático
        conn.execute("UPDATE ativos SET origem = 'auto' WHERE ticker = 'PETR4'")
    inserir_cotacoes(conn, "PETR4", dias, [20.0] * 150, [10_000] * 150)   # 200 mil/dia
    inserir_cotacoes(conn, "VALE3", dias, [10.0] * 150, [5_000] * 150)    # 50 mil/dia
    inserir_cotacoes(conn, "WEGE3", dias[:60], [40.0] * 60, [10_000] * 60)  # 400 mil/dia, só 60 pregões
    return conn, dias


def _no_universo(u, dia):
    return set(u.loc[u["data"] == pd.Timestamp(dia), "ticker"])


def test_filtro_de_liquidez_ponto_no_tempo(conn_univ):
    conn, dias = conn_univ
    u = universo.calcular(conn)
    assert _no_universo(u, dias[19]) == set()                      # menos de 21 pregões de histórico
    assert _no_universo(u, dias[30]) == {"PETR4", "WEGE3"}          # VALE3 ilíquida
    # WEGE3 some da bolsa no pregão 60: média de 63 pregões com zeros cai abaixo de 100 mil
    # quando menos de 16 dos últimos 63 pregões tiveram negócio (400 mil x 16 / 63 = 101,6 mil)
    assert "WEGE3" in _no_universo(u, dias[60 + 63 - 17])
    assert "WEGE3" not in _no_universo(u, dias[60 + 63 - 15])
    # no histórico ela continua existindo (sem viés de sobrevivência)
    assert "WEGE3" in set(u["ticker"])


def test_inclusao_e_exclusao_manual(conn_univ):
    conn, dias = conn_univ
    sincronizar_ativos(conn, [
        {"ticker": "PETR4", "nome": "Petrobras", "setor": None, "cnpj": None, "ativo": 0},   # excluída
        {"ticker": "VALE3", "nome": "Vale", "setor": None, "cnpj": None, "ativo": 1},        # incluída à força
    ])
    u = universo.calcular(conn)
    assert _no_universo(u, dias[30]) == {"VALE3", "WEGE3"}
    assert u.loc[(u["ticker"] == "VALE3") & (u["data"] == pd.Timestamp(dias[30])), "motivo"].iloc[0] == "manual"


def test_anti_look_ahead_universo(conn_univ):
    conn, dias = conn_univ
    completo = universo.calcular(conn)
    for d in (dias[25], dias[70], dias[110], dias[140]):
        truncado = universo.calcular(conn, ate=base.corte(d))
        a = completo[completo["data"] == pd.Timestamp(d)].reset_index(drop=True)
        b = truncado[truncado["data"] == pd.Timestamp(d)].reset_index(drop=True)
        pd.testing.assert_frame_equal(a, b)


def test_gravar_e_idempotente(conn_univ):
    conn, _ = conn_univ
    u = universo.calcular(conn)
    n = universo.gravar(conn, u)
    assert universo.gravar(conn, u) == n
    assert conn.execute("SELECT COUNT(*) FROM universo").fetchone()[0] == n
