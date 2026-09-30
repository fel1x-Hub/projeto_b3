"""Etapa 4: matriz de features, alvo, walk-forward e ranking ponto-no-tempo,
com dados sintéticos em que um sinal ('x') prevê o retorno futuro."""

from datetime import date, time

import numpy as np
import pandas as pd
import pytest

from src.db.ativos import registrar_automaticos
from src.db.tempo import iso_brt
from src.ranking import dados, gerar, modelo
from src.sinais import base
from tests.sinais.conftest import TS, dias_uteis

N_ACOES, N_DIAS = 40, 330


@pytest.fixture
def conn_mercado(conn, monkeypatch):
    """40 ações; o sinal 'x' de hoje antecipa o retorno dos próximos 21 pregões."""
    rng = np.random.default_rng(7)
    dias = dias_uteis(date(2023, 1, 2), N_DIAS)
    tickers = [f"AC{i:02d}3" for i in range(N_ACOES)]
    registrar_automaticos(conn, {t: t for t in tickers})
    habilidade = rng.normal(0, 1, N_ACOES)            # ações "boas" sobem mais
    retornos = 0.001 * habilidade[None, :] + rng.normal(0, 0.01, (N_DIAS, N_ACOES))
    precos = 20 * np.cumprod(1 + retornos, axis=0)
    cot, sinal, univ = [], [], []
    for j, t in enumerate(tickers):
        for i, d in enumerate(dias):
            corte = iso_brt(d, time(19, 0))
            cot.append((t, d.isoformat(), float(precos[i, j]), 100_000, iso_brt(d, time(19, 0)), TS))
            sinal.append((t, d.isoformat(), "x", float(habilidade[j] + rng.normal(0, 0.5)), 1, corte, TS))
            univ.append((d.isoformat(), t, 2e6, "liquidez", corte))
    with conn:
        conn.executemany("INSERT INTO cotacoes (ticker, data, fechamento, volume, fonte, disponivel_em, coletado_em) "
                         "VALUES (?, ?, ?, ?, 'b3_cotahist', ?, ?)", cot)
        conn.executemany("INSERT INTO sinais (ticker, data, nome, valor, versao, disponivel_em, calculado_em) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?)", sinal)
        conn.executemany("INSERT INTO universo VALUES (?, ?, ?, ?, ?)", univ)
    monkeypatch.setattr(modelo, "TREINO_MINIMO_DIAS", 120)
    return conn, dias


def test_alvo_so_existe_quando_o_futuro_ja_ocorreu(conn_mercado):
    conn, dias = conn_mercado
    alvo = dados.calcular_alvo(conn)
    assert alvo["data"].max() == pd.Timestamp(dias[-1 - dados.HORIZONTE])
    assert (alvo["data_alvo"] > alvo["data"]).all()
    # retorno relativo tem mediana zero em cada dia
    assert alvo.groupby("data")["retorno_relativo"].median().abs().max() < 1e-12
    # com corte no meio, alvos que terminam depois do corte não existem
    corte = dias[200]
    parcial = dados.calcular_alvo(conn, ate=base.corte(corte))
    assert parcial["data_alvo"].max() <= pd.Timestamp(corte)


def test_features_em_percentil_do_dia(conn_mercado):
    conn, dias = conn_mercado
    X = dados.carregar_features(conn, ["x"])
    dia = X.xs(pd.Timestamp(dias[50]), level="data")
    assert dia["x"].min() == pytest.approx(1 / N_ACOES) and dia["x"].max() == 1.0


def test_walk_forward_so_treina_com_alvos_realizados(conn_mercado, monkeypatch):
    conn, _ = conn_mercado
    X, alvo = dados.carregar_features(conn, ["x"]), dados.calcular_alvo(conn)
    vistos = []
    original = modelo.treinar

    def espiao(Xt, y):
        vistos.append(len(Xt))
        return original(Xt, y)

    monkeypatch.setattr(modelo, "treinar", espiao)
    prev = modelo.walk_forward(X, alvo, ["x"])
    assert vistos and not prev.empty
    for refit, grupo in prev.groupby("refit"):
        assert grupo["data"].min() >= refit                   # teste começa no refit
    # o sinal é preditivo: o modelo precisa achar
    r = modelo.resumo(modelo.ic_diario(prev, alvo), modelo.spread_decis(prev, alvo), dados.HORIZONTE)
    assert r["ic_medio"] > 0.2 and r["spread_medio"] > 0


def test_ranking_da_data_nao_muda_com_dados_futuros(conn_mercado):
    conn, dias = conn_mercado
    dia = dias[250]
    antes = gerar.ranking_da_data(conn, dia, ["x"]).ranking
    with conn:  # envenena o futuro: preços absurdos e sinais invertidos depois do dia
        conn.execute("UPDATE cotacoes SET fechamento = fechamento * 50 WHERE data > ?", (dia.isoformat(),))
        conn.execute("UPDATE sinais SET valor = -valor WHERE data > ?", (dia.isoformat(),))
    depois = gerar.ranking_da_data(conn, dia, ["x"]).ranking
    pd.testing.assert_frame_equal(antes, depois)
    assert list(antes["posicao"]) == list(range(1, N_ACOES + 1))


def test_gravar_ranking_e_idempotente(conn_mercado):
    conn, dias = conn_mercado
    ranking = gerar.ranking_da_data(conn, dias[250], ["x"]).ranking
    n = gerar.gravar(conn, ranking, "teste")
    assert gerar.gravar(conn, ranking, "teste") == n == N_ACOES
    linha = conn.execute("SELECT posicao, disponivel_em FROM ranking WHERE posicao = 1").fetchone()
    assert linha["disponivel_em"] == base.corte(dias[250])


def test_dia_sem_dados_e_erro_claro(conn_mercado):
    conn, _ = conn_mercado
    with pytest.raises(ValueError, match="sem universo"):
        gerar.ranking_da_data(conn, date(2024, 12, 25), ["x"])


def test_modelo_salvo_para_auditoria(conn_mercado, tmp_path):
    conn, dias = conn_mercado
    gerar.ranking_da_data(conn, dias[250], ["x"], salvar_em=tmp_path)
    assert (tmp_path / f"{gerar.VERSAO_MODELO}_{dias[250].isoformat()}.txt").exists()


def test_fatores_explicam_cada_acao(conn_mercado):
    conn, dias = conn_mercado
    r = gerar.ranking_da_data(conn, dias[250], ["x"])
    assert set(r.fatores["ticker"]) == set(r.ranking["ticker"])
    assert set(r.fatores["sinal"]) == {"x"} and r.fatores["percentil"].between(0, 1).all()
    # a ação do topo tem contribuição positiva do sinal; a do fundo, negativa
    topo, fundo = r.ranking["ticker"].iloc[0], r.ranking["ticker"].iloc[-1]
    contrib = r.fatores.set_index("ticker")["contribuicao"]
    assert contrib[topo] > 0 > contrib[fundo]
    assert gerar.gravar_fatores(conn, r.fatores, "teste") == len(r.fatores)
