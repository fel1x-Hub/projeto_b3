"""Gera o ranking de uma data usando só dados disponíveis até ela.

Uso:
    python scripts/gerar_ranking.py                    # último pregão com dados
    python scripts/gerar_ranking.py --data 2025-03-14  # qualquer data passada
    python scripts/gerar_ranking.py --top 20

O modelo é treinado com o que se sabia no corte da data (19h BRT) e o
resultado é gravado na tabela `ranking` (versão lgbm-vN).
Material de apoio à decisão, não recomendação de investimento.
"""

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from src.db.conexao import conectar  # noqa: E402
from src.db.migracoes import migrar  # noqa: E402
from src.logging_config import configurar_logging  # noqa: E402
from src.ranking import gerar  # noqa: E402

logger = logging.getLogger("gerar_ranking")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=date.fromisoformat, default=None, help="AAAA-MM-DD (padrão: último pregão)")
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--db", type=Path, default=None, help=f"arquivo do banco (padrão: {settings.DB_PATH})")
    args = parser.parse_args(argv)

    configurar_logging()
    conn = conectar(args.db)
    try:
        migrar(conn)
        dia = args.data or date.fromisoformat(conn.execute("SELECT MAX(data) FROM universo").fetchone()[0])
        ranking, importancia = gerar.ranking_da_data(conn, dia)
        gerar.gravar(conn, ranking, gerar.VERSAO_MODELO)
    except ValueError as e:
        logger.error("%s", e)
        return 1
    finally:
        conn.close()

    n = len(ranking)
    print(f"Ranking de {dia:%d/%m/%Y} ({n} ações no universo; modelo {gerar.VERSAO_MODELO})")
    print(f"\nTopo {args.top}:")
    for r in ranking.head(args.top).itertuples():
        print(f"  {r.posicao:>3}. {r.ticker:<7} score {r.score:.3f}")
    print(f"\nFundo {args.top}:")
    for r in ranking.tail(args.top).itertuples():
        print(f"  {r.posicao:>3}. {r.ticker:<7} score {r.score:.3f}")
    print("\nSinais que mais pesaram (contribuição média absoluta):")
    for nome, valor in importancia.head(8).items():
        print(f"  {nome:<20} {valor:.4f}")
    print("\nMaterial de apoio à decisão, não recomendação de investimento.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
