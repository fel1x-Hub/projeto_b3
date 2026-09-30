"""Migrações simples do schema.

Cada migração é um par (versão, SQL). As versões aplicadas ficam na tabela
`schema_versao`; `migrar()` aplica apenas as pendentes, em ordem, cada uma em
sua própria transação. Rodar de novo não faz nada, e por isso é idempotente.

Para mudar o schema: acrescente uma nova versão ao fim de MIGRACOES. Nunca
edite uma migração já aplicada.
"""

import logging
import sqlite3

from src.db.schema import SCHEMA_V1, SCHEMA_V2, SCHEMA_V3, SCHEMA_V4, SCHEMA_V5, SCHEMA_V6, SCHEMA_V7

logger = logging.getLogger(__name__)

MIGRACOES: list[tuple[int, str]] = [
    (1, SCHEMA_V1),
    (2, SCHEMA_V2),  # etapa 2: proventos, demonstracoes, ativos.apelidos/tipo
    (3, SCHEMA_V3),  # etapa 2: documentos.assunto
    (4, SCHEMA_V4),  # etapa 3: sinais, sentimento, eventos e cache do LLM
    (5, SCHEMA_V5),  # universo ampliado: ativos.origem e tabela universo
    (6, SCHEMA_V6),  # etapa 4: tabela ranking
    (7, SCHEMA_V7),  # etapa 5: paper trading
]

_CRIAR_CONTROLE = """
CREATE TABLE IF NOT EXISTS schema_versao (
    versao     INTEGER PRIMARY KEY,
    aplicada_em TEXT NOT NULL
)
"""


def versao_atual(conn: sqlite3.Connection) -> int:
    conn.execute(_CRIAR_CONTROLE)
    return conn.execute("SELECT COALESCE(MAX(versao), 0) FROM schema_versao").fetchone()[0]


def migrar(conn: sqlite3.Connection, migracoes: list[tuple[int, str]] | None = None) -> int:
    """Aplica as migrações pendentes e devolve a versão final do schema."""
    migracoes = MIGRACOES if migracoes is None else migracoes
    versoes = [v for v, _ in migracoes]
    if versoes != sorted(set(versoes)):
        raise ValueError(f"versões de migração devem ser únicas e crescentes: {versoes}")

    atual = versao_atual(conn)
    for versao, sql in migracoes:
        if versao <= atual:
            continue
        logger.info("Aplicando migração %d", versao)
        # executescript faz COMMIT antes de rodar; o BEGIN/COMMIT explícito
        # garante que a migração inteira (e o registro da versão) seja atômica.
        script = (
            "BEGIN;\n"
            f"{sql}\n;\n"
            f"INSERT INTO schema_versao (versao, aplicada_em) "
            f"VALUES ({int(versao)}, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'));\n"
            "COMMIT;"
        )
        try:
            conn.executescript(script)
        except sqlite3.Error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            logger.exception("Falha na migração %d; nada dela foi aplicado", versao)
            raise
        atual = versao
    return atual
