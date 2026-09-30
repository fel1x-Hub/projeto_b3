import numpy as np
import pandas as pd
import pytest

from src.validacao.backtest import Custos, Regra, drawdown, escolher, metricas, simular

DIAS = pd.bdate_range("2024-01-01", periods=8)
SEM_CUSTO = Custos(emolumentos=0.0, faixas=((0.0, 0.0),))


def _retornos(**colunas):
    return pd.DataFrame(colunas, index=DIAS)


def _scores(*linhas):
    return pd.DataFrame(linhas, columns=["data", "ticker", "score"])


def _universo(tickers, volume=1e7):
    return pd.DataFrame([(d, t, volume) for d in DIAS for t in tickers], columns=["data", "ticker", "volume_medio"])


def test_execucao_no_fechamento_seguinte_e_primeiro_retorno_em_d_mais_2():
    # score em DIAS[0]: compra A no fechamento de DIAS[1]; o retorno de DIAS[1] não conta
    ret = _retornos(A=[0.0, 0.50, 0.10, 0.0, 0.0, 0.0, 0.0, 0.0], B=[0.0] * 8)
    sc = _scores((DIAS[0], "A", 1.0), (DIAS[0], "B", 0.0))
    r = simular(sc, ret, _universo(["A", "B"]), Regra(n_acoes=1, intervalo=100), SEM_CUSTO)
    assert r.retorno.index[0] == DIAS[1] and r.retorno.iloc[0] == 0.0
    assert r.retorno[DIAS[2]] == pytest.approx(0.10)
    assert r.valor.iloc[-1] == pytest.approx(1.10)


def test_pesos_derivam_entre_rebalanceamentos():
    ret = _retornos(A=[0, 0, 1.0, 0.0, 0, 0, 0, 0], B=[0, 0, 0.0, -0.5, 0, 0, 0, 0])
    sc = _scores((DIAS[0], "A", 1.0), (DIAS[0], "B", 0.9))
    r = simular(sc, ret, _universo(["A", "B"]), Regra(n_acoes=2, intervalo=100), SEM_CUSTO)
    # dia 2: 50/50 -> +50%; pesos viram A 2/3, B 1/3; dia 3: B cai 50% -> -1/6
    assert r.retorno[DIAS[2]] == pytest.approx(0.5)
    assert r.retorno[DIAS[3]] == pytest.approx(-1 / 6)
    assert r.valor.iloc[-1] == pytest.approx(1.5 * (1 - 1 / 6))


def test_custo_sobre_o_giro_por_faixa_de_liquidez():
    ret = _retornos(A=[0.0] * 8, B=[0.0] * 8)
    sc = _scores((DIAS[0], "A", 1.0), (DIAS[0], "B", 0.0), (DIAS[2], "A", 0.0), (DIAS[2], "B", 1.0))
    custos = Custos(emolumentos=0.0003, faixas=((5e6, 0.0005), (0.0, 0.0050)))
    universo = pd.concat([_universo(["A"], 1e7), _universo(["B"], 1e5)])
    r = simular(sc, ret, universo, Regra(n_acoes=1, intervalo=1), custos)  # rebalanceia a cada data com score
    # montagem: compra 100% de A (0,05% + 0,03%); troca: vende A (0,08%) e compra B (0,50% + 0,03%)
    assert r.custos.iloc[0] == pytest.approx(0.0008)
    assert r.custos.iloc[1] == pytest.approx(0.0008 + 0.0053)
    assert r.giro.iloc[1] == pytest.approx(1.0)
    assert r.valor.iloc[-1] == pytest.approx((1 - 0.0008) * (1 - 0.0061))


def test_regra_com_folga_segura_quem_ainda_esta_bem_colocado():
    dia = _scores(("d", "A", 5), ("d", "B", 4), ("d", "C", 3), ("d", "D", 2))
    assert escolher(dia, ["C"], Regra(n_acoes=2)) == ["A", "B"]             # sem folga: troca
    assert escolher(dia, ["C"], Regra(n_acoes=2, folga=3)) == ["C", "A"]    # C ainda no top 3: fica


def test_metricas():
    ret = pd.Series([0.01, -0.02, 0.03, 0.0], index=DIAS[:4])
    m = metricas(ret, cdi_diario=pd.Series(0.0, index=DIAS[:4]), giro=pd.Series([1.0, 0.5]))
    assert m["retorno_total"] == pytest.approx(1.01 * 0.98 * 1.03 - 1)
    assert m["drawdown_max"] == pytest.approx(0.98 - 1)
    assert m["giro_anual"] == pytest.approx(1.5 / (4 / 252))
    assert drawdown(pd.Series([1.0, 2.0, 1.0, 3.0])).tolist() == [0, 0, -0.5, 0]
