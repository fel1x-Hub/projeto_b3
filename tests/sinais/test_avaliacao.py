import csv

import pytest

from scripts import avaliar_sentimento
from src.sinais import avaliacao, sentimento
from tests.sinais.test_sentimento_cobertura import classificador_falso, inserir_noticia


def test_metricas_calculadas_a_mao():
    reais = ["positivo", "positivo", "neutro", "neutro", "negativo", "negativo"]
    prev = ["positivo", "neutro", "neutro", "neutro", "negativo", "positivo"]
    m = avaliacao.metricas(reais, prev)
    assert m["acuracia"] == pytest.approx(4 / 6)
    # positivo: P = 1/2, R = 1/2 -> F1 0,5 | neutro: P = 2/3, R = 1 -> F1 0,8 | negativo: P = 1, R = 1/2 -> F1 2/3
    assert m["por_classe"]["positivo"]["f1"] == pytest.approx(0.5)
    assert m["por_classe"]["neutro"]["f1"] == pytest.approx(0.8)
    assert m["por_classe"]["negativo"]["f1"] == pytest.approx(2 / 3)
    assert m["f1_macro"] == pytest.approx((0.5 + 0.8 + 2 / 3) / 3)
    assert m["matriz"]["negativo"]["positivo"] == 1


def test_classe_nunca_prevista_tem_f1_zero():
    m = avaliacao.metricas(["positivo", "neutro"], ["neutro", "neutro"])
    assert m["por_classe"]["positivo"]["f1"] == 0.0


def test_relatorio_de_avaliacao(conn, tmp_path):
    from datetime import datetime
    inserir_noticia(conn, "PETR4 em alta", datetime(2026, 9, 2, 10, 0))
    inserir_noticia(conn, "PETR4 em queda", datetime(2026, 9, 2, 11, 0))
    sentimento.classificar_pendentes(conn, classificador_falso)
    rotulos = tmp_path / "r.csv"
    with open(rotulos, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["noticia_id", "fonte", "titulo", "rotulo", "rotulado_por"])
        w.writerow([1, "x", "PETR4 em alta", "positivo", "claude"])
        w.writerow([2, "x", "PETR4 em queda", "neutro", "claude"])
    texto, m = avaliar_sentimento.relatorio(conn, rotulos)
    assert m["acuracia"] == pytest.approx(0.5)
    assert "rotuladas por: claude" in texto
    assert "| 2 | PETR4 em queda | neutro | negativo |" in texto  # divergência listada
