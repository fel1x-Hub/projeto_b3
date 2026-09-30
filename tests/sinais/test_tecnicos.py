from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.sinais import base, tecnicos
from src.sinais.precos import retornos_totais
from tests.sinais.conftest import dias_uteis, inserir_cotacoes, inserir_provento


def _cot(datas, precos, volumes=None):
    return pd.DataFrame({"data": pd.to_datetime(datas), "fechamento": precos,
                         "volume": volumes if volumes is not None else [100] * len(precos)})


def _prov(*eventos):
    return pd.DataFrame([{"tipo": t, "data_ex": pd.Timestamp(d), "valor": v, "fator": f} for t, d, v, f in eventos],
                        columns=["tipo", "data_ex", "valor", "fator"])


def test_retorno_total_com_dividendo_e_desdobramento_no_mesmo_dia():
    # dia 3: desdobramento 2:1 e dividendo de 0,20 por ação antiga
    cot = _cot(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"], [10.0, 11.0, 5.4, 5.5])
    prov = _prov(("desdobramento", "2024-01-03", None, 2.0), ("dividendo", "2024-01-03", 0.20, None))
    r = retornos_totais(cot, prov)
    assert np.isnan(r.iloc[0])
    assert r.iloc[1] == pytest.approx(0.10)
    assert r.iloc[2] == pytest.approx(0.0)           # (5,4 x 2 + 0,20) / 11 - 1
    assert r.iloc[3] == pytest.approx(5.5 / 5.4 - 1)


def test_evento_em_dia_sem_pregao_vai_para_o_pregao_seguinte():
    cot = _cot(["2024-01-05", "2024-01-08"], [10.0, 9.5])       # sexta e segunda
    prov = _prov(("dividendo", "2024-01-06", 0.5, None))        # data ex no sábado
    assert retornos_totais(cot, prov).iloc[1] == pytest.approx(0.0)


def test_rsi_calculado_a_mao():
    # deltas 1, -1, 2; Wilder com n=2 (alfa 0,5): ganhos 0,5 -> 1,25; perdas 0,5 -> 0,25
    r = tecnicos.rsi(pd.Series([1.0, 2.0, 1.0, 3.0]), 2)
    assert np.isnan(r.iloc[1])
    assert r.iloc[2] == pytest.approx(50.0)
    assert r.iloc[3] == pytest.approx(100 - 100 / 6)


def test_sinais_em_serie_de_crescimento_constante():
    dias = dias_uteis(date(2024, 1, 2), 260)
    precos = 10 * 1.01 ** np.arange(len(dias))
    s = tecnicos.sinais_ativo(_cot(dias, precos), _prov())
    ultimo = s.iloc[-1]
    assert ultimo["ret_5d"] == pytest.approx(1.01 ** 5 - 1)
    assert ultimo["ret_63d"] == pytest.approx(1.01 ** 63 - 1)
    media21 = np.mean(1.01 ** -np.arange(21))                   # média das últimas 21 / preço atual
    assert ultimo["dist_mm21"] == pytest.approx(1 / media21 - 1)
    assert ultimo["vol_21d"] == pytest.approx(0.0, abs=1e-12)   # retorno constante: sem volatilidade
    assert ultimo["rsi14"] == pytest.approx(100.0)              # só altas
    assert s["dist_mm200"].notna().sum() == len(dias) - 199     # só com janela completa


def test_volume_financeiro_relativo_ignora_desdobramento():
    dias = dias_uteis(date(2024, 1, 2), 30)
    precos = [20.0] * 25 + [10.0] * 5          # desdobramento 2:1 no pregão 25...
    volumes = [100] * 25 + [200] * 5           # ...dobra a quantidade, mas não o volume financeiro
    s = tecnicos.sinais_ativo(_cot(dias, precos, volumes), _prov(("desdobramento", dias[25], None, 2.0)))
    assert s["vol_fin_rel21"].dropna().tolist() == pytest.approx([1.0] * 9)
    assert s["ret_1d"].iloc[25] == pytest.approx(0.0)  # índice de retorno total não salta


def test_anti_look_ahead(conn_precos):
    conn_precos, dias = conn_precos
    """Sinais de D calculados com o banco completo == calculados com o banco
    truncado em D (só disponivel_em <= corte de D)."""
    completo = tecnicos.calcular(conn_precos)
    for d in (dias[149], dias[150], dias[199], dias[200], dias[250]):  # véspera e dia de cada evento
        truncado = tecnicos.calcular(conn_precos, ate=base.corte(d))
        a = completo[completo["data"] == pd.Timestamp(d)].sort_values("nome").reset_index(drop=True)
        b = truncado[truncado["data"] == pd.Timestamp(d)].sort_values("nome").reset_index(drop=True)
        esperado = len(tecnicos.NOMES) - (1 if d < dias[199] else 0)  # mm200 só com 200 pregões
        assert len(a) == esperado
        pd.testing.assert_frame_equal(a, b)


def test_dados_futuros_nao_alteram_o_passado(conn_precos):
    conn_precos, dias = conn_precos
    """Envenena o futuro (preços absurdos e proventos) e confere que D não muda."""
    d = dias[250]
    antes = tecnicos.calcular(conn_precos, ate=base.corte(d))
    futuros = dias_uteis(date(2026, 1, 1), 5)
    inserir_cotacoes(conn_precos, "PETR4", futuros, [1e6] * 5)
    inserir_provento(conn_precos, "PETR4", futuros[2], valor=5e5)
    inserir_provento(conn_precos, "PETR4", futuros[3], fator=100.0)
    depois = tecnicos.calcular(conn_precos)
    x = antes[antes["data"] <= pd.Timestamp(d)].sort_values(["data", "nome"]).reset_index(drop=True)
    y = depois[depois["data"] <= pd.Timestamp(d)].sort_values(["data", "nome"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(x, y)


def test_gravar_e_idempotente(conn_precos):
    conn_precos, dias = conn_precos
    sinais = tecnicos.calcular(conn_precos)
    n = base.gravar(conn_precos, sinais, tecnicos.VERSOES)
    assert base.gravar(conn_precos, sinais, tecnicos.VERSOES) == n
    assert conn_precos.execute("SELECT COUNT(*) FROM sinais").fetchone()[0] == n
    linha = conn_precos.execute("SELECT data, disponivel_em FROM sinais LIMIT 1").fetchone()
    assert linha["disponivel_em"] == base.corte(date.fromisoformat(linha["data"]))


def test_grupamento_nao_registrado_nao_vira_retorno():
    # KRSA3/OIBR3 reais: grupamento 10:1 sem registro -> preço x10 num dia
    cot = _cot(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"], [0.50, 0.52, 5.1, 5.0])
    r = retornos_totais(cot, _prov())
    assert r.iloc[2] == 0.0                              # salto contábil neutralizado
    assert r.iloc[3] == pytest.approx(5.0 / 5.1 - 1)     # dias seguintes normais


def test_colapso_real_e_mantido():
    # Americanas em 12/01/2023: -77% (razão 0,23, longe de 1/4 e de 1/5)
    cot = _cot(["2023-01-11", "2023-01-12"], [12.00, 2.72])
    assert retornos_totais(cot, _prov()).iloc[1] == pytest.approx(2.72 / 12 - 1)


def test_criterio_de_evento_nao_registrado():
    from src.sinais.precos import evento_nao_registrado
    assert evento_nao_registrado(10.2) and evento_nao_registrado(1 / 3.05) and evento_nao_registrado(39.75 / 1.0)
    assert not evento_nao_registrado(1.3) and not evento_nao_registrado(0.23) and not evento_nao_registrado(2.5)


def test_alta_de_mais_de_3x_sem_evento_e_neutralizada():
    # TRAD3 real: +665% num dia (grupamento com razão distorcida)
    cot = _cot(["2024-07-19", "2024-07-22"], [1.00, 7.65])
    assert retornos_totais(cot, _prov()).iloc[1] == 0.0


def test_gravar_incremental_preserva_historico(conn_precos):
    conn_precos, dias = conn_precos
    sinais = tecnicos.calcular(conn_precos)
    base.gravar(conn_precos, sinais, tecnicos.VERSOES)
    antigo = conn_precos.execute("SELECT calculado_em FROM sinais WHERE data = ? LIMIT 1", (dias[100].isoformat(),)).fetchone()[0]
    total = conn_precos.execute("SELECT COUNT(*) FROM sinais").fetchone()[0]
    import time as _t; _t.sleep(1.1)
    n = base.gravar(conn_precos, sinais, tecnicos.VERSOES, desde=dias[300])
    assert n == len(sinais[sinais["data"] >= pd.Timestamp(dias[300])].dropna())
    assert conn_precos.execute("SELECT COUNT(*) FROM sinais").fetchone()[0] == total          # nada perdido
    assert conn_precos.execute("SELECT calculado_em FROM sinais WHERE data = ? LIMIT 1",
                               (dias[100].isoformat(),)).fetchone()[0] == antigo            # antigo intacto
