"""Nota de venda por "chance de cair" (pedido do usuário, 02/10/2026; pré-registro em docs/venda.md).

Alvo: retorno total ABSOLUTO negativo nos próximos 21 pregões (execução no
fechamento do pregão seguinte). Classificador LightGBM com walk-forward e
retreino trimestral, mesmos hiperparâmetros regularizados do ranking.

Além dos sinais do ranking (percentis do dia), usa sinais de "esticada"
calculados só com preços até a data: distância da máxima de 252 pregões e a
variação da nota de compra em 10 pregões (histórico fora da amostra do ranking).

A chance mostrada é CALIBRADA: a probabilidade do modelo é trocada pela taxa
de queda realmente observada, fora da amostra, nas ações com probabilidade
parecida (tabela venda_calibracao).
"""

import lightgbm as lgb
import numpy as np
import pandas as pd

from src.ranking import calibracao as cal
from src.ranking import dados, modelo

VERSAO = "venda-v1"
HORIZONTE = 21
EXTRAS = ["dist_max_252", "delta_compra_10"]
COLUNAS = list(dados.FEATURES_BASE) + EXTRAS
PARAMETROS = {**modelo.PARAMETROS, "objective": "binary"}
BINS = 10


def indice_precos(retornos: pd.DataFrame) -> pd.DataFrame:
    return (1 + retornos.fillna(0.0)).cumprod().where(retornos.notna().cumsum() > 0)


def extras(retornos: pd.DataFrame, scores_wf: pd.DataFrame) -> pd.DataFrame:
    """(data, ticker) -> dist_max_252, delta_compra_10 (só passado)."""
    idx = indice_precos(retornos)
    dist = (idx / idx.rolling(252, min_periods=60).max() - 1).stack().rename("dist_max_252")
    sc = scores_wf.copy()
    sc["data"] = pd.to_datetime(sc["data"])
    sc["compra"] = 100 * sc.groupby("data")["score"].rank(pct=True)
    larg = sc.pivot(index="data", columns="ticker", values="compra").sort_index()
    delta = (larg - larg.shift(10)).stack().rename("delta_compra_10")
    out = pd.concat([dist, delta], axis=1)
    out.index.names = ["data", "ticker"]
    return out


def alvo(retornos: pd.DataFrame, horizonte: int = HORIZONTE) -> pd.DataFrame:
    """data, ticker, caiu (0/1), data_alvo (último pregão da janela: só treina depois dele)."""
    fut = cal.retornos_futuros(retornos, horizonte)
    longo = fut.stack().rename("retorno").reset_index()
    longo.columns = ["data", "ticker", "retorno"]
    datas = retornos.index
    posicao = pd.Series(np.arange(len(datas)), index=datas)
    fim = np.minimum(posicao.reindex(longo["data"]).to_numpy() + horizonte + 1, len(datas) - 1)
    longo["data_alvo"] = datas[fim]
    longo["caiu"] = (longo["retorno"] < 0).astype(int)
    return longo


def montar(X_base: pd.DataFrame, extra: pd.DataFrame) -> pd.DataFrame:
    X = X_base.join(extra, how="left")
    X[EXTRAS] = X[EXTRAS].groupby(level="data").rank(pct=True)     # percentil do dia, como os outros sinais
    return X


def treinar(X: pd.DataFrame, y: pd.Series) -> lgb.Booster:
    return lgb.train(PARAMETROS, lgb.Dataset(X, label=y), num_boost_round=modelo.N_ARVORES)


def walk_forward(X: pd.DataFrame, y: pd.DataFrame) -> pd.DataFrame:
    """Probabilidade de queda fora da amostra: data, ticker, prob."""
    dados_ = y.merge(X[COLUNAS].reset_index(), on=["data", "ticker"], how="inner")
    todas = X[COLUNAS].reset_index()
    refits = modelo.datas_de_refit(pd.DatetimeIndex(X.index.get_level_values("data")))
    saida = []
    for i, refit in enumerate(refits):
        fim = refits[i + 1] if i + 1 < len(refits) else None
        treino = dados_[dados_["data_alvo"] <= refit]
        teste = todas[(todas["data"] >= refit) & ((todas["data"] < fim) if fim is not None else True)]
        if len(treino) < 1000 or teste.empty:
            continue
        m = treinar(treino[COLUNAS], treino["caiu"])
        saida.append(teste[["data", "ticker"]].assign(prob=m.predict(teste[COLUNAS])))
    return pd.concat(saida, ignore_index=True) if saida else pd.DataFrame(columns=["data", "ticker", "prob"])


