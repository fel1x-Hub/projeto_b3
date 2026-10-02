"""Coleta os dados de todas as fontes (ou de uma) e mostra um resumo.

Uso:
    python scripts/coletar.py                      # todas as fontes, incremental
    python scripts/coletar.py --fonte b3           # só uma fonte
    python scripts/coletar.py --desde 2020-01-01   # carga histórica a partir de uma data

Fontes: cvm (cadastro, documentos e demonstrações), b3 (cotações),
proventos (yfinance + config/eventos_manuais.csv), bcb (macro) e rss (notícias).
A coleta é incremental: rodar de novo só traz o que ainda não está no banco.
Sem --desde, a carga inicial cobre HISTORICO_ANOS (padrão 5) anos.
Uma fonte com erro não interrompe as outras; o código de saída é 1 se
alguma fonte falhou por completo.
"""

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from src.coleta import (  # noqa: E402
    b3_cotahist, bcb_sgs, cvm_cadastro, cvm_dfp_itr, cvm_ipe, eventos_manuais, noticias_rss, pluggy, resumo,
    yfinance_proventos,
)
from src.coleta.execucao import executar  # noqa: E402
from src.db.ativos import sincronizar_ativos  # noqa: E402
from src.db.conexao import conectar  # noqa: E402
from src.db.migracoes import migrar  # noqa: E402
from src.db.tempo import agora_utc_iso, hoje_brt  # noqa: E402
from src.logging_config import configurar_logging  # noqa: E402

logger = logging.getLogger("coletar")

# (nome da execução, função, grupo do --fonte). A ordem importa: o cadastro
# CVM preenche os códigos usados por documentos e demonstrações.
FONTES = [
    (cvm_cadastro.FONTE, cvm_cadastro.coletar, "cvm"),
    (b3_cotahist.FONTE, b3_cotahist.coletar, "b3"),
    (yfinance_proventos.FONTE, yfinance_proventos.coletar, "proventos"),
    (eventos_manuais.FONTE, eventos_manuais.coletar, "proventos"),
    (bcb_sgs.FONTE, bcb_sgs.coletar, "bcb"),
    (cvm_ipe.FONTE, cvm_ipe.coletar, "cvm"),
    (cvm_dfp_itr.FONTE, cvm_dfp_itr.coletar, "cvm"),
    ("rss", noticias_rss.coletar, "rss"),
    ("carteira_xp", pluggy.coletar, "carteira"),   # só com PLUGGY_* no .env; sem elas, não faz nada
]
GRUPOS = sorted({g for _, _, g in FONTES})


def desde_padrao(hoje: date, anos: int) -> date:
    try:
        return hoje.replace(year=hoje.year - anos)
    except ValueError:  # 29 de fevereiro
        return hoje.replace(year=hoje.year - anos, day=28)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fonte", choices=["todas", *GRUPOS], default="todas")
    parser.add_argument("--desde", type=date.fromisoformat, default=None, help="AAAA-MM-DD")
    parser.add_argument("--db", type=Path, default=None, help=f"arquivo do banco (padrão: {settings.DB_PATH})")
    args = parser.parse_args(argv)

    configurar_logging()
    desde = args.desde or desde_padrao(hoje_brt(), settings.HISTORICO_ANOS)
    conn = conectar(args.db)
    try:
        migrar(conn)
        sincronizar_ativos(conn, settings.carregar_ativos())

        inicio = agora_utc_iso()
        antes = resumo.contar_tabelas(conn)
        resultados = [
            executar(conn, nome, funcao, desde)
            for nome, funcao, grupo in FONTES
            if args.fonte in ("todas", grupo)
        ]
        print(resumo.montar(conn, resultados, antes, inicio))
    finally:
        conn.close()

    return 1 if any(r.status == "falha" for r in resultados) else 0


if __name__ == "__main__":
    sys.exit(main())
