"""Sincroniza a carteira da XP (Meu Pluggy / Open Finance) direto no banco que a API usa.

Uso:
    python scripts/sincronizar_carteira.py

Com DATABASE_URL (nuvem): grava no Postgres, onde a carteira vive (nunca no
repositório). Sem ela: no SQLite local. Sem credenciais PLUGGY_*: não faz nada.
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.coleta import pluggy  # noqa: E402
from src.db.nuvem import conectar_api  # noqa: E402
from src.logging_config import configurar_logging  # noqa: E402

logger = logging.getLogger("sincronizar_carteira")


def main() -> int:
    configurar_logging()
    if pluggy.credenciais() is None:
        print("Meu Pluggy não configurado (PLUGGY_*): nada a sincronizar.")
        return 0
    conn = conectar_api()
    try:
        n = pluggy.coletar(conn)
    except Exception:  # noqa: BLE001 - registra e devolve código de erro
        logger.exception("Falha ao sincronizar a carteira com a Pluggy")
        return 1
    finally:
        conn.close()
    print(f"Carteira sincronizada: {n} posições de bolsa.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
