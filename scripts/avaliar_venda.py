"""Avalia a nota de venda por "chance de cair" com o critério PRÉ-REGISTRADO em docs/venda.md.

Uso:
    python scripts/avaliar_venda.py

Compara, fora da amostra: N (modelo novo), A (nota de venda atual) e B (100 − compra).
Grava a calibração da opção que vale (N se aprovado, senão A) em venda_calibracao
e a seção "Resultados" de docs/venda.md.
"""

import logging
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from scripts.backtest import matriz_retornos  # noqa: E402
from src.db.conexao import conectar  # noqa: E402
from src.db.migracoes import migrar  # noqa: E402
from src.db.tempo import agora_utc_iso  # noqa: E402
from src.logging_config import configurar_logging  # noqa: E402
from src.ranking import dados, gerar, venda  # noqa: E402

logger = logging.getLogger("avaliar_venda")
DOC = settings.BASE_DIR / "docs" / "venda.md"


def notas_atuais(scores: pd.DataFrame) -> pd.DataFrame:
    """A = 100 − compra + metade da queda da compra em 10 pregões; B = 100 − compra (histórico fora da amostra)."""
    sc = scores.copy()
    sc["data"] = pd.to_datetime(sc["data"])
    sc["compra"] = 100 * sc.groupby("data")["score"].rank(pct=True)
    larg = sc.pivot(index="data", columns="ticker", values="compra").sort_index()
    queda = (larg.shift(10) - larg).clip(lower=0).stack().rename("queda").reset_index()
    sc = sc.merge(queda, on=["data", "ticker"], how="left")
    sc["A"] = (100 - sc["compra"] + 0.5 * sc["queda"].fillna(0)).clip(0, 100)
    sc["B"] = 100 - sc["compra"]
    return sc[["data", "ticker", "A", "B"]]


def main() -> int:
    configurar_logging()
    conn = conectar()
    migrar(conn)
    scores = pd.read_sql_query("SELECT data, ticker, score FROM ranking WHERE versao_modelo = ?", conn,
                               params=(gerar.VERSAO_WALK_FORWARD,), parse_dates=["data"])
    retornos = matriz_retornos(conn)
    X = venda.montar(dados.carregar_features(conn, dados.FEATURES_BASE), venda.extras(retornos, scores))
    y = venda.alvo(retornos)
    logger.info("Walk-forward da chance de cair (%d amostras)", len(y))
    prev = venda.walk_forward(X, y)

    df = (prev.merge(notas_atuais(scores), on=["data", "ticker"])
              .merge(y[["data", "ticker", "caiu"]], on=["data", "ticker"]).dropna(subset=["prob", "A", "caiu"]))
    res = {}
    for nome, col in (("N · modelo novo", "prob"), ("A · nota atual", "A"), ("B · 100 − compra", "B")):
        res[nome] = {"auc": venda.auc(df[col], df["caiu"]), "topo": venda.taxa_topo(df, col)}
    base_queda = df["caiu"].mean()
    cal_n = venda.tabela_calibracao(df["prob"], df["caiu"])
    desvio = float((cal_n["prob_media"] - cal_n["taxa_real"]).abs().max())
    criterios = [
        ("AUC de N ≥ AUC de A + 0,01", res["N · modelo novo"]["auc"] >= res["A · nota atual"]["auc"] + 0.01),
        ("taxa de queda no decil de maior nota: N > A", res["N · modelo novo"]["topo"] > res["A · nota atual"]["topo"]),
        ("calibração: previsto vs realizado ≤ 5 p.p. em todo decil", desvio <= 0.05),
    ]
    aprovado = all(ok for _, ok in criterios)
    fonte, col = ("modelo", "prob") if aprovado else ("nota_atual", "A")
    tabela = venda.tabela_calibracao(df[col], df["caiu"]) if not aprovado else cal_n
    agora = agora_utc_iso()
    with conn:
        conn.execute("DELETE FROM venda_calibracao")
        conn.executemany("INSERT INTO venda_calibracao VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         [(venda.VERSAO, fonte, i, float(r.prob_min), float(r.prob_max), float(r.prob_media),
                           float(r.taxa_real), int(r.n), agora) for i, r in enumerate(tabela.itertuples())])
    conn.close()

    md = [f"## Resultados ({date.today():%d/%m/%Y})", "",
          f"- Período fora da amostra: {df['data'].min():%d/%m/%Y} a {df['data'].max():%d/%m/%Y}, {len(df):,} casos. "
          f"Taxa de queda em 1 mês no período: {base_queda:.1%}.".replace(",", "."), "",
          "| Nota | AUC | queda real no decil de maior nota |", "|---|---|---|"]
    md += [f"| {n} | {r['auc']:.3f} | {r['topo']:.1%} |" for n, r in res.items()]
    md += ["", "### Calibração do modelo novo (por decil de probabilidade)", "",
           "| prob. prevista | queda real | casos |", "|---|---|---|"]
    md += [f"| {r.prob_media:.1%} | {r.taxa_real:.1%} | {r.n} |" for r in cal_n.itertuples()]
    md += ["", "### Critério pré-registrado", ""] + [f"- {'✅' if ok else '❌'} {t}" for t, ok in criterios]
    md += ["", f"**Decisão: {'o modelo novo vira a nota de venda' if aprovado else 'a nota atual continua'}.** "
               f"A chance de cair mostrada no app vem da calibração de {'N' if aprovado else 'A'} (tabela venda_calibracao).", ""]
    texto = DOC.read_text(encoding="utf-8")
    DOC.write_text(texto[:texto.index("## Resultados")] + "\n".join(md), encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
