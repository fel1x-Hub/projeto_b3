"""Avalia o modelo de ranking contra baselines, período a período, e grava o
histórico fora da amostra (walk-forward) na tabela `ranking`.

Uso:
    python scripts/avaliar_ranking.py

Saída: docs/ranking_avaliacao.md (números) e tabela ranking (versão wf-lgbm-vN).
Todas as variações testadas ficam listadas no relatório (quanto mais variações,
maior o risco de escolher uma boa por acaso).
"""

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from src.db.conexao import conectar  # noqa: E402
from src.db.migracoes import migrar  # noqa: E402
from src.logging_config import configurar_logging  # noqa: E402
from src.ranking import dados, gerar, modelo  # noqa: E402

logger = logging.getLogger("avaliar_ranking")
SAIDA = settings.BASE_DIR / "docs" / "ranking_avaliacao.md"

# (nome, features, horizonte) — TODA variação rodada entra aqui e no relatório
VARIACOES = [
    ("modelo principal (sem eventos)", dados.FEATURES_BASE, 21),
    ("modelo com eventos", dados.FEATURES_BASE + dados.FEATURES_EVENTOS, 21),
    ("modelo, horizonte 5 pregões", dados.FEATURES_BASE, 5),
]
BASELINES = {"aleatório": None, "momentum (ret_63d)": "ret_63d", "valor (fund_lp)": "fund_lp",
             "eventos (evt_saldo)": "evt_saldo"}
FAIXAS = [("≥ R$ 5 mi/dia", 5e6, np.inf), ("R$ 1–5 mi/dia", 1e6, 5e6), ("R$ 0,1–1 mi/dia", 0, 1e6)]


def _linha(nome, r):
    return (f"| {nome} | {r['ic_medio']:+.4f} | {r['ic_desvio']:.3f} | {r['ic_positivo']:.0%} | "
            f"{r['t_ic']:+.2f} | {r['spread_medio']:+.2%} |")


def _tabela(titulo, linhas):
    return [f"### {titulo}", "", "| Método | IC médio | desvio | dias IC>0 | t (sem sobreposição) | spread top−bottom decil (21d) |",
            "|---|---|---|---|---|---|", *linhas, ""]


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    configurar_logging()
    conn = conectar()
    migrar(conn)
    todas = sorted(set(dados.FEATURES_BASE + dados.FEATURES_EVENTOS))
    X = dados.carregar_features(conn, todas)
    alvos = {h: dados.calcular_alvo(conn, horizonte=h) for h in sorted({h for *_, h in VARIACOES})}
    universo = dados.carregar_universo(conn)

    previsoes = {}
    for nome, colunas, h in VARIACOES:
        logger.info("Variação: %s", nome)
        previsoes[nome] = (modelo.walk_forward(X, alvos[h], colunas), h)
    principal, _ = previsoes[VARIACOES[0][0]]
    inicio = principal["data"].min()

    Xr = X.reset_index()
    Xr = Xr[Xr["data"] >= inicio]
    rng = np.random.default_rng(0)
    metodos = {nome: (p[p["data"] >= inicio], h) for nome, (p, h) in previsoes.items()}
    for nome, col in BASELINES.items():
        score = rng.random(len(Xr)) if col is None else Xr[col]
        metodos[nome] = (Xr[["data", "ticker"]].assign(score=score), 21)

    def avaliar(sc, h, filtro=None):
        if filtro is not None:
            sc = sc.merge(filtro, on=["data", "ticker"])
        alvo = alvos[h]
        return modelo.resumo(modelo.ic_diario(sc, alvo, minimo_acoes=15), modelo.spread_decis(sc, alvo), h)

    md = [f"# Avaliação do ranking ({date.today():%d/%m/%Y})", "",
          f"- Período fora da amostra: {inicio:%d/%m/%Y} a {principal['data'].max():%d/%m/%Y} "
          f"(walk-forward com retreino trimestral; treino só com alvos já realizados).",
          f"- Universo: {universo.groupby('data').size().loc[lambda s: s.index >= inicio].mean():.0f} ações/dia em média.",
          "- IC = correlação de Spearman entre score e retorno futuro, por dia. t usa só dias sem sobreposição do horizonte.",
          "- Spread = retorno médio do decil de maior score menos o de menor, nos próximos 21 pregões (sem custos).",
          f"- **Variações do modelo testadas: {len(VARIACOES)}** — " + "; ".join(n for n, *_ in VARIACOES) + ".",
          "- O modelo principal foi escolhido ANTES de ver os resultados (sem eventos, por causa do risco de "
          "look-ahead do LLM); as outras variações são sensibilidade.", ""]

    md += _tabela("Período completo", [_linha(n, avaliar(sc, h)) for n, (sc, h) in metodos.items()])

    anos = sorted({d.year for d in principal["data"]})
    linhas = []
    for n, (sc, h) in metodos.items():
        ics = [modelo.ic_diario(sc[sc["data"].dt.year == a], alvos[h], minimo_acoes=15).mean() for a in anos]
        linhas.append(f"| {n} | " + " | ".join(f"{v:+.3f}" for v in ics) + " |")
    md += ["### IC médio por ano", "", "| Método | " + " | ".join(map(str, anos)) + " |",
           "|---|" + "---|" * len(anos), *linhas, ""]

    linhas = []
    for faixa, lo, hi in FAIXAS:
        filtro = universo[(universo["volume_medio"] >= lo) & (universo["volume_medio"] < hi)][["data", "ticker"]]
        for n in (VARIACOES[0][0], "valor (fund_lp)", "momentum (ret_63d)"):
            sc, h = metodos[n]
            linhas.append(_linha(f"{faixa} · {n}", avaliar(sc, h, filtro)))
    md += _tabela("Por faixa de liquidez", linhas)

    # importância: modelo treinado com tudo o que já tem alvo, aplicado ao último dia
    alvo21 = alvos[21]
    treino = alvo21.merge(X.reset_index(), on=["data", "ticker"])
    treino["y"] = modelo.alvo_de_treino(treino)
    final = modelo.treinar(treino[dados.FEATURES_BASE], treino["y"])
    ultimo = X.xs(X.index.get_level_values("data").max(), level="data")
    imp = modelo.importancia(final, ultimo[dados.FEATURES_BASE])
    md += ["### Sinais que mais pesam no modelo principal (último pregão)", "",
           "| Sinal | Contribuição média absoluta |", "|---|---|",
           *[f"| {k} | {v:.4f} |" for k, v in imp.items()], ""]

    SAIDA.write_text("\n".join(md) + "\n", encoding="utf-8")
    gerar.gravar(conn, principal[["data", "ticker", "score"]], gerar.VERSAO_WALK_FORWARD)
    conn.close()
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
