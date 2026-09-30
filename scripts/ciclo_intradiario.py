"""Ciclo intradiário (regra 15), rodado a cada ~15 min durante o pregão pelo
agendador: cotação do momento, notícias novas (com sentimento) e ranking
PROVISÓRIO com a cotação atual. Fora do pregão não faz nada (use --forcar).

Uso:
    python scripts/ciclo_intradiario.py
    python scripts/ciclo_intradiario.py --forcar
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402,F401  (carrega o .env)
from src.coleta import intradiario, noticias_rss  # noqa: E402
from src.coleta.execucao import executar  # noqa: E402
from src.db.conexao import conectar  # noqa: E402
from src.db.migracoes import migrar  # noqa: E402
from src.db.tempo import hoje_brt  # noqa: E402
from src.logging_config import configurar_logging  # noqa: E402
from src.ranking import provisorio  # noqa: E402
from src.sinais import sentimento  # noqa: E402

logger = logging.getLogger("ciclo_intradiario")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--forcar", action="store_true", help="roda mesmo fora do horário do pregão")
    args = parser.parse_args(argv)
    configurar_logging()
    if not args.forcar and not intradiario.pregao_em_andamento():
        logger.info("Fora do pregão: nada a fazer")
        return 0
    conn = conectar()
    try:
        migrar(conn)
        passos = [
            ("cotacao_atual", lambda c, d: intradiario.coletar(c)),
            ("rss", noticias_rss.coletar),
            ("sentimento", lambda c, d: sentimento.classificar_pendentes(c)),
            ("ranking_provisorio", lambda c, d: len(getattr(provisorio.gerar_provisorio(c), "ranking", []))),
        ]
        resultados = [executar(conn, nome, funcao, hoje_brt()) for nome, funcao in passos]
    finally:
        conn.close()
    for r in resultados:
        print(f"  {r.fonte:<20} {r.status:<8} {r.novos:>5}" + (f"  ({r.erro})" if r.erro else ""))
    return 1 if any(r.status == "falha" for r in resultados) else 0


if __name__ == "__main__":
    sys.exit(main())
