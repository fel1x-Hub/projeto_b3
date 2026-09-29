import pytest

from src.db.conexao import conectar
from src.db.migracoes import migrar

TS = "2026-01-02T21:00:00+00:00"


@pytest.fixture
def conn_vazia(tmp_path):
    """Conexão com um banco novo, sem schema. Nunca toca em data/."""
    conn = conectar(tmp_path / "teste.db")
    yield conn
    conn.close()


@pytest.fixture
def conn(conn_vazia):
    """Conexão com o schema completo aplicado e um ativo (PETR4) cadastrado."""
    migrar(conn_vazia)
    with conn_vazia:
        conn_vazia.execute(
            "INSERT INTO ativos (ticker, nome, ativo, criado_em, atualizado_em) "
            "VALUES ('PETR4', 'Petrobras', 1, ?, ?)",
            (TS, TS),
        )
    return conn_vazia
