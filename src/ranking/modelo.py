"""Modelo de ranking (LightGBM) com validação walk-forward, baselines e métricas.

Walk-forward: a cada refit (início de trimestre), treina com as amostras cujo
alvo já era conhecido (data_alvo <= refit, o que equivale a um intervalo do
tamanho do horizonte entre treino e teste) e prevê o trimestre seguinte.
Nunca há divisão aleatória.

Hiperparâmetros modestos e fixos (sem busca): árvores rasas, muitas amostras
por folha e regularização, para não decorar ruído com poucas ações.
"""

import logging

import lightgbm as lgb
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

VERSAO = 1
PARAMETROS = {
    "objective": "regression",
    "learning_rate": 0.03,
    "num_leaves": 15,
    "min_data_in_leaf": 500,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 10.0,
    "seed": 42,
    "deterministic": True,
    "num_threads": 1,
    "verbose": -1,
}
N_ARVORES = 300

# Modelo v2 (docs/ranking_v2.md): direção econômica imposta a alguns sinais.
# +1 = maior percentil nunca piora o score; -1 = nunca melhora. Os demais ficam livres.
MONOTONIA = {
    "fund_lp": 1, "fund_roe": 1, "fund_margem_liq": 1, "fund_margem_ebitda": 1,
    "fund_pvp": -1, "fund_pl": -1, "fund_divliq_ebitda": -1, "vol_21d": -1, "vol_63d": -1,
}
TREINO_MINIMO_DIAS = 252  # ~1 ano de alvos conhecidos antes do primeiro teste


def treinar(X: pd.DataFrame, y: pd.Series, monotonia: dict[str, int] | None = None) -> lgb.Booster:
    """monotonia: {sinal: +1/-1} (None = v1, sem restrições)."""
    params = dict(PARAMETROS)
    if monotonia:
        params["monotone_constraints"] = [int(monotonia.get(c, 0)) for c in X.columns]
    return lgb.train(params, lgb.Dataset(X, label=y), num_boost_round=N_ARVORES)


def alvo_de_treino(alvo: pd.DataFrame) -> pd.Series:
    """Percentil do retorno relativo dentro do dia (robusto a outliers)."""
    return alvo.groupby("data")["retorno_relativo"].rank(pct=True)


def datas_de_refit(datas: pd.DatetimeIndex, minimo: int = TREINO_MINIMO_DIAS) -> list[pd.Timestamp]:
    """Primeiro pregão de cada trimestre, depois de `minimo` pregões de histórico."""
    datas = pd.DatetimeIndex(sorted(set(datas)))
    candidatas = datas[minimo:]
    trimestres = pd.Series(candidatas, index=candidatas).groupby(candidatas.to_period("Q")).first()
    return list(trimestres)


def walk_forward(features: pd.DataFrame, alvo: pd.DataFrame, colunas: list[str],
                 monotonia: dict[str, int] | None = None) -> pd.DataFrame:
    """Previsões fora da amostra: data, ticker, score, refit."""
    dados = alvo.merge(features[colunas].reset_index(), on=["data", "ticker"], how="inner")
    dados["y"] = alvo_de_treino(dados)
    todas = features.reset_index()[["data", "ticker"]].merge(features[colunas].reset_index(), on=["data", "ticker"])
    refits = datas_de_refit(pd.DatetimeIndex(features.index.get_level_values("data")))
    previsoes = []
    for i, refit in enumerate(refits):
        fim = refits[i + 1] if i + 1 < len(refits) else None
        treino = dados[dados["data_alvo"] <= refit]
        teste = todas[(todas["data"] >= refit) & ((todas["data"] < fim) if fim is not None else True)]
        if len(treino) < 1000 or teste.empty:
            continue
        modelo = treinar(treino[colunas], treino["y"], monotonia)
        previsoes.append(teste[["data", "ticker"]].assign(score=modelo.predict(teste[colunas]), refit=refit))
        logger.info("refit %s: treino %d amostras (até %s), teste %d", refit.date(), len(treino),
                    treino["data"].max().date(), len(teste))
    return pd.concat(previsoes, ignore_index=True) if previsoes else pd.DataFrame(columns=["data", "ticker", "score", "refit"])


def importancia(modelo: lgb.Booster, X: pd.DataFrame) -> pd.Series:
    """Contribuição média absoluta de cada feature (valores SHAP do próprio LightGBM)."""
    contrib = modelo.predict(X, pred_contrib=True)[:, :-1]  # última coluna é o valor base
    return pd.Series(np.abs(contrib).mean(axis=0), index=X.columns).sort_values(ascending=False)


# ---------------------------------------------------------------- avaliação

def ic_diario(scores: pd.DataFrame, alvo: pd.DataFrame, minimo_acoes: int = 20) -> pd.Series:
    """Correlação de Spearman, dia a dia, entre score e retorno futuro."""
    df = scores.merge(alvo[["data", "ticker", "retorno_futuro"]], on=["data", "ticker"]).dropna(subset=["score"])
    df = df.groupby("data").filter(lambda g: len(g) >= minimo_acoes)
    return df.groupby("data").apply(
        lambda g: g["score"].rank().corr(g["retorno_futuro"].rank()), include_groups=False).rename("ic")


def spread_decis(scores: pd.DataFrame, alvo: pd.DataFrame) -> pd.Series:
    """Retorno futuro médio do decil do topo menos o do fundo, por dia."""
    df = scores.merge(alvo[["data", "ticker", "retorno_futuro"]], on=["data", "ticker"]).dropna(subset=["score"])
    df["decil"] = df.groupby("data")["score"].transform(lambda s: pd.qcut(s.rank(method="first"), 10, labels=False))
    por_dia = df.groupby(["data", "decil"])["retorno_futuro"].mean().unstack()
    return (por_dia[9] - por_dia[0]).rename("spread")


def resumo(ic: pd.Series, spread: pd.Series, horizonte: int) -> dict:
    """Métricas agregadas. Para t-stat usa só dias sem sobreposição de horizonte."""
    nao_sobrepostos = ic.iloc[::horizonte]
    t = nao_sobrepostos.mean() / (nao_sobrepostos.std(ddof=1) / np.sqrt(len(nao_sobrepostos))) if len(nao_sobrepostos) > 2 else np.nan
    return {"ic_medio": ic.mean(), "ic_desvio": ic.std(), "ic_positivo": (ic > 0).mean(), "t_ic": t,
            "spread_medio": spread.mean(), "dias": len(ic)}
