"""Calibra as previsões por prazo e mede o efeito histórico dos padrões gráficos.

Uso:
    python scripts/calibrar.py

Precisa do histórico fora da amostra do modelo em uso (rode antes
scripts/avaliar_ranking.py, que grava o walk-forward). Grava as tabelas
`calibracao` e `padroes_efeito`; o resumo vai para docs/previsoes.md.
Roda toda semana na nuvem (workflow "Recalibrar").
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
from src.ranking import calibracao as cal  # noqa: E402
from src.ranking import dados, gerar  # noqa: E402
from src.sinais import padroes  # noqa: E402

logger = logging.getLogger("calibrar")
DOC = settings.BASE_DIR / "docs" / "previsoes.md"
PRAZOS_PADRAO = {21: "1 mês", 63: "3 meses"}
PASSO = 5            # avalia padrões a cada 5 pregões (uma vez por semana)
INTERVALO_MESMO = 20  # o mesmo padrão na mesma ação só conta de novo após 20 pregões


def eventos_de_padroes(retornos: pd.DataFrame, universo: pd.DataFrame) -> pd.DataFrame:
    """(data, ticker, padrao) detectados só com preços até a data (índice de retorno total)."""
    indice = (1 + retornos.fillna(0.0)).cumprod()
    no_universo = universo.groupby("ticker")["data"].apply(set)
    linhas = []
    datas = indice.index
    for ticker in indice.columns:
        if ticker not in no_universo:
            continue
        validas = no_universo[ticker]
        precos = indice[ticker].to_numpy()
        ultimo_visto: dict[str, int] = {}
        for i in range(padroes.JANELA, len(datas), PASSO):
            if datas[i] not in validas:
                continue
            achado = padroes.detectar(precos[i - padroes.JANELA + 1: i + 1])
            if achado and i - ultimo_visto.get(achado, -10**9) >= INTERVALO_MESMO:
                linhas.append((datas[i], ticker, achado))
                ultimo_visto[achado] = i
    return pd.DataFrame(linhas, columns=["data", "ticker", "padrao"])


def efeito_padroes(eventos: pd.DataFrame, retornos: pd.DataFrame) -> pd.DataFrame:
    linhas = []
    for h, rotulo in PRAZOS_PADRAO.items():
        fut = cal.retornos_futuros(retornos, h)
        excesso = fut.sub(fut["BOVA11"], axis=0)
        longo = excesso.stack().rename("excesso").reset_index()
        longo.columns = ["data", "ticker", "excesso"]
        ev = eventos.merge(longo, on=["data", "ticker"]).dropna(subset=["excesso"])
        for nome in padroes.NOMES:
            g = ev[ev["padrao"] == nome]
            if g.empty:
                linhas.append({"padrao": nome, "horizonte": h, "n": 0, "excesso_medio": None, "chance_superar": None,
                               "t": None, "conclusao": "nunca detectado no histórico"})
                continue
            # t conservador: média por mês (eventos do mesmo mês não são independentes)
            mensal = g.groupby(g["data"].dt.to_period("M"))["excesso"].mean()
            t = mensal.mean() / (mensal.std(ddof=1) / np.sqrt(len(mensal))) if len(mensal) > 2 and mensal.std() > 0 else np.nan
            m, chance = g["excesso"].mean(), (g["excesso"] > 0).mean()
            if len(g) >= 30 and np.isfinite(t) and abs(t) >= cal.T_MINIMO:
                conclusao = (f"historicamente antecedeu {'alta' if m > 0 else 'queda'} contra o mercado em {rotulo} "
                             f"(média {m:+.1%}, {len(g)} casos)")
            else:
                conclusao = f"sem efeito comprovado no histórico em {rotulo} ({len(g)} casos)"
            linhas.append({"padrao": nome, "horizonte": h, "n": int(len(g)), "excesso_medio": float(m),
                           "chance_superar": float(chance), "t": float(t) if np.isfinite(t) else None,
                           "conclusao": conclusao})
    return pd.DataFrame(linhas)


def main() -> int:
    configurar_logging()
    conn = conectar()
    migrar(conn)
    scores = pd.read_sql_query("SELECT data, ticker, score FROM ranking WHERE versao_modelo = ?", conn,
                               params=(gerar.VERSAO_WALK_FORWARD,), parse_dates=["data"])
    if scores.empty:
        logger.error("Sem histórico %s: rode scripts/avaliar_ranking.py antes", gerar.VERSAO_WALK_FORWARD)
        return 1
    retornos = matriz_retornos(conn)
    universo = dados.carregar_universo(conn)
    agora = agora_utc_iso()

    tab = cal.calibrar(scores, retornos).assign(versao_modelo=gerar.VERSAO_MODELO, calculado_em=agora)
    eventos = eventos_de_padroes(retornos, universo)
    efeito = efeito_padroes(eventos, retornos).assign(
        periodo_inicio=eventos["data"].min().date().isoformat() if not eventos.empty else date.today().isoformat(),
        periodo_fim=eventos["data"].max().date().isoformat() if not eventos.empty else date.today().isoformat(),
        calculado_em=agora)
    with conn:
        conn.execute("DELETE FROM calibracao WHERE versao_modelo = ?", (gerar.VERSAO_MODELO,))
        tab.to_sql("calibracao", conn, if_exists="append", index=False)
        conn.execute("DELETE FROM padroes_efeito")
        efeito.to_sql("padroes_efeito", conn, if_exists="append", index=False)
    conn.close()

    md = [f"# Previsões por prazo e padrões gráficos ({date.today():%d/%m/%Y})", "",
          "O que aparece no app como \"ganho esperado\" é o **histórico real, fora da amostra**, de ações que estavam na "
          f"mesma faixa de pontuação de compra (modelo {gerar.VERSAO_MODELO}, de {tab['periodo_inicio'].min()} a "
          f"{tab['periodo_fim'].max()}). Não é promessa. O sinal só aparece com t ≥ {cal.T_MINIMO:g} e ao menos "
          f"{cal.JANELAS_MINIMAS} janelas que não se sobrepõem.", ""]
    for h, rotulo in cal.PRAZOS.items():
        t = tab[tab["horizonte"] == h]
        if t.empty:
            continue
        md += [f"## {rotulo}", "", "| Faixa de compra | casos | janelas indep. | retorno médio | faixa provável | contra o mercado | chance de superar | sinal |",
               "|---|---|---|---|---|---|---|---|"]
        for r in t.sort_values("faixa_min", ascending=False).itertuples():
            md.append(f"| {r.faixa_min}–{r.faixa_max} | {r.n} | {r.janelas_independentes} | {r.retorno_medio:+.1%} | "
                      f"{r.p25:+.1%} a {r.p75:+.1%} | {r.excesso_medio:+.1%} | {r.chance_superar:.0%} | {r.sinal} |")
        md.append("")
    md += ["## Padrões gráficos", "", "Detectados só com preços até cada data; efeito contra o BOVA11.", "",
           "| Padrão | prazo | casos | contra o mercado | chance de superar | conclusão |", "|---|---|---|---|---|---|"]
    for r in efeito.itertuples():
        nome = padroes.NOMES[r.padrao][0]
        md.append(f"| {nome} | {PRAZOS_PADRAO[r.horizonte]} | {r.n} | "
                  f"{'' if r.excesso_medio is None or pd.isna(r.excesso_medio) else f'{r.excesso_medio:+.1%}'} | "
                  f"{'' if r.chance_superar is None or pd.isna(r.chance_superar) else f'{r.chance_superar:.0%}'} | {r.conclusao} |")
    DOC.write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
