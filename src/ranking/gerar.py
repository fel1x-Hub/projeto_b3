"""Geração e gravação de rankings.

`ranking_da_data(dia)` treina o modelo só com o que se sabia no corte do dia
(sinais, universo e cotações com disponivel_em <= corte, e alvos cujo pregão
final já ocorreu) e ordena o universo daquele dia. Mesma data => mesmo
ranking, não importa quantos dados futuros existam no banco.
"""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from src.db.tempo import agora_utc_iso
from src.ranking import dados, modelo
from src.sinais import base

logger = logging.getLogger(__name__)

VERSAO_MODELO = f"lgbm-v{modelo.VERSAO}"
VERSAO_WALK_FORWARD = f"wf-lgbm-v{modelo.VERSAO}"


N_FATORES = 5  # sinais que mais pesaram, por ação


def fatores(m, hoje: pd.DataFrame, colunas: list[str], n: int = N_FATORES) -> pd.DataFrame:
    """Para cada ação do dia, os `n` sinais de maior contribuição absoluta ao
    score (SHAP do LightGBM), com o percentil do sinal. Colunas: data, ticker,
    sinal, percentil, contribuicao."""
    contrib = pd.DataFrame(m.predict(hoje[colunas], pred_contrib=True)[:, :-1], columns=colunas, index=hoje.index)
    longo = contrib.stack().rename("contribuicao").reset_index()
    longo.columns = ["data", "ticker", "sinal", "contribuicao"]
    longo["percentil"] = hoje[colunas].stack().reindex(pd.MultiIndex.from_frame(longo[["data", "ticker", "sinal"]])).to_numpy()
    longo["_abs"] = longo["contribuicao"].abs()
    topo = longo.sort_values("_abs", ascending=False).groupby(["data", "ticker"]).head(n)
    return topo.drop(columns="_abs").sort_values(["ticker", "contribuicao"]).reset_index(drop=True)


def gravar_fatores(conn: sqlite3.Connection, fat: pd.DataFrame, versao: str) -> int:
    datas = sorted({d.date().isoformat() for d in fat["data"]})
    with conn:
        conn.executemany("DELETE FROM ranking_fatores WHERE versao_modelo = ? AND data = ?", [(versao, d) for d in datas])
        conn.executemany(
            "INSERT INTO ranking_fatores (data, ticker, versao_modelo, sinal, percentil, contribuicao) VALUES (?, ?, ?, ?, ?, ?)",
            [(r.data.date().isoformat(), r.ticker, versao, r.sinal,
              None if pd.isna(r.percentil) else float(r.percentil), float(r.contribuicao))
             for r in fat.itertuples(index=False)])
    return len(fat)


def com_posicao(scores: pd.DataFrame) -> pd.DataFrame:
    """Acrescenta `posicao` (1 = maior score) dentro de cada data."""
    scores = scores.dropna(subset=["score"]).copy()
    scores["posicao"] = scores.groupby("data")["score"].rank(ascending=False, method="first").astype(int)
    return scores.sort_values(["data", "posicao"]).reset_index(drop=True)


def gravar(conn: sqlite3.Connection, scores: pd.DataFrame, versao: str) -> int:
    """Substitui o ranking da `versao` nas datas presentes em `scores`."""
    ranking = com_posicao(scores)
    agora = agora_utc_iso()
    datas = sorted({d.date().isoformat() for d in ranking["data"]})
    with conn:
        conn.executemany("DELETE FROM ranking WHERE versao_modelo = ? AND data = ?", [(versao, d) for d in datas])
        conn.executemany(
            "INSERT INTO ranking (data, ticker, score, posicao, versao_modelo, disponivel_em, calculado_em) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(r.data.date().isoformat(), r.ticker, float(r.score), int(r.posicao), versao,
              base.corte(r.data.date()), agora) for r in ranking.itertuples(index=False)])
    logger.info("Ranking %s: %d linhas em %d datas", versao, len(ranking), len(datas))
    return len(ranking)


@dataclass
class RankingDoDia:
    ranking: pd.DataFrame        # data, ticker, score, posicao
    importancia: pd.Series       # contribuição média absoluta por sinal
    fatores: pd.DataFrame        # por ação: sinais que mais pesaram (ver `fatores`)
    modelo: object = None


def ranking_da_data(conn: sqlite3.Connection, dia: date, colunas: list[str] | None = None,
                    salvar_em: Path | None = None) -> RankingDoDia:
    """Ranking do dia, importância geral dos sinais e fatores por ação.
    Com `salvar_em`, grava o modelo treinado (texto do LightGBM) nessa pasta como
    <VERSAO_MODELO>_<data>.txt, para auditoria e reprodução."""
    colunas = colunas or dados.FEATURES_BASE
    ate = base.corte(dia)
    X = dados.carregar_features(conn, colunas, ate)
    alvo = dados.calcular_alvo(conn, ate)
    treino = alvo[alvo["data_alvo"] <= pd.Timestamp(dia)].merge(X.reset_index(), on=["data", "ticker"])
    if len(treino) < 1000:
        raise ValueError(f"histórico insuficiente para treinar em {dia}: {len(treino)} amostras")
    treino["y"] = modelo.alvo_de_treino(treino)
    m = modelo.treinar(treino[colunas], treino["y"])
    if salvar_em is not None:
        salvar_em.mkdir(parents=True, exist_ok=True)
        # o LightGBM (C) não grava em caminhos com acento no Windows ("Fodástica"): grava via Python
        (salvar_em / f"{VERSAO_MODELO}_{dia.isoformat()}.txt").write_text(m.model_to_string(), encoding="utf-8")

    hoje = X.xs(pd.Timestamp(dia), level="data", drop_level=False) if pd.Timestamp(dia) in X.index.get_level_values("data") else None
    if hoje is None or hoje.empty:
        raise ValueError(f"sem universo/sinais para {dia} (não foi pregão ou dados ainda não disponíveis)")
    scores = hoje.reset_index()[["data", "ticker"]].assign(score=m.predict(hoje[colunas]))
    return RankingDoDia(com_posicao(scores), modelo.importancia(m, hoje[colunas]), fatores(m, hoje, colunas), m)
