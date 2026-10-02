import sqlite3
import tarfile

from scripts.empacotar_banco import empacotar
from src.db.migracoes import migrar
from src.db.conexao import conectar

TS = "2026-10-01T12:00:00+00:00"


def test_pacote_sai_sem_carteira_e_com_modelos(tmp_path):
    origem = tmp_path / "b3.db"
    conn = conectar(origem)
    migrar(conn)
    with conn:
        conn.execute("INSERT INTO carteira_operacoes (ticker, tipo, data, quantidade, preco, custos, origem, criado_em) "
                     "VALUES ('PETR4', 'compra', '2026-01-05', 100, 30, 0, 'manual', ?)", (TS,))
        conn.execute("INSERT INTO macro (serie, data, valor, fonte, disponivel_em, coletado_em) "
                     "VALUES ('cdi', '2026-01-05', 0.05, 'bcb', ?, ?)", (TS, TS))
    conn.close()
    modelos = tmp_path / "modelos"
    modelos.mkdir()
    (modelos / "lgbm-v1_2026-10-01.txt").write_text("modelo")
    pacote = empacotar(origem, modelos, tmp_path / "banco.tar.gz")

    with tarfile.open(pacote) as tar:
        assert {"data/b3.db", "data/modelos/lgbm-v1_2026-10-01.txt"} <= set(tar.getnames())
        tar.extractall(tmp_path / "x", filter="data")
    copia = sqlite3.connect(tmp_path / "x" / "data" / "b3.db")
    assert copia.execute("SELECT COUNT(*) FROM carteira_operacoes").fetchone()[0] == 0
    assert copia.execute("SELECT COUNT(*) FROM macro").fetchone()[0] == 1
    copia.close()
    original = sqlite3.connect(origem)
    assert original.execute("SELECT COUNT(*) FROM carteira_operacoes").fetchone()[0] == 1   # original intacto
    original.close()