# ---------------------------------------------------------------- métricas

def auc(score: pd.Series, y: pd.Series) -> float:
    """Área sob a curva ROC (Mann-Whitney): chance de uma ação que caiu ter nota maior que uma que subiu."""
    r = score.rank()
    pos = y == 1
    n1, n0 = pos.sum(), (~pos).sum()
    return float((r[pos].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)) if n1 and n0 else float("nan")


def taxa_topo(df: pd.DataFrame, coluna: str) -> float:
    """Taxa de queda real no decil de maior nota (por dia)."""
    decil = df.groupby("data")[coluna].transform(lambda s: pd.qcut(s.rank(method="first"), 10, labels=False))
    return float(df.loc[decil == 9, "caiu"].mean())


def tabela_calibracao(prob: pd.Series, caiu: pd.Series, bins: int = BINS) -> pd.DataFrame:
    """Faixas de probabilidade (por quantis) -> taxa de queda observada."""
    faixa = pd.qcut(prob, bins, duplicates="drop")
    t = pd.DataFrame({"prob": prob, "caiu": caiu, "faixa": faixa}).groupby("faixa", observed=True).agg(
        prob_min=("prob", "min"), prob_max=("prob", "max"), prob_media=("prob", "mean"), taxa_real=("caiu", "mean"),
        n=("caiu", "size"))
    return t.reset_index(drop=True)


def chance_calibrada(prob: float, tabela: pd.DataFrame) -> float | None:
    if tabela is None or tabela.empty or prob is None:
        return None
    linha = tabela[tabela["prob_min"] <= prob].tail(1)
    linha = tabela.head(1) if linha.empty else linha
    return float(linha["taxa_real"].iloc[0])


# ---------------------------------------------------------------- produção

def calibracao_em_uso(conn) -> tuple[str | None, pd.DataFrame]:
    """(fonte, tabela): 'modelo' se o modelo novo foi aprovado no pré-registro, 'nota_atual' se não."""
    df = pd.DataFrame([tuple(r) for r in conn.execute(
        "SELECT fonte, prob_min, prob_max, prob_media, taxa_real, n FROM venda_calibracao WHERE versao = ? ORDER BY ordem",
        (VERSAO,)).fetchall()], columns=["fonte", "prob_min", "prob_max", "prob_media", "taxa_real", "n"])
    return (df["fonte"].iloc[0] if not df.empty else None), df


def prever_dia(conn, dia, retornos: pd.DataFrame, scores_hist: pd.DataFrame) -> pd.DataFrame:
    """Chance de cair no próximo mês para o universo do dia (treina com tudo o que já tem alvo realizado)."""
    from src.sinais import base
    X = montar(dados.carregar_features(conn, dados.FEATURES_BASE, base.corte(dia)), extras(retornos, scores_hist))
    y = alvo(retornos)
    treino = y[y["data_alvo"] <= pd.Timestamp(dia)].merge(X[COLUNAS].reset_index(), on=["data", "ticker"])
    if len(treino) < 1000 or pd.Timestamp(dia) not in X.index.get_level_values("data"):
        return pd.DataFrame(columns=["ticker", "prob", "chance_cair", "nota"])
    m = treinar(treino[COLUNAS], treino["caiu"])
    hoje = X.xs(pd.Timestamp(dia), level="data")
    prob = pd.Series(m.predict(hoje[COLUNAS]), index=hoje.index)
    _, tabela = calibracao_em_uso(conn)
    return pd.DataFrame({"ticker": prob.index, "prob": prob.values,
                         "chance_cair": [chance_calibrada(p, tabela) for p in prob.values],
                         "nota": (100 * prob.rank(pct=True)).round().astype(int).values})
