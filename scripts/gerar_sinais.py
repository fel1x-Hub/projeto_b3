"""Calcula os sinais de todo o histórico disponível, grava na tabela `sinais` e
mostra o relatório de cobertura.

Uso:
    python scripts/gerar_sinais.py                         # todas as famílias
    python scripts/gerar_sinais.py --familia tecnicos      # só uma
    python scripts/gerar_sinais.py --so-cobertura          # só o relatório

Recalcular é idempotente: cada família substitui os próprios valores da sua
versão. Todo sinal da data D usa apenas dados com disponivel_em <= D 19h BRT.
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from src.db.conexao import conectar  # noqa: E402
from src.db.migracoes import migrar  # noqa: E402
from src.logging_config import configurar_logging  # noqa: E402
from src.sinais import base, cobertura, fundamentalistas, sentimento, tecnicos  # noqa: E402

logger = logging.getLogger("gerar_sinais")

FAMILIAS = {
    "tecnicos": tecnicos,
    "fundamentalistas": fundamentalistas,
    "sentimento": sentimento,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--familia", choices=["todas", *FAMILIAS], default="todas")
    parser.add_argument("--so-cobertura", action="store_true")
    parser.add_argument("--db", type=Path, default=None, help=f"arquivo do banco (padrão: {settings.DB_PATH})")
    args = parser.parse_args(argv)

    configurar_logging()
    conn = conectar(args.db)
    try:
        migrar(conn)
        if not args.so_cobertura:
            for nome, modulo in FAMILIAS.items():
                if args.familia not in ("todas", nome):
                    continue
                inicio = time.monotonic()
                n = base.gravar(conn, modulo.calcular(conn), modulo.VERSOES)
                logger.info("%s: %d valores em %.0fs", nome, n, time.monotonic() - inicio)
        print(cobertura.relatorio(conn))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
