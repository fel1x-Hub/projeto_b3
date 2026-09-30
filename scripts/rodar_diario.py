"""Pipeline diário completo (depois do fechamento, quando sai o arquivo da B3):
coleta -> eventos -> sinais -> ranking -> paper trading -> relatório.

Uso:
    python scripts/rodar_diario.py

Cada passo roda em um processo separado: se um falhar, os seguintes rodam do
mesmo jeito (com os dados que houver) e o resumo final mostra o que falhou.
"""

import logging
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src.db.tempo import hoje_brt  # noqa: E402
from src.logging_config import configurar_logging  # noqa: E402

logger = logging.getLogger("rodar_diario")


def passos() -> list[tuple[str, list[str]]]:
    desde = (hoje_brt() - timedelta(days=15)).isoformat()  # regrava só os sinais recentes (rápido)
    return [
        ("coleta", ["scripts/coletar.py"]),
        ("eventos (títulos + 150 textos completos)", ["scripts/extrair_eventos.py", "--limite", "150"]),
        ("sinais", ["scripts/gerar_sinais.py", "--desde", desde]),
        ("ranking", ["scripts/gerar_ranking.py"]),
        ("paper trading", ["scripts/paper_trading.py"]),
        ("relatório", ["scripts/gerar_relatorio.py"]),
    ]


def main() -> int:
    configurar_logging()
    resumo = []
    for nome, comando in passos():
        inicio = time.monotonic()
        logger.info("Pipeline diário: %s", nome)
        r = subprocess.run([sys.executable, *comando], cwd=RAIZ, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        duracao = time.monotonic() - inicio
        if r.returncode != 0:
            logger.error("%s falhou (código %d): %s", nome, r.returncode, r.stderr[-800:])
        resumo.append((nome, r.returncode, duracao))
    for nome, codigo, duracao in resumo:
        print(f"  {nome:<42} {'ok' if codigo == 0 else f'FALHOU ({codigo})':<12} {duracao:>6.0f}s")
    return 0 if all(c == 0 for _, c, _ in resumo) else 1


if __name__ == "__main__":
    sys.exit(main())
