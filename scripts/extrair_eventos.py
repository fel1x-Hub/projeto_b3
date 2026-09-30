"""Extrai eventos de fatos relevantes e releases com o Gemini (plano gratuito).

Uso:
    python scripts/extrair_eventos.py               # títulos pendentes + até 300 textos completos
    python scripts/extrair_eventos.py --limite 50   # menos textos completos
    python scripts/extrair_eventos.py --so-titulos

1. Títulos: classifica em lotes (~40 por requisição) os títulos de todos os
   fatos relevantes ainda sem evento, cobrindo todas as empresas.
2. Texto completo: lê o PDF, das empresas mais líquidas para as menos; tem
   preferência sobre a classificação pelo título.

Retomável: documentos já processados (ou com erro registrado) não são
reenviados, e respostas ficam em cache. Se a cota gratuita acabar, a execução
para e continua de onde parou na próxima vez. Depois rode
`python scripts/gerar_sinais.py --familia eventos` para atualizar os sinais.
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402,F401  (carrega o .env)
from src.coleta.cliente_http import ClienteHTTP  # noqa: E402
from src.db.conexao import conectar  # noqa: E402
from src.db.migracoes import migrar  # noqa: E402
from src.logging_config import configurar_logging  # noqa: E402
from src.sinais import eventos  # noqa: E402

logger = logging.getLogger("extrair_eventos")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limite", type=int, default=300, help="máximo de textos completos por execução")
    parser.add_argument("--so-titulos", action="store_true")
    parser.add_argument("--modelo", default=None, help="padrão: GEMINI_MODELO do .env")
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)

    configurar_logging()
    conn = conectar(args.db)
    try:
        migrar(conn)
        llm = eventos.ClienteGemini(modelo=args.modelo)
        t = eventos.processar_titulos(conn, llm)
        print(f"Títulos ({llm.modelo}): {t['classificados']} classificados em {t['lotes']} lotes "
              f"({t['cache']} do cache), {t['erros']} erros.")
        if not args.so_titulos:
            r = eventos.processar(conn, llm, ClienteHTTP(), limite=args.limite)
            print(f"Texto completo: {r['processados']} processados ({r['cache']} do cache), "
                  f"{r['erros']} erros, {r['pendentes_restantes']} pendentes.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
