import logging
from datetime import date

import pytest

from config import settings
from scripts import coletar
from tests.conftest import TS


@pytest.fixture(autouse=True)
def isolar(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "LOG_DIR", tmp_path / "logs")
    antes = list(logging.getLogger().handlers)
    yield
    raiz = logging.getLogger()
    for h in [h for h in raiz.handlers if h not in antes]:
        raiz.removeHandler(h)
        h.close()


def _fonte_cotacoes(conn, desde):
    with conn:
        conn.execute("INSERT OR IGNORE INTO cotacoes (ticker, data, fechamento, fonte, disponivel_em, coletado_em) "
                     "VALUES ('PETR4', '2026-01-02', 30.0, 'teste', ?, ?)", (TS, TS))
    return 1


def _fonte_quebrada(conn, desde):
    raise ConnectionError("fora do ar")


def test_fonte_quebrada_nao_para_as_outras(tmp_path, monkeypatch, capsys):
    chamadas = []
    monkeypatch.setattr(coletar, "FONTES", [
        ("quebrada", _fonte_quebrada, "b3"),
        ("cotacoes", lambda c, d: chamadas.append(d) or _fonte_cotacoes(c, d), "b3"),
        ("rss", lambda c, d: 0, "rss"),
    ])
    codigo = coletar.main(["--db", str(tmp_path / "b3.db"), "--desde", "2024-01-01", "--fonte", "b3"])
    assert codigo == 1                                   # alguma fonte falhou por completo
    assert chamadas == [date(2024, 1, 1)]
    saida = capsys.readouterr().out
    assert "quebrada       falha" in saida and "cotacoes       sucesso" in saida
    assert "rss " not in saida.split("=== Registros")[0]  # filtrada pelo --fonte
    assert "PETR4" in saida


def test_sucesso_retorna_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(coletar, "FONTES", [("cotacoes", _fonte_cotacoes, "b3")])
    assert coletar.main(["--db", str(tmp_path / "b3.db")]) == 0
    # banco novo: o cadastro CVM não rodou, então o resumo avisa
    assert "Ações sem código CVM" in capsys.readouterr().out.split("=== Alertas ===")[1]


def test_desde_padrao_em_29_de_fevereiro():
    assert coletar.desde_padrao(date(2028, 2, 29), 5) == date(2023, 2, 28)
    assert coletar.desde_padrao(date(2026, 9, 29), 5) == date(2021, 9, 29)
