import numpy as np
import pandas as pd
import pytest

from src.ranking import venda


def test_auc_perfeita_aleatoria_e_invertida():
    y = pd.Series([0, 0, 1, 1])
    assert venda.auc(pd.Series([0.1, 0.2, 0.8, 0.9]), y) == 1.0
    assert venda.auc(pd.Series([0.9, 0.8, 0.2, 0.1]), y) == 0.0
    rng = np.random.default_rng(0)
    yy = pd.Series(rng.integers(0, 2, 5000))
    assert venda.auc(pd.Series(rng.random(5000)), yy) == pytest.approx(0.5, abs=0.03)


def test_alvo_queda_absoluta_e_data_de_treino():
    datas = pd.bdate_range("2024-01-01", periods=30)
    r = pd.DataFrame({"X": [0.0] * 30, "Y": [0.0] * 30}, index=datas)
    r.loc[datas[2], "X"] = -0.05          # X cai logo depois do dia 0
    r.loc[datas[2], "Y"] = 0.05
    a = venda.alvo(r, horizonte=3).set_index(["data", "ticker"])
    assert a.loc[(datas[0], "X"), "caiu"] == 1 and a.loc[(datas[0], "Y"), "caiu"] == 0
    assert a.loc[(datas[0], "X"), "data_alvo"] == datas[4]      # só treina depois do fim da janela


def test_extras_usam_so_o_passado():
    datas = pd.bdate_range("2023-01-01", periods=300)
    r = pd.DataFrame({"X": np.r_[[0.001] * 280, [-0.01] * 20]}, index=datas)
    scores = pd.DataFrame({"data": datas, "ticker": "X", "score": 1.0})
    e = venda.extras(r, scores)
    assert e.loc[(datas[279], "X"), "dist_max_252"] == pytest.approx(0.0, abs=1e-9)   # na máxima
    assert e.loc[(datas[299], "X"), "dist_max_252"] < -0.15                           # 20 dias caindo


def test_calibracao_troca_probabilidade_pela_taxa_real():
    rng = np.random.default_rng(1)
    prob = pd.Series(rng.random(20000))
    caiu = pd.Series((rng.random(20000) < 0.3 + 0.4 * prob).astype(int))   # taxa real = 0,3 + 0,4·prob
    tab = venda.tabela_calibracao(prob, caiu)
    assert len(tab) == 10
    assert venda.chance_calibrada(0.95, tab) == pytest.approx(0.3 + 0.4 * 0.95, abs=0.04)
    assert venda.chance_calibrada(0.02, tab) == pytest.approx(0.3 + 0.4 * 0.05, abs=0.04)
    assert venda.chance_calibrada(None, tab) is None
