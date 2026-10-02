"""Gera o ranking de uma data usando só dados disponíveis até ela.

Uso:
    python scripts/gerar_ranking.py                    # pregões ainda sem ranking (o último, normalmente)
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


def gravar_venda(conn, dias) -> None:
    """Nota de venda por chance de cair (docs/venda.md), só se o modelo foi aprovado no pré-registro."""
    import pandas as pd

    from scripts.backtest import matriz_retornos
    from src.db.tempo import agora_utc_iso
    from src.ranking import venda
    fonte, _ = venda.calibracao_em_uso(conn)
    if fonte != "modelo":
        return
    retornos = matriz_retornos(conn)
    scores = pd.read_sql_query("SELECT data, ticker, score FROM ranking WHERE versao_modelo IN (?, ?)", conn,
                               params=(gerar.VERSAO_WALK_FORWARD, gerar.VERSAO_MODELO), parse_dates=["data"])
    scores = scores.drop_duplicates(["data", "ticker"], keep="last")
    for dia in dias:
        prev = venda.prever_dia(conn, dia, retornos, scores)
        with conn:
            conn.execute("DELETE FROM venda WHERE data = ? AND versao = ?", (dia.isoformat(), venda.VERSAO))
            conn.executemany("INSERT INTO venda VALUES (?, ?, ?, ?, ?, ?, ?)",
                             [(dia.isoformat(), r.ticker, venda.VERSAO, float(r.prob),
                               None if r.chance_cair is None else float(r.chance_cair), int(r.nota), agora_utc_iso())
                              for r in prev.itertuples()])
        logger.info("Chance de cair de %s: %d ações", dia, len(prev))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=date.fromisoformat, default=None, help="AAAA-MM-DD (padrão: último pregão)")
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--venda", action="store_true", help="só recalcula a chance de cair do último ranking oficial")
    parser.add_argument("--db", type=Path, default=None, help=f"arquivo do banco (padrão: {settings.DB_PATH})")
    args = parser.parse_args(argv)

    configurar_logging()
    conn = conectar(args.db)
    try:
        migrar(conn)
        if args.venda:
            ultimo = conn.execute("SELECT MAX(data) FROM ranking WHERE versao_modelo = ?", (gerar.VERSAO_MODELO,)).fetchone()[0]
            if ultimo:
                gravar_venda(conn, [date.fromisoformat(ultimo)])
            return 0
        dias = [args.data] if args.data else gerar.datas_pendentes(conn)
        if not dias:
            print("Ranking oficial já está em dia.")
            return 0
        for dia in dias:
            resultado = gerar.ranking_da_data(conn, dia, salvar_em=settings.BASE_DIR / "data" / "modelos")
            ranking, importancia = resultado.ranking, resultado.importancia
            gerar.gravar(conn, ranking, gerar.VERSAO_MODELO)
            gerar.gravar_fatores(conn, resultado.fatores, gerar.VERSAO_MODELO)
        gravar_venda(conn, dias)
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
