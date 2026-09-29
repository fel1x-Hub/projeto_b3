from datetime import date, time

import numpy as np
import pandas as pd
import pytest

from src.db.tempo import iso_brt
from src.sinais import base
from src.sinais import fundamentalistas as f
from tests.sinais.conftest import TS, dias_uteis, inserir_cotacoes, inserir_provento

COD = "9512"


def _linhas_doc(ref, receita=None, ebit=None, lucro=None, da=None, pl=None, divida=None, caixa=None,
                acoes=None, trimestre=None):
    """Linhas no formato de `demonstracoes` para um documento de empresa não financeira.
    Fluxos são acumulados do ano (data_ini = 1º de janeiro); `trimestre` acrescenta
    uma linha só do trimestre, que NÃO deve ser usada."""
    ini = ref[:4] + "-01-01"
    L = []

    def fluxo(dem, cd, ds, v):
        if v is not None:
            L.append((dem, 1, ini, ref, cd, ds, v))
            if trimestre is not None:
                L.append((dem, 1, trimestre, ref, cd, ds, v / 10))

    fluxo("DRE", "3.01", "Receita de Venda de Bens e/ou Serviços", receita)
    fluxo("DRE", "3.05", "Resultado Antes do Resultado Financeiro e dos Tributos", ebit)
    if lucro is not None:
        fluxo("DRE", "3.11", "Lucro/Prejuízo Consolidado do Período", lucro * 1.1)
        fluxo("DRE", "3.11.01", "Atribuído a Sócios da Empresa Controladora", lucro)
    fluxo("DVA", "7.04.01", "Depreciação, Amortização e Exaustão", -da if da is not None else None)
    if pl is not None:
        L.append(("BPP", 1, None, ref, "2.03", "Patrimônio Líquido Consolidado", pl * 1.2))
        L.append(("BPP", 1, None, ref, "2.03.09", "Participação dos Acionistas Não Controladores", pl * 0.2))
    if divida is not None:
        L.append(("BPP", 1, None, ref, "2.01.04", "Empréstimos e Financiamentos", divida / 2))
        L.append(("BPP", 1, None, ref, "2.02.01", "Empréstimos e Financiamentos", divida / 2))
    if caixa is not None:
        L.append(("BPA", 1, None, ref, "1.01.01", "Caixa e Equivalentes de Caixa", caixa))
    if acoes is not None:
        L.append(("CAPITAL", 0, None, ref, "QT_ACAO_TOTAL_CAP_INTEGR", "Total", acoes))
        L.append(("CAPITAL", 0, None, ref, "QT_ACAO_TOTAL_TESOURO", "Tesouraria", 0.0))
    return L


def _df(linhas, ref="2024-06-30"):
    return pd.DataFrame(linhas, columns=["demonstrativo", "consolidado", "data_ini", "data_fim",
                                         "cd_conta", "ds_conta", "valor"])


def inserir_doc(conn, tipo, ref, versao, entrega: date, **valores):
    with conn:
        conn.executemany(
            "INSERT INTO demonstracoes (codigo_cvm, tipo_doc, data_referencia, versao, demonstrativo, consolidado, "
            "data_ini, data_fim, cd_conta, ds_conta, valor, disponivel_em, coletado_em) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(COD, tipo, ref, versao, *l, iso_brt(entrega, time(23, 59, 59)), TS)
             for l in _linhas_doc(ref, **valores)],
        )


# ------------------------------------------------------------------ extração

def test_extrai_acumulado_do_ano_e_desconta_minoritarios():
    doc = _df(_linhas_doc("2024-06-30", receita=1000, ebit=300, lucro=150, da=50, pl=2000,
                          divida=800, caixa=200, acoes=10, trimestre="2024-04-01"))
    v = f.extrair_documento(doc, "2024-06-30")
    assert (v["receita"], v["ebit"], v["lucro"], v["da"]) == (1000, 300, 150, 50)  # acumulado, não trimestre
    assert v["pl"] == pytest.approx(2000)                                           # total - não controladores
    assert (v["divida"], v["caixa"], v["acoes"], v["financeira"]) == (800, 200, 10, False)


def test_extrai_contas_de_banco_pela_descricao():
    # layout do Itaú: lucro em 3.09/3.09.01, PL em 2.08
    doc = _df([
        ("DRE", 1, "2025-01-01", "2025-12-31", "3.01", "Receitas da Intermediação Financeira", 387.0),
        ("DRE", 1, "2025-01-01", "2025-12-31", "3.09", "Lucro/Prejuízo Consolidado do Período", 45.85),
        ("DRE", 1, "2025-01-01", "2025-12-31", "3.09.01", "Atribuído a Sócios da Empresa Controladora", 44.86),
        ("BPP", 1, None, "2025-12-31", "2.03", "Passivos Financeiros ao Custo Amortizado", 2350.0),
        ("BPP", 1, None, "2025-12-31", "2.08", "Patrimônio Líquido Consolidado", 215.08),
        ("BPP", 1, None, "2025-12-31", "2.08.09", "Participação dos Acionistas Não Controladores", 10.57),
    ])
    v = f.extrair_documento(doc, "2025-12-31")
    assert v["financeira"] and v["lucro"] == pytest.approx(44.86)
    assert v["pl"] == pytest.approx(215.08 - 10.57)
    assert np.isnan(v["receita"]) and np.isnan(v["ebit"])  # sem métricas operacionais para banco


