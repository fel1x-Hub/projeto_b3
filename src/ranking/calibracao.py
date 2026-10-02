"""Pontuações 0–100 e previsões por prazo, calibradas no HISTÓRICO (pedido do usuário, 02/10/2026).

Nada aqui é "previsão" no sentido de saber o futuro: para cada faixa de
pontuação de compra (0–10, ..., 90–100) e cada prazo (1, 6 e 12 meses), mede-se
o que aconteceu, no passado e FORA DA AMOSTRA (histórico walk-forward do
modelo), com as ações que estavam naquela faixa:
- retorno médio, mediano e a faixa provável (25% piores / 25% melhores casos);
- retorno contra o mercado (BOVA11) e a chance de ter superado o mercado;
- força estatística (t) usando só janelas que não se sobrepõem.

O sinal só aparece com evidência: t >= 2 e ao menos 8 janelas independentes;
senão "sem sinal claro" (o que acontece quase sempre em 6 e 12 meses, por falta
de histórico — e é mostrado assim, sem disfarce). Contas em código (regra 2).
"""

import numpy as np
import pandas as pd

PRAZOS = {21: "1 mês", 126: "6 meses", 252: "12 meses"}
FAIXA = 10                    # largura das faixas de pontuação
T_MINIMO = 2.0
JANELAS_MINIMAS = 8


def pontuacao_compra(posicao, total) -> pd.Series | float:
    """Posição no ranking -> 0 a 100 (100 = melhor do universo no dia)."""
    return 100.0 * (total - posicao) / max(total - 1, 1)


def pontuacao_venda(compra_hoje: float, compra_antes: float | None) -> float:
    """Quanto mais no fundo do ranking, e quanto mais caiu em ~10 pregões, maior.
    = (100 − compra) + metade da queda recente da pontuação, limitado a 0–100."""
    queda = max(0.0, (compra_antes or compra_hoje) - compra_hoje)
    return float(np.clip(100.0 - compra_hoje + 0.5 * queda, 0, 100))


def faixa_de(compra: float) -> int:
    return int(min(max(compra, 0.0) // FAIXA * FAIXA, 100 - FAIXA))   # arredondamento nunca cria faixa negativa


def retornos_futuros(retornos: pd.DataFrame, horizonte: int, minimo: float = 0.8) -> pd.DataFrame:
    """Retorno acumulado do fechamento de d+1 ao de d+1+h (execução no pregão seguinte ao ranking).
    NaN se a ação não negociou em ao menos `minimo` dos dias da janela."""
    log = np.log1p(retornos.fillna(0.0))
    negociou = retornos.notna().astype(float)
    soma = log[::-1].rolling(horizonte, min_periods=1).sum()[::-1].shift(-2)
    dias = negociou[::-1].rolling(horizonte, min_periods=1).sum()[::-1].shift(-2)
    acumulado = np.expm1(soma).where(dias >= minimo * horizonte)
    return acumulado.iloc[: max(len(acumulado) - horizonte - 1, 0)]


def calibrar(scores: pd.DataFrame, retornos: pd.DataFrame, mercado: str = "BOVA11") -> pd.DataFrame:
    """scores: data, ticker, score (histórico fora da amostra) · retornos: pregões × tickers (retorno total)."""
    sc = scores.copy()
    sc["data"] = pd.to_datetime(sc["data"])
    sc["compra"] = sc.groupby("data")["score"].rank(pct=True, method="first")
    n = sc.groupby("data")["score"].transform("size")
    sc["compra"] = (100.0 * (sc["compra"] * n - 1) / (n - 1).clip(lower=1)).clip(0, 100)
    sc["faixa"] = sc["compra"].map(faixa_de)
    linhas = []
    for h, rotulo in PRAZOS.items():
        fut = retornos_futuros(retornos, h)
        if mercado not in fut:
            continue
        longo = fut.stack().rename("retorno").reset_index()
        longo.columns = ["data", "ticker", "retorno"]
        mkt = fut[mercado].rename("mercado")
        df = sc.merge(longo, on=["data", "ticker"]).merge(mkt, left_on="data", right_index=True)
        df = df.dropna(subset=["retorno", "mercado"])
        if df.empty:
            continue
        df["excesso"] = df["retorno"] - df["mercado"]
        datas = sorted(df["data"].unique())
        independentes = set(datas[::h])            # janelas que não se sobrepõem
        for faixa, g in df.groupby("faixa"):
            por_data = g.groupby("data")["excesso"].mean()
            serie = por_data[por_data.index.isin(independentes)]
            t = (serie.mean() / (serie.std(ddof=1) / np.sqrt(len(serie)))) if len(serie) > 2 and serie.std() > 0 else np.nan
            excesso, chance = g["excesso"].mean(), (g["excesso"] > 0).mean()
            if len(serie) < JANELAS_MINIMAS or not np.isfinite(t) or abs(t) < T_MINIMO:
                sinal = "sem sinal claro"
            else:
                sinal = "compra" if excesso > 0 else "venda"
            # comportamento só afirma o que a evidência sustenta (mesmo critério do sinal)
            comportamento = {"compra": "tende a superar o mercado", "venda": "tende a ficar abaixo do mercado"}.get(
                sinal, "sem diferença comprovada em relação ao mercado")
            linhas.append({
                "horizonte": h, "prazo": rotulo, "faixa_min": int(faixa), "faixa_max": int(faixa) + FAIXA,
                "n": int(len(g)), "janelas_independentes": int(len(serie)),
                "retorno_medio": float(g["retorno"].mean()), "retorno_mediano": float(g["retorno"].median()),
                "p25": float(g["retorno"].quantile(0.25)), "p75": float(g["retorno"].quantile(0.75)),
                "excesso_medio": float(excesso), "chance_superar": float(chance),
                "t": float(t) if np.isfinite(t) else None, "sinal": sinal, "comportamento": comportamento,
                "periodo_inicio": pd.Timestamp(min(datas)).date().isoformat(),
                "periodo_fim": pd.Timestamp(max(datas)).date().isoformat(),
            })
    return pd.DataFrame(linhas)
