"""Postgres na nuvem (Neon) com a mesma interface que a API usa do sqlite3 (etapa 8).

A API escolhe o banco pela variável DATABASE_URL:
- vazia: SQLite local (desenvolvimento, app desktop offline);
- postgresql://...: Postgres (produção). Só o "modelo de leitura" (o que as
  telas mostram), a carteira e os relatórios vivem lá; o banco de trabalho
  completo continua SQLite, no pipeline (ver scripts/publicar_nuvem.py).

O SQL da API é escrito uma vez, com `?` e funções comuns aos dois bancos;
aqui ele é traduzido (`?` -> `%s`). Linhas aceitam índice e nome, como sqlite3.Row.
"""

import os
import threading

import pandas as pd

from src.db.conexao import conectar


class Linha(tuple):
    """Tupla que também aceita linha["coluna"] (igual a sqlite3.Row)."""

    def __new__(cls, valores, nomes):
        obj = super().__new__(cls, valores)
        obj._nomes = nomes
        return obj

    def __getitem__(self, chave):
        if isinstance(chave, str):
            return tuple.__getitem__(self, self._nomes[chave])
        return tuple.__getitem__(self, chave)

    def keys(self):
        return list(self._nomes)


def traduzir(sql: str) -> str:
    """Placeholders do sqlite3 (?) para os do psycopg (%s); % literal vira %%."""
    return sql.replace("%", "%%").replace("?", "%s")


class _Cursor:
    def __init__(self, cur):
        self._cur = cur
        self.description = cur.description
        self.rowcount = cur.rowcount
        nomes = [d[0] for d in cur.description] if cur.description else []
        self._nomes = {n: i for i, n in enumerate(nomes)}

    def _linha(self, valores):
        return None if valores is None else Linha(valores, self._nomes)

    def fetchone(self):
        return self._linha(self._cur.fetchone())

    def fetchall(self):
        return [self._linha(v) for v in self._cur.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())


class ConexaoPG:
    """Embrulha uma conexão psycopg (autocommit) com a interface usada pela API."""

    def __init__(self, conn, devolver=None):
        self._conn = conn
        self._devolver = devolver
        self._transacao = None

    def execute(self, sql: str, params=()) -> _Cursor:
        cur = self._conn.cursor()
        cur.execute(traduzir(sql), tuple(params))
        return _Cursor(cur)

    def executemany(self, sql: str, linhas) -> None:
        with self._conn.cursor() as cur:
            cur.executemany(traduzir(sql), [tuple(l) for l in linhas])

    def __enter__(self):  # `with conn:` = uma transação, como no sqlite3
        self._transacao = self._conn.transaction()
        self._transacao.__enter__()
        return self

    def __exit__(self, *exc):
        t, self._transacao = self._transacao, None
        return t.__exit__(*exc)

    def close(self) -> None:
        if self._devolver:
            self._devolver(self._conn)
        else:
            self._conn.close()


_pool = None
_trava = threading.Lock()


def _pool_pg(url: str):
    global _pool
    with _trava:
        if _pool is None:
            from psycopg_pool import ConnectionPool
            # Neon desliga a computação ociosa e derruba conexões: check() testa antes de entregar
            _pool = ConnectionPool(url, min_size=1, max_size=int(os.getenv("DB_POOL_MAX", "4")),
                                   kwargs={"autocommit": True}, check=ConnectionPool.check_connection, open=True)
        return _pool


def fechar_pool() -> None:
    """Fecha o pool (testes trocam de banco; a API em produção usa um só)."""
    global _pool
    with _trava:
        if _pool is not None:
            _pool.close()
            _pool = None


def conectar_api(caminho=None):
    """Conexão para a API: Postgres se DATABASE_URL estiver definida, senão o SQLite local."""
    url = os.getenv("DATABASE_URL", "")
    if url and caminho is None:
        pool = _pool_pg(url)
        return ConexaoPG(pool.getconn(), devolver=pool.putconn)
    return conectar(caminho, entre_threads=True)


def ler_df(conn, sql: str, params=(), parse_dates=None) -> pd.DataFrame:
    """pd.read_sql_query que funciona nos dois bancos (a API não usa SQLAlchemy)."""
    cur = conn.execute(sql, params)
    colunas = [d[0] for d in cur.description]
    df = pd.DataFrame([tuple(l) for l in cur.fetchall()], columns=colunas)
    for c in parse_dates or []:
        df[c] = pd.to_datetime(df[c])
    return df