def test_linha_de_controladores_zerada_usa_conta_mae():
    # Sabesp: sem minoritários, deixa 3.11.01 zerado
    doc = _df([
        ("DRE", 1, "2023-01-01", "2023-12-31", "3.11", "Lucro/Prejuízo Consolidado do Período", 3.5),
        ("DRE", 1, "2023-01-01", "2023-12-31", "3.11.01", "Atribuído a Sócios da Empresa Controladora", 0.0),
    ])
    assert f.extrair_documento(doc, "2023-12-31")["lucro"] == pytest.approx(3.5)


def test_ttm_calculado_a_mao():
    docs = {
        "2023-06-30": pd.Series({"lucro": 40.0}),
        "2023-12-31": pd.Series({"lucro": 100.0}),
        "2024-06-30": pd.Series({"lucro": 60.0}),
    }
    assert f.ttm(docs, "2024-06-30", "lucro") == 60 + 100 - 40
    assert f.ttm(docs, "2023-12-31", "lucro") == 100
    assert np.isnan(f.ttm(docs, "2023-06-30", "lucro"))  # falta o ano anterior


# ------------------------------------------------------------------ ponto-no-tempo

@pytest.fixture
def conn_fund(conn):
    with conn:
        conn.execute("UPDATE ativos SET codigo_cvm = ? WHERE ticker = 'PETR4'", (COD,))
    dias = dias_uteis(date(2024, 1, 2), 200)
    inserir_cotacoes(conn, "PETR4", dias, [20.0] * len(dias))
    base_doc = dict(receita=1000, ebit=300, da=50, divida=800, caixa=200, acoes=1000)
    inserir_doc(conn, "ITR", "2023-06-30", 1, date(2023, 8, 10), lucro=40, pl=5000, **base_doc)
    inserir_doc(conn, "DFP", "2023-12-31", 1, date(2024, 3, 1), lucro=100, pl=5000, **{**base_doc, "receita": 2000})
    inserir_doc(conn, "ITR", "2024-06-30", 1, date(2024, 8, 9), lucro=60, pl=5000, **base_doc)
    inserir_doc(conn, "ITR", "2024-06-30", 2, date(2024, 9, 2), lucro=80, pl=5000, **base_doc)  # reapresentação
    return conn, dias


def _valor(sinais, nome, dia):
    linha = sinais[(sinais["nome"] == nome) & (sinais["data"] == pd.Timestamp(dia))]
    return linha["valor"].iloc[0] if not linha.empty else None


def test_versoes_valem_a_partir_da_entrega(conn_fund):
    conn, _ = conn_fund
    s = f.calcular(conn)
    assert _valor(s, "fund_pl", date(2024, 2, 29)) is None               # nada disponível antes da DFP
    assert _valor(s, "fund_pl", date(2024, 3, 1)) is None                # DFP entregue às 23:59 -> só no dia seguinte
    assert _valor(s, "fund_pl", date(2024, 3, 4)) == pytest.approx(20_000 / 100)          # lucro TTM = DFP
    assert _valor(s, "fund_pl", date(2024, 8, 12)) == pytest.approx(20_000 / (60 + 100 - 40))  # v1
    assert _valor(s, "fund_pl", date(2024, 9, 3)) == pytest.approx(20_000 / (80 + 100 - 40))   # v2
    assert _valor(s, "fund_pvp", date(2024, 9, 3)) == pytest.approx(20_000 / 5000)


def test_anti_look_ahead_fundamentalistas(conn_fund):
    conn, dias = conn_fund
    completo = f.calcular(conn)
    for d in (date(2024, 3, 4), date(2024, 8, 9), date(2024, 8, 12), date(2024, 9, 2), date(2024, 9, 3)):
        truncado = f.calcular(conn, ate=base.corte(d))
        a = completo[completo["data"] == pd.Timestamp(d)].sort_values("nome").reset_index(drop=True)
        b = truncado[truncado["data"] == pd.Timestamp(d)].sort_values("nome").reset_index(drop=True)
        pd.testing.assert_frame_equal(a, b)


def test_acoes_em_milhares_e_desdobramento_posterior(conn_fund):
    conn, dias = conn_fund
    with conn:  # empresa passa a informar ações em milhares
        conn.execute("UPDATE demonstracoes SET valor = valor / 1000 WHERE demonstrativo = 'CAPITAL'")
    inserir_provento(conn, "PETR4", date(2024, 9, 16), fator=2.0)  # desdobramento depois da data de referência
    with conn:
        conn.execute("UPDATE cotacoes SET fechamento = 10.0 WHERE data >= '2024-09-16'")
    s = f.calcular(conn)
    assert _valor(s, "fund_pvp", date(2024, 9, 3)) == pytest.approx(4.0)   # escala detectada (1.000 ações x 20 / 5.000)
    assert _valor(s, "fund_pvp", date(2024, 9, 17)) == pytest.approx(4.0)  # 2.000 ações x 10 / 5.000
