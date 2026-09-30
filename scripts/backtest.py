"""Backtest da estratégia (etapa 5) com a regra fixada pelo usuário antes dos
resultados: top 30, pesos iguais, rebalanceamento a cada 10 pregões, universo
todo, só comprada. Usa o ranking FORA DA AMOSTRA do walk-forward.

Uso:
    python scripts/backtest.py

Saída: docs/backtest.md e gráficos em docs/img/. Material de estudo, não
recomendação de investimento.
"""

import argparse
import logging
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from src.db.conexao import conectar  # noqa: E402
from src.db.migracoes import migrar  # noqa: E402
from src.logging_config import configurar_logging  # noqa: E402
from src.ranking import dados, gerar, modelo  # noqa: E402
from src.sinais import base  # noqa: E402
from src.sinais.precos import retornos_totais  # noqa: E402
from src.validacao.backtest import Custos, Regra, drawdown, metricas, simular  # noqa: E402

logger = logging.getLogger("backtest")
SAIDA = settings.BASE_DIR / "docs" / "backtest.md"
IMG = settings.BASE_DIR / "docs" / "img"
REGRA = Regra(n_acoes=30, intervalo=10)
CUSTOS = Custos()


def matriz_retornos(conn) -> pd.DataFrame:
    cot, prov = base.carregar_cotacoes(conn), base.carregar_proventos(conn)
    calendario = pd.DatetimeIndex(sorted(cot["data"].unique()))
    colunas = {t: retornos_totais(c, prov[prov["ticker"] == t]) for t, c in cot.groupby("ticker")}
    return pd.DataFrame({t: s.reindex(calendario) for t, s in colunas.items()})


