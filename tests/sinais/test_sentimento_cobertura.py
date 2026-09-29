import logging
from datetime import date, datetime, time, timezone

import pandas as pd
import pytest

from config import settings
from scripts import gerar_sinais
from src.db.tempo import iso_brt
from src.sinais import base, cobertura, sentimento
from tests.sinais.conftest import TS, dias_uteis, inserir_cotacoes


def classificador_falso(textos):
    """'alta' -> positivo, 'queda' -> negativo, resto neutro."""
    saida = []
    for t in textos:
        if "alta" in t:
            saida.append({"positivo": 0.9, "neutro": 0.05, "negativo": 0.05})
        elif "queda" in t:
            saida.append({"positivo": 0.1, "neutro": 0.1, "negativo": 0.8})
        else:
            saida.append({"positivo": 0.2, "neutro": 0.6, "negativo": 0.2})
    return saida


def inserir_noticia(conn, titulo, publicado: datetime, tickers=("PETR4",)):
    with conn:
        nid = conn.execute(
            "INSERT INTO noticias (titulo, url, fonte, publicado_em, disponivel_em, coletado_em, hash) "
            "VALUES (?, ?, 'rss_teste', ?, ?, ?, ?)",
            (titulo, f"https://n/{titulo}", iso_brt(publicado.date(), publicado.time()),
             iso_brt(publicado.date(), publicado.time()), TS, titulo),
        ).lastrowid
        for t in tickers:
            conn.execute("INSERT INTO noticias_ativos VALUES (?, ?, 'ticker_no_texto')", (nid, t))


@pytest.fixture
def conn_sent(conn):
    dias = dias_uteis(date(2026, 9, 1), 25)  # 01/09 (ter) em diante
    inserir_cotacoes(conn, "PETR4", dias, [30.0] * len(dias))
    inserir_noticia(conn, "PETR4 em alta", datetime(2026, 9, 2, 10, 0))
    inserir_noticia(conn, "PETR4 em queda", datetime(2026, 9, 2, 20, 0))   # após o corte das 19h -> dia 03
    inserir_noticia(conn, "PETR4 em alta de novo", datetime(2026, 9, 5, 12, 0))  # sábado -> segunda 07
    inserir_noticia(conn, "Mercado sem PETR4", datetime(2026, 9, 3, 9, 0), tickers=())
    assert sentimento.classificar_pendentes(conn, classificador_falso) == 4
    return conn, dias


def _v(s, nome, dia):
    linha = s[(s["nome"] == nome) & (s["data"] == pd.Timestamp(dia))]
    return linha["valor"].iloc[0] if not linha.empty else None


def test_classificacao_e_idempotente(conn_sent):
    conn, _ = conn_sent
    assert sentimento.classificar_pendentes(conn, classificador_falso) == 0
    r = conn.execute("SELECT rotulo, score FROM sentimento_noticias WHERE noticia_id = 2").fetchone()
    assert r["rotulo"] == "negativo" and r["score"] == pytest.approx(-0.7)


def test_agregacao_diaria(conn_sent):
    conn, _ = conn_sent
    s = sentimento.calcular(conn)
    assert _v(s, "sent_n_dia", date(2026, 9, 1)) is None            # antes do início da coleta
    assert _v(s, "sent_n_dia", date(2026, 9, 2)) == 1
    assert _v(s, "sent_media_dia", date(2026, 9, 2)) == pytest.approx(0.85)
    assert _v(s, "sent_media_dia", date(2026, 9, 3)) == pytest.approx(-0.7)  # notícia das 20h do dia 02
    assert _v(s, "sent_n_dia", date(2026, 9, 4)) == 0
    assert _v(s, "sent_media_dia", date(2026, 9, 4)) is None
    assert _v(s, "sent_n_dia", date(2026, 9, 7)) == 1                 # notícia de sábado
    assert _v(s, "sent_media_21d", date(2026, 9, 7)) == pytest.approx((0.85 - 0.7 + 0.85) / 3)
    assert _v(s, "sent_delta", date(2026, 9, 7)) == pytest.approx(0.85 - 1.0 / 3)


def test_anti_look_ahead_sentimento(conn_sent):
    conn, dias = conn_sent
    completo = sentimento.calcular(conn)
    for d in dias[1:8]:
        truncado = sentimento.calcular(conn, ate=base.corte(d))
        a = completo[completo["data"] == pd.Timestamp(d)].sort_values("nome").reset_index(drop=True)
        b = truncado[truncado["data"] == pd.Timestamp(d)].sort_values("nome").reset_index(drop=True)
        pd.testing.assert_frame_equal(a, b)


def test_relatorio_de_cobertura(conn_sent):
    conn, dias = conn_sent
    base.gravar(conn, sentimento.calcular(conn), sentimento.VERSOES)
    texto = cobertura.relatorio(conn)
    assert "sent_n_dia" in texto and "sentimento" in texto
    assert "4.0%" in texto  # sent_n_dia falta só no 1º de 25 pregões


@pytest.fixture
def logs_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "LOG_DIR", tmp_path / "logs")
    antes = list(logging.getLogger().handlers)
    yield
    raiz = logging.getLogger()
    for h in [h for h in raiz.handlers if h not in antes]:
        raiz.removeHandler(h)
        h.close()


def test_script_gerar_sinais_em_banco_vazio(tmp_path, logs_tmp, capsys):
    assert gerar_sinais.main(["--db", str(tmp_path / "b3.db")]) == 0
    assert "Nenhum sinal gravado" in capsys.readouterr().out
