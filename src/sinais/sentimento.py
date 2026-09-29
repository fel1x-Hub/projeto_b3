"""Sentimento de notícias: classificação por modelo pronto e agregação diária.

Modelo: FinBERT-PT-BR (lucas-leme/FinBERT-PT-BR, Apache 2.0), BERT treinado em
notícias financeiras brasileiras; roda em CPU. Classifica o TÍTULO da notícia
em positivo/neutro/negativo; score = P(positivo) - P(negativo), entre -1 e 1.

Agregação por ativo e pregão D, só com notícias associadas ao ativo e
`disponivel_em` em (corte(pregão anterior), corte(D)] — notícias de fim de
semana entram no pregão seguinte:
    sent_n_dia      quantidade de notícias (0 quando não houve nenhuma)
    sent_media_dia  score médio do dia (só se houve notícia)
    sent_media_21d  score médio das notícias dos últimos 21 pregões
    sent_delta      sent_media_dia - sent_media_21d
Só há sinais a partir do início da coleta de notícias (o RSS não tem histórico).
"""

import logging
import sqlite3
from datetime import datetime, timezone
from typing import Callable

import numpy as np
import pandas as pd

from src.db.tempo import para_iso_utc
from src.sinais import base

logger = logging.getLogger(__name__)

MODELO = "lucas-leme/FinBERT-PT-BR"
VERSAO = 1
JANELA = 21
NOMES = ["sent_n_dia", "sent_media_dia", "sent_media_21d", "sent_delta"]
VERSOES = {nome: VERSAO for nome in NOMES}
ROTULOS = {"POSITIVE": "positivo", "NEUTRAL": "neutro", "NEGATIVE": "negativo"}

Classificador = Callable[[list[str]], list[dict[str, float]]]  # textos -> [{positivo, neutro, negativo}]


def classificador_finbert(tamanho_lote: int = 32) -> Classificador:
    """Carrega o FinBERT-PT-BR (baixa ~400 MB na primeira vez) e devolve a função."""
    from transformers import pipeline

    modelo = pipeline("text-classification", model=MODELO, top_k=None, device=-1)

    def classificar(textos: list[str]) -> list[dict[str, float]]:
        saidas = modelo(textos, batch_size=tamanho_lote, truncation=True)
        return [{ROTULOS[s["label"].upper()]: float(s["score"]) for s in saida} for saida in saidas]

    return classificar


def classificar_pendentes(conn: sqlite3.Connection, classificador: Classificador | None = None,
                          modelo: str = MODELO) -> int:
    """Classifica as notícias que ainda não têm score deste modelo."""
    pendentes = conn.execute(
        "SELECT id, titulo FROM noticias WHERE id NOT IN "
        "(SELECT noticia_id FROM sentimento_noticias WHERE modelo = ?) ORDER BY id", (modelo,)
    ).fetchall()
    if not pendentes:
        return 0
    classificador = classificador or classificador_finbert()
    probs = classificador([titulo for _, titulo in pendentes])
    agora = para_iso_utc(datetime.now(timezone.utc))
    linhas = []
    for (noticia_id, _), p in zip(pendentes, probs):
        rotulo = max(p, key=p.get)
        linhas.append((noticia_id, modelo, rotulo, p["positivo"], p["neutro"], p["negativo"],
                       p["positivo"] - p["negativo"], agora))
    with conn:
        conn.executemany(
            "INSERT INTO sentimento_noticias (noticia_id, modelo, rotulo, prob_positivo, prob_neutro, "
            "prob_negativo, score, calculado_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", linhas)
    logger.info("%d notícias classificadas com %s", len(linhas), modelo)
    return len(linhas)


def sinais_ativo(pregoes: pd.Series, noticias: pd.DataFrame, inicio_cobertura: pd.Timestamp) -> pd.DataFrame:
    """`pregoes`: datas do ativo; `noticias`: colunas disponivel_em (UTC) e score."""
    pregoes = pregoes.sort_values().reset_index(drop=True)
    cortes = pd.to_datetime(pregoes.dt.date.map(base.corte), utc=True)
    # cada notícia vai para o primeiro pregão cujo corte é >= sua disponibilidade
    # .values de datas com fuso = datetime64 em UTC (comparáveis entre si)
    pos = np.searchsorted(cortes.values, noticias["disponivel_em"].values, side="left")
    noticias = noticias.assign(pos=pos)
    noticias = noticias[noticias["pos"] < len(pregoes)]
    por_dia = noticias.groupby("pos")["score"].agg(["count", "sum"]).reindex(range(len(pregoes)), fill_value=0)

    s = pd.DataFrame({"data": pregoes})
    s["sent_n_dia"] = por_dia["count"].to_numpy(dtype=float)
    s["sent_media_dia"] = (por_dia["sum"] / por_dia["count"].replace(0, np.nan)).to_numpy()
    soma = por_dia["sum"].rolling(JANELA, min_periods=1).sum()
    quantidade = por_dia["count"].rolling(JANELA, min_periods=1).sum()
    s["sent_media_21d"] = (soma / quantidade.replace(0, np.nan)).to_numpy()
    s["sent_delta"] = s["sent_media_dia"] - s["sent_media_21d"]
    # antes do início da coleta de notícias não há como saber: sem valor
    return s[(cortes >= inicio_cobertura).to_numpy()]


def calcular(conn: sqlite3.Connection, ate: str | None = None, modelo: str = MODELO) -> pd.DataFrame:
    noticias = base._ler(conn, "SELECT id, disponivel_em FROM noticias WHERE 1 = 1", ate)
    if noticias.empty:
        return pd.DataFrame(columns=["ticker", "data", "nome", "valor"])
    inicio_cobertura = pd.to_datetime(noticias["disponivel_em"].min(), utc=True)
    associadas = pd.read_sql_query(
        "SELECT na.ticker, n.disponivel_em, s.score FROM noticias_ativos na "
        "JOIN noticias n ON n.id = na.noticia_id "
        "JOIN sentimento_noticias s ON s.noticia_id = n.id AND s.modelo = ?", conn, params=(modelo,))
    if ate is not None:
        associadas = associadas[associadas["disponivel_em"] <= ate]
    associadas["disponivel_em"] = pd.to_datetime(associadas["disponivel_em"], utc=True)
    cotacoes = base.carregar_cotacoes(conn, ate)
    acoes = {r[0] for r in conn.execute("SELECT ticker FROM ativos WHERE ativo = 1 AND tipo = 'acao'")}

    partes = []
    for ticker, cot in cotacoes[cotacoes["ticker"].isin(acoes)].groupby("ticker"):
        largo = sinais_ativo(cot["data"], associadas[associadas["ticker"] == ticker], inicio_cobertura)
        longo = largo.melt(id_vars="data", var_name="nome", value_name="valor").dropna(subset=["valor"])
        longo["ticker"] = ticker
        partes.append(longo)
    if not partes:
        return pd.DataFrame(columns=["ticker", "data", "nome", "valor"])
    return pd.concat(partes, ignore_index=True)[["ticker", "data", "nome", "valor"]]