def _linha(nome, m):
    return (f"| {nome} | {m['retorno_total']:+.1%} | {m['retorno_anual']:+.1%} | {m['volatilidade']:.1%} | "
            f"{m['sharpe']:.2f} | {m['drawdown_max']:.1%} | {m['giro_anual']:.1f}x |")


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    configurar_logging()
    conn = conectar()
    migrar(conn)

    scores = pd.read_sql_query("SELECT data, ticker, score FROM ranking WHERE versao_modelo = ?", conn,
                               params=(gerar.VERSAO_WALK_FORWARD,), parse_dates=["data"])
    if scores.empty:
        logger.error("Sem ranking fora da amostra: rode antes python scripts/avaliar_ranking.py")
        return 1
    retornos = matriz_retornos(conn)
    universo = dados.carregar_universo(conn)
    cdi = pd.read_sql_query("SELECT data, valor FROM macro WHERE serie = 'cdi'", conn, parse_dates=["data"])
    cdi = (cdi.set_index("data")["valor"] / 100).reindex(retornos.index).ffill()
    inicio = scores["data"].min()

    # baselines e variação com eventos (mesma regra)
    X = dados.carregar_features(conn, ["ret_63d", "fund_lp"] + dados.FEATURES_EVENTOS).reset_index()
    X = X[X["data"] >= inicio]
    rng = np.random.default_rng(0)
    alternativas = {
        "valor (fund_lp)": X[["data", "ticker"]].assign(score=X["fund_lp"]).dropna(),
        "momentum (ret_63d)": X[["data", "ticker"]].assign(score=X["ret_63d"]).dropna(),
        "aleatório": X[["data", "ticker"]].assign(score=rng.random(len(X))),
    }
    logger.info("Walk-forward com eventos (sensibilidade)")
    Xe = dados.carregar_features(conn, dados.FEATURES_BASE + dados.FEATURES_EVENTOS)
    com_eventos = modelo.walk_forward(Xe, dados.calcular_alvo(conn), dados.FEATURES_BASE + dados.FEATURES_EVENTOS)

    def rodar(sc, regra=REGRA, custos=CUSTOS):
        return simular(sc, retornos, universo, regra, custos)

    principal = rodar(scores)
    periodo = principal.retorno.index
    bova = retornos["BOVA11"].reindex(periodo).fillna(0.0) if "BOVA11" in retornos else None
    cdi_p = cdi.reindex(periodo).fillna(0.0)

    linhas = [_linha("**Regra principal (top 30, quinzenal, universo todo)**", metricas(principal.retorno, cdi_p, principal.giro))]
    curvas = {"Modelo (regra principal)": principal.valor}
    for nome, sc in alternativas.items():
        r = rodar(sc)
        linhas.append(_linha(f"{nome}, mesma regra", metricas(r.retorno, cdi_p, r.giro)))
        curvas[nome] = r.valor
    if bova is not None:
        linhas.append(_linha("Ibovespa (BOVA11, comprar e segurar)", metricas(bova, cdi_p)))
        curvas["BOVA11"] = (1 + bova).cumprod()
    linhas.append(_linha("CDI", metricas(cdi_p, cdi_p)))
    curvas["CDI"] = (1 + cdi_p).cumprod()

    sens = []
    for nome, regra, custos, sc in [
        ("N = 20", replace(REGRA, n_acoes=20), CUSTOS, scores),
        ("N = 40", replace(REGRA, n_acoes=40), CUSTOS, scores),
        ("rebalanceamento semanal (5 pregões)", replace(REGRA, intervalo=5), CUSTOS, scores),
        ("rebalanceamento mensal (21 pregões)", replace(REGRA, intervalo=21), CUSTOS, scores),
        ("custos em dobro", REGRA, replace(CUSTOS, multiplicador=2.0), scores),
        ("só ações ≥ R$ 1 mi/dia", replace(REGRA, liquidez_minima=1e6), CUSTOS, scores),
        ("com folga (vende só se sair do top 60)", replace(REGRA, folga=60), CUSTOS, scores),
        ("modelo com eventos", REGRA, CUSTOS, com_eventos[["data", "ticker", "score"]]),
    ]:
        r = rodar(sc, regra, custos)
        sens.append(_linha(nome, metricas(r.retorno.reindex(periodo).fillna(0.0), cdi_p, r.giro)))

    anos = sorted({d.year for d in periodo})
    por_ano = []
    for nome, serie in [("Modelo", principal.retorno), ("BOVA11", bova), ("CDI", cdi_p)]:
        if serie is None:
            continue
        valores = [(1 + serie[serie.index.year == a]).prod() - 1 for a in anos]
        por_ano.append(f"| {nome} | " + " | ".join(f"{v:+.1%}" for v in valores) + " |")

    IMG.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 5))
    for nome, v in curvas.items():
        ax.plot(v.index, v.values, label=nome, linewidth=2.2 if nome.startswith("Modelo") else 1.2)
    ax.set_title("Patrimônio (R$ 1 no início, retornos líquidos de custos)")
    ax.legend(); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(IMG / "backtest_patrimonio.png", dpi=110); plt.close(fig)
    fig, ax = plt.subplots(figsize=(10, 3))
    ax.fill_between(principal.valor.index, drawdown(principal.valor).values, 0, color="firebrick", alpha=0.5, label="Modelo")
    if bova is not None:
        ax.plot(periodo, drawdown((1 + bova).cumprod()).values, color="gray", label="BOVA11")
    ax.set_title("Queda a partir do pico (drawdown)"); ax.legend(); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(IMG / "backtest_drawdown.png", dpi=110); plt.close(fig)

    cab = ["| Estratégia | Retorno total | ao ano | Volatilidade | Sharpe (sobre CDI) | Queda máxima | Giro anual |",
           "|---|---|---|---|---|---|---|"]
    md = [f"# Backtest ({date.today():%d/%m/%Y})", "",
          f"- Período: {periodo[0]:%d/%m/%Y} a {periodo[-1]:%d/%m/%Y} (ranking fora da amostra do walk-forward).",
          "- **Regra fixada pelo usuário antes dos resultados:** top 30 do ranking, pesos iguais, rebalanceamento "
          "a cada 10 pregões, universo todo (≥ R$ 100 mil/dia), só comprada.",
          "- Execução no fechamento do pregão seguinte ao ranking; retornos com dividendos/JCP/desdobramentos; "
          "custos = emolumentos 0,03% + meio spread (0,05% ≥ R$ 5 mi/dia, 0,15% R$ 1–5 mi, 0,50% abaixo) sobre o giro.",
          "- Não considera imposto de renda.", "",
          "## Resultado", "", *cab, *linhas, "",
          "![Patrimônio](img/backtest_patrimonio.png)", "", "![Drawdown](img/backtest_drawdown.png)", "",
          "## Por ano", "", "| | " + " | ".join(map(str, anos)) + " |", "|---|" + "---|" * len(anos), *por_ano, "",
          "## Sensibilidade (mudanças pequenas na regra; resultado bom que some aqui é sinal de sorte)", "",
          *cab, *sens, "",
          "Material de estudo, não recomendação de investimento."]
    SAIDA.write_text("\n".join(md) + "\n", encoding="utf-8")
    conn.close()
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
