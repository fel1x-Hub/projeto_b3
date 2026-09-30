"""Conexão com o banco SQLite."""

import logging
import sqlite3
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)


def conectar(caminho: Path | str | None = None) -> sqlite3.Connection:
    """Abre o banco (criando a pasta se preciso) com as configurações do projeto.

    - foreign_keys=ON: o SQLite vem com FKs desligadas por padrão.
    - journal_mode=WAL: leituras não bloqueiam a escrita (útil quando a API da
      etapa 7 ler enquanto a coleta grava).
    - row_factory=Row: acesso às colunas por nome.
    """
    caminho = Path(caminho) if caminho else settings.DB_PATH
    caminho.parent.mkdir(parents=True, exist_ok=True)
    # espera até 60 s se outra conexão estiver escrevendo (ex.: coleta e extração
    # de eventos rodando ao mesmo tempo), em vez de falhar com 'database is locked'
    conn = sqlite3.connect(caminho, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    logger.debug("Conectado a %s", caminho)
    return conn
