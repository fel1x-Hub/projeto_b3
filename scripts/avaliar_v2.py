"""Avalia o modelo v2 contra o v1 com o protocolo e o critério PRÉ-REGISTRADOS
em docs/ranking_v2.md (escritos antes de rodar).

Uso:
    python scripts/avaliar_v2.py

Não grava nada no banco: só escreve a seção "Resultados" de docs/ranking_v2.md.
A troca de modelo, se o critério aprovar, depende de autorização do usuário.
"""

import logging
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from scripts.backtest import CUSTOS, REGRA, matriz_retornos  # noqa: E402
from src.db.conexao import conectar  # noqa: E402
from src.logging_config import configurar_logging  # noqa: E402
from src.ranking import dados, modelo  # noqa: E402
from src.validacao.backtest import metricas, simular  # noqa: E402

logger = logging.getLogger("avaliar_v2")
DOC = settings.BASE_DIR / "docs" / "ranking_v2.md"

# Exatamente as variações pré-registradas (nenhuma a mais).
VARIACOES = [
    ("A · v1 (referência)", dados.FEATURES_BASE, None),
    ("B · v1 + restrições monotônicas (candidata)", dados.FEATURES_BASE, modelo.MONOTONIA),
    ("C · B + eventos (só sensibilidade)", dados.FEATURES_BASE + dados.FEATURES_EVENTOS, modelo.MONOTONIA),
]


def main() -> int:
    configurar_logging()
    conn = conectar()
    X = dados.carregar_features(conn, sorted(set(dados.FEATURES_BASE + dados.FEATURES_EVENTOS)))
    alvo = dados.calcular_alvo(conn, horizonte=21)
    universo = dados.carregar_universo(conn)
    retornos = matriz_retornos(conn)
    cdi = pd.read_sql_query("SELECT data, valor FROM macro WHERE serie = 'cdi'", conn, parse_dates=["data"])
    cdi = (cdi.set_index("data")["valor"] / 100).reindex(retornos.index).ffill()
    conn.close()

    res = {}
    for nome, colunas, mono in VARIACOES:
        logger.info("Variação: %s", nome)
        prev = modelo.walk_forward(X, alvo, colunas, mono)
        ics = modelo.ic_diario(prev, alvo, minimo_acoes=15)
        r = modelo.resumo(ics, modelo.spread_decis(prev, alvo), 21)
        anos = {a: modelo.ic_diario(prev[prev["data"].dt.year == a], alvo, minimo_acoes=15).mean()
                for a in sorted({d.year for d in prev["data"]})}
        bt = simular(prev[["data", "ticker", "score"]], retornos, universo, REGRA, CUSTOS)
        periodo = bt.retorno.index
        m = metricas(bt.retorno, cdi.reindex(periodo).fillna(0.0), bt.giro)
        res[nome] = {"r": r, "anos": anos, "bt": m}
        logger.info("%s: IC %+.4f spread %+.2f%% retorno anual %+.1f%%", nome, r["ic_medio"],
                    100 * r["spread_medio"], 100 * m["retorno_anual"])

    a, b = res[VARIACOES[0][0]], res[VARIACOES[1][0]]
    criterios = [
        ("IC médio ≥ v1", b["r"]["ic_medio"] >= a["r"]["ic_medio"]),
        ("spread topo−fundo ≥ v1", b["r"]["spread_medio"] >= a["r"]["spread_medio"]),
        ("IC positivo em todos os anos", all(v > 0 for v in b["anos"].values())),
        ("retorno anual do backtest (após custos) ≥ v1", b["bt"]["retorno_anual"] >= a["bt"]["retorno_anual"]),
    ]
    aprovado = all(ok for _, ok in criterios)

    anos = sorted(a["anos"])
    md = [f"## Resultados ({date.today():%d/%m/%Y})", "",
          "| Variação | IC médio | dias IC>0 | t | spread 21d | backtest a.a. | Sharpe | drawdown | giro |",
          "|---|---|---|---|---|---|---|---|---|"]
    for nome, v in res.items():
        r, m = v["r"], v["bt"]
        md.append(f"| {nome} | {r['ic_medio']:+.4f} | {r['ic_positivo']:.0%} | {r['t_ic']:+.2f} | "
                  f"{r['spread_medio']:+.2%} | {m['retorno_anual']:+.1%} | {m['sharpe']:.2f} | "
                  f"{m['drawdown_max']:.1%} | {m['giro_anual']:.1f}x |")
    md += ["", "### IC médio por ano", "", "| Variação | " + " | ".join(map(str, anos)) + " |",
           "|---|" + "---|" * len(anos)]
    for nome, v in res.items():
        md.append(f"| {nome} | " + " | ".join(f"{v['anos'].get(ano, float('nan')):+.3f}" for ano in anos) + " |")
    md += ["", "### Critério pré-registrado (B contra A)", ""]
    md += [f"- {'✅' if ok else '❌'} {txt}" for txt, ok in criterios]
    md += ["", f"**Decisão pelo critério: {'B aprovado como v2 (aguarda autorização do usuário para trocar)' if aprovado else 'v1 continua (B não cumpriu todos os critérios)'}.**",
           "", "C é só sensibilidade (risco de look-ahead do LLM) e não pode virar o modelo, qualquer que seja o resultado.", ""]

    texto = DOC.read_text(encoding="utf-8")
    texto = texto[:texto.index("## Resultados")] + "\n".join(md)
    DOC.write_text(texto, encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
