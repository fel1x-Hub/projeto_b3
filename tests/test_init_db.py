import logging
import sqlite3

import pytest

from config import settings
from config.settings import carregar_ativos
from scripts.init_db import main
from src.db.migracoes import MIGRACOES


@pytest.fixture(autouse=True)
def logs_em_tmp(tmp_path, monkeypatch):
    """Direciona os logs para tmp e remove os handlers criados pelo script."""
    monkeypatch.setattr(settings, "LOG_DIR", tmp_path / "logs")
    antes = list(logging.getLogger().handlers)
    yield
    raiz = logging.getLogger()
    for h in [h for h in raiz.handlers if h not in antes]:
        raiz.removeHandler(h)
        h.close()


def _contagens(caminho):
    conn = sqlite3.connect(caminho)
    try:
        tabelas = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tabelas}
    finally:
        conn.close()


def test_roda_duas_vezes_sem_erro_nem_duplicata(tmp_path):
    db = tmp_path / "sub" / "b3.db"
    assert main(["--db", str(db)]) == 0
    primeira = _contagens(db)
    assert main(["--db", str(db)]) == 0
    assert _contagens(db) == primeira
    assert primeira["ativos"] == len(carregar_ativos())
    assert primeira["schema_versao"] == len(MIGRACOES)


def test_csv_invalido_retorna_erro(tmp_path):
    csv = tmp_path / "ativos.csv"
    csv.write_text("ticker,nome\nPETR4,Petrobras\n", encoding="utf-8")
    assert main(["--db", str(tmp_path / "b3.db"), "--ativos", str(csv)]) == 1
