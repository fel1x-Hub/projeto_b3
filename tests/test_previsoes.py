import numpy as np
import pandas as pd
import pytest

from src.ranking import calibracao as cal
from src.sinais import padroes


def _serie(*trechos):
    """Concatena trechos lineares: (inicio, fim, pregões)."""
    return np.concatenate([np.linspace(a, b, n, endpoint=False) for a, b, n in trechos])


def test_topo_duplo_confirmado_no_rompimento():
    p = _serie((80, 100, 30), (100, 88, 20), (88, 100, 20), (100, 84, 25))   # rompe o vale (88)
    assert padroes.detectar(p) == "topo_duplo"


def test_fundo_duplo_confirmado_no_rompimento():
    p = _serie((120, 100, 30), (100, 112, 20), (112, 100, 20), (100, 116, 25))
    assert padroes.detectar(p) == "fundo_duplo"


def test_oco():
    p = _serie((80, 95, 20), (95, 88, 12), (88, 104, 15), (104, 88, 15), (88, 95, 12), (95, 82, 25))
    assert padroes.detectar(p) == "oco"


def test_oco_invertido():
    p = _serie((120, 105, 20), (105, 112, 12), (112, 96, 15), (96, 112, 15), (112, 105, 12), (105, 118, 25))
    assert padroes.detectar(p) == "oco_invertido"


def test_sem_padrao_em_tendencia_limpa_e_serie_curta():
    assert padroes.detectar(np.linspace(50, 80, 120)) is None
    assert padroes.detectar(np.linspace(50, 80, 30)) is None
    assert padroes.descrever("oco")["direcao_classica"] == "baixa"


def test_pontuacoes():
    assert cal.pontuacao_compra(1, 245) == 100 and cal.pontuacao_compra(245, 245) == 0
    assert cal.pontuacao_venda(80, 80) == 20                 # sem queda: 100 − compra
    assert cal.pontuacao_venda(50, 90) == 70                 # caiu 40 pontos: 50 + 20
    assert cal.pontuacao_venda(5, 100) == 100                # limitado a 100
    assert cal.faixa_de(100) == 90 and cal.faixa_de(37.5) == 30 and cal.faixa_de(-1e-12) == 0


def test_retorno_futuro_comeca_no_pregao_seguinte():
    datas = pd.bdate_range("2024-01-01", periods=10)
    r = pd.DataFrame({"X": [0.0, 0.0, 0.10, 0.10, 0, 0, 0, 0, 0, 0]}, index=datas)
    fut = cal.retornos_futuros(r, 2)
    # ranking no dia 0 -> compra no fechamento do dia 1 -> ganha os dias 2 e 3
    assert fut["X"].iloc[0] == pytest.approx(1.1 * 1.1 - 1)
    assert len(fut) == 10 - 2 - 1


def test_calibracao_reconhece_score_que_funciona_e_ignora_ruido():
    rng = np.random.default_rng(0)
    datas = pd.bdate_range("2019-01-01", periods=900)
    tickers = [f"A{i:03d}" for i in range(60)]
    qualidade = pd.Series(np.linspace(-1, 1, 60), index=tickers)          # score "verdadeiro" fixo
    retornos = pd.DataFrame(rng.normal(0, 0.01, (900, 60)) + 0.0004 * qualidade.to_numpy(), index=datas, columns=tickers)
    retornos["BOVA11"] = rng.normal(0, 0.008, 900)
    scores = pd.DataFrame([(d, t, qualidade[t]) for d in datas[::5] for t in tickers], columns=["data", "ticker", "score"])
    tab = cal.calibrar(scores, retornos)
    m1 = tab[tab["horizonte"] == 21].set_index("faixa_min")
    assert m1.loc[90, "excesso_medio"] > 0 > m1.loc[0, "excesso_medio"]
    assert m1.loc[90, "sinal"] == "compra" and m1.loc[0, "sinal"] == "venda"
    assert m1.loc[90, "comportamento"] == "tende a superar o mercado"
    # 12 meses com ~3,5 anos de dados: poucas janelas independentes -> sem sinal, mesmo que o efeito exista
    m12 = tab[tab["horizonte"] == 252]
    assert (m12["sinal"] == "sem sinal claro").all() and (m12["janelas_independentes"] < cal.JANELAS_MINIMAS).all()
    assert (m12["comportamento"] == "sem diferença comprovada em relação ao mercado").all()
