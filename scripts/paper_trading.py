"""Paper trading diário (etapa 5.2): gera o ranking do último pregão, aplica a
regra da carteira (top 30, pesos iguais, rebalanceamento a cada 10 pregões) e
registra carteira e patrimônio. NENHUMA ordem real é enviada.

Uso (depois de coletar.py e gerar_sinais.py):
    python scripts/paper_trading.py

Na primeira execução, o último pregão vira a data de início. A comparação com
o backtest e com Ibovespa/CDI no mesmo período aparece no resumo.
"""

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.backtest import matriz_retornos  # noqa: E402
from src.db.conexao import conectar  # noqa: E402
from src.db.migracoes import migrar  # noqa: E402
from src.logging_config import configurar_logging  # noqa: E402
from src.ranking import dados, gerar  # noqa: E402
from src.validacao import paper  # noqa: E402

logger = logging.getLogger("paper_trading")


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    configurar_logging()
    conn = conectar()
    try:
        migrar(conn)
        ultimo = conn.execute("SELECT MAX(data) FROM universo").fetchone()[0]
        if ultimo is None:
            logger.error("Universo vazio: rode coletar.py e gerar_sinais.py antes")
            return 1
        ja_tem = conn.execute("SELECT 1 FROM ranking WHERE versao_modelo = ? AND data = ? LIMIT 1",
                              (gerar.VERSAO_MODELO, ultimo)).fetchone()
        if not ja_tem:
            ranking, _ = gerar.ranking_da_data(conn, date.fromisoformat(ultimo))
            gerar.gravar(conn, ranking, gerar.VERSAO_MODELO)
        data_inicio = paper.inicio(conn, se_vazio=ultimo)
        r = paper.atualizar(conn, matriz_retornos(conn), dados.carregar_universo(conn), data_inicio)
        carteira = conn.execute(
            "SELECT data_execucao, data_ranking, GROUP_CONCAT(ticker, ', ') FROM paper_carteira "
            "WHERE data_execucao = (SELECT MAX(data_execucao) FROM paper_carteira)").fetchone()
    finally:
        conn.close()

    print(f"Paper trading desde {data_inicio} (regra: top {paper.REGRA.n_acoes}, a cada {paper.REGRA.intervalo} pregões)")
    if r is None or r.valor.empty:
        print("Carteira ainda não montada: a primeira compra é no fechamento do pregão seguinte ao início.")
        return 0
    print(f"Patrimônio: {r.valor.iloc[-1]:.4f} (início = 1,0000) | retorno {r.valor.iloc[-1] - 1:+.2%} "
          f"em {len(r.valor)} pregões | custos pagos {r.custos.sum():.3%}")
    if carteira and carteira[0]:
        print(f"Carteira atual (montada em {carteira[0]}, ranking de {carteira[1]}): {carteira[2]}")
    print("Nenhuma ordem real é enviada. Material de estudo, não recomendação de investimento.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
