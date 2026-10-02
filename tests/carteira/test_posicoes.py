import pandas as pd
import pytest

from src.carteira.posicoes import calcular, quantidade_em


def ops(*linhas):
    return pd.DataFrame(linhas, columns=["ticker", "tipo", "data", "quantidade", "preco", "custos"])


def provs(*linhas):
    return pd.DataFrame(linhas, columns=["ticker", "tipo", "data_ex", "valor", "fator"])


def test_preco_medio_com_custos_e_venda_que_nao_muda_o_medio():
    p = calcular(ops(("PETR4", "compra", "2026-01-05", 100, 30.0, 10.0),
                     ("PETR4", "compra", "2026-02-05", 100, 40.0, 10.0),
                     ("PETR4", "venda", "2026-03-05", 50, 50.0, 5.0)))["PETR4"]
    assert p.quantidade == 150
    assert p.preco_medio == pytest.approx(7020 / 200)                  # (3010 + 4010) / 200
    assert p.lucro_realizado == pytest.approx(50 * 50 - 5 - 50 * 35.1)
    assert p.primeira_compra.isoformat() == "2026-01-05"


def test_desdobramento_ajusta_quantidade_e_dividendo_conta_so_quem_tinha_antes_da_data_ex():
    p = calcular(ops(("WEGE3", "compra", "2026-01-05", 100, 40.0, 0.0),
                     ("WEGE3", "compra", "2026-03-10", 10, 21.0, 0.0)),      # comprou NA data ex: sem dividendo
                 provs(("WEGE3", "desdobramento", "2026-02-01", None, 2.0),
                       ("WEGE3", "dividendo", "2026-03-10", 0.5, None),
                       ("WEGE3", "dividendo", "2025-12-01", 9.9, None)))["WEGE3"]  # antes da 1ª compra
    assert p.quantidade == 210
    assert p.custo == pytest.approx(4000 + 210)
    assert p.proventos == pytest.approx(200 * 0.5)


def test_venda_maior_que_a_posicao_avisa_e_zera():
    p = calcular(ops(("VALE3", "compra", "2026-01-05", 10, 60.0, 0.0),
                     ("VALE3", "venda", "2026-01-06", 15, 62.0, 0.0)))["VALE3"]
    assert p.quantidade == 0 and p.custo == 0 and p.preco_medio is None
    assert p.lucro_realizado == pytest.approx(20.0) and "maior que a posição" in p.avisos[0]


def test_quantidade_por_dia():
    q = quantidade_em(ops(("ITUB4", "compra", "2026-01-05", 100, 30.0, 0.0),
                          ("ITUB4", "venda", "2026-01-07", 40, 31.0, 0.0)), None,
                      pd.DatetimeIndex(["2026-01-02", "2026-01-05", "2026-01-07"]))
    assert q["ITUB4"].tolist() == [0, 100, 60]


def test_simular_venda_ir():
    from src.carteira.servico import simular_venda
    v = simular_venda(15000.0, 10000.0, True)
    assert v["lucro"] == 5000 and v["ir_se_tributado"] == 750 and v["isento_se_so_esta_venda"]
    assert simular_venda(30000.0, 20000.0, True)["isento_se_so_esta_venda"] is False
    assert simular_venda(8000.0, 10000.0, True)["ir_se_tributado"] == 0
    assert simular_venda(12000.0, 10000.0, False)["ir_se_tributado"] is None     # FII/ETF: regra própria
    assert simular_venda(None, 10000.0, True) is None
