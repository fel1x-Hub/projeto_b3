"""Cria/atualiza o banco: aplica migrações pendentes e sincroniza os ativos.

Uso:
    python scripts/init_db.py                  # banco definido em DB_PATH (.env)
    python scripts/init_db.py --db outro.db    # outro arquivo

Pode ser rodado quantas vezes quiser: só aplica o que falta. Para acompanhar
um novo ativo, adicione uma linha em config/ativos.csv e rode de novo.
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from src.db.ativos import sincronizar_ativos  # noqa: E402
from src.db.conexao import conectar  # noqa: E402
from src.db.migracoes import migrar  # noqa: E402
from src.logging_config import configurar_logging  # noqa: E402

logger = logging.getLogger("init_db")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=None, help=f"arquivo do banco (padrão: {settings.DB_PATH})")
    parser.add_argument("--ativos", type=Path, default=None, help=f"CSV de ativos (padrão: {settings.ATIVOS_CSV})")
    args = parser.parse_args(argv)

    configurar_logging()
    caminho = args.db or settings.DB_PATH

    try:
        ativos = settings.carregar_ativos(args.ativos)
    except (OSError, ValueError) as e:
        logger.error("Lista de ativos inválida: %s", e)
        return 1

    conn = conectar(caminho)
    try:
        versao = migrar(conn)
        sincronizar_ativos(conn, ativos)
        n_ativos, n_inativos = conn.execute(
            "SELECT SUM(ativo = 1), SUM(ativo = 0) FROM ativos"
        ).fetchone()
    finally:
        conn.close()

    logger.info(
        "Banco pronto em %s | schema v%d | %d ativos acompanhados, %d inativos",
        caminho, versao, n_ativos or 0, n_inativos or 0,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
