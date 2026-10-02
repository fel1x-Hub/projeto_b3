"""Consultas da API (etapa 7): tudo que as telas mostram sai daqui (regra 10).

Funções puras sobre uma conexão SQLite, que devolvem dicts e listas prontos
para JSON. Nenhuma conta é feita por LLM (regra 2).

Regra 15 (sempre atualizado):
- preço: a cotação do momento (provisória, ~15 min de atraso) quando ela é
  mais nova que o último fechamento oficial da B3; senão, o oficial;
- ranking: o provisório de hoje quando é mais novo que o oficial.
"""

import sqlite3
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from src.coleta.intradiario import pregao_em_andamento
from src.db.tempo import FUSO_B3
from src.ranking import gerar, provisorio
from src.sinais import descricoes

OFICIAL = gerar.VERSAO_MODELO
PROVISORIO = provisorio.VERSAO
HISTORICO = gerar.VERSAO_WALK_FORWARD
TOP_COMPRA = 30          # regra validada no backtest/paper trading (docs/validacao.md)
LIMITE_OBSERVAR = 60     # da carteira: 31–60 observar, abaixo de 60 considerar vender


def agora_utc() -> datetime:
    return datetime.now(timezone.utc)


def mercado_aberto(agora: datetime | None = None) -> bool:
    return pregao_em_andamento(agora or agora_utc())


def _data_brt(iso_utc: str) -> date:
    return datetime.fromisoformat(iso_utc).astimezone(FUSO_B3).date()


# ---------------------------------------------------------------- ranking

def ranking_em_vigor(conn: sqlite3.Connection, versao: str | None = None) -> dict | None:
    """Qual ranking vale agora: {data, versao, provisorio, atualizado_em}."""
    def ultimo(v):
        r = conn.execute("SELECT data, MAX(disponivel_em) FROM ranking WHERE versao_modelo = ? "
                         "AND data = (SELECT MAX(data) FROM ranking WHERE versao_modelo = ?)", (v, v)).fetchone()
        return {"data": r[0], "versao": v, "provisorio": v == PROVISORIO, "atualizado_em": r[1]} if r[0] else None

    oficial = ultimo(OFICIAL)
    if versao == "oficial":
        return oficial
    prov = ultimo(PROVISORIO)
    if prov and (oficial is None or prov["data"] > oficial["data"]):
        return prov
    return oficial


def posicoes_ranking(conn: sqlite3.Connection, vigor: dict | None) -> dict[str, tuple[int, float]]:
    if not vigor:
        return {}
    return {r[0]: (r[1], r[2]) for r in conn.execute(
        "SELECT ticker, posicao, score FROM ranking WHERE data = ? AND versao_modelo = ?",
        (vigor["data"], vigor["versao"]))}


def fatores(conn: sqlite3.Connection, vigor: dict | None, tickers: list[str] | None = None, n: int = 4) -> dict:
    """ticker -> [{sinal, nome, percentil, contribuicao, texto}] (os que mais pesaram, regra 16)."""
    if not vigor:
        return {}
    sql = ("SELECT ticker, sinal, percentil, contribuicao FROM ranking_fatores WHERE data = ? AND versao_modelo = ?")
    params: list = [vigor["data"], vigor["versao"]]
    if tickers is not None:
        sql += f" AND ticker IN ({','.join('?' * len(tickers))})"
        params += tickers
    saida: dict[str, list] = {}
    for t, sinal, pct, contrib in conn.execute(sql + " ORDER BY ticker, ABS(contribuicao) DESC", params):
        lista = saida.setdefault(t, [])
        if len(lista) < n:
            lista.append({"sinal": sinal, "nome": descricoes.nome(sinal), "percentil": pct,
                          "contribuicao": contrib, "texto": descricoes.explicar(sinal, pct, contrib)})
    return saida


def nomes(conn: sqlite3.Connection) -> dict[str, str]:
    return dict(conn.execute("SELECT ticker, nome FROM ativos"))


# ---------------------------------------------------------------- preços

def ultimos_fechamentos(conn: sqlite3.Connection) -> dict[str, dict]:
    """ticker -> {data, fechamento, anterior} dos dois últimos pregões oficiais."""
    df = pd.read_sql_query(
        "SELECT ticker, data, fechamento FROM cotacoes WHERE data >= (SELECT date(MAX(data), '-20 day') FROM cotacoes)",
        conn)
    saida = {}
    for t, g in df.sort_values("data").groupby("ticker"):
        ult = g.iloc[-1]
        saida[t] = {"data": ult["data"], "fechamento": float(ult["fechamento"]),
                    "anterior": float(g.iloc[-2]["fechamento"]) if len(g) > 1 else None}
    return saida


def precos(conn: sqlite3.Connection) -> dict[str, dict]:
    """ticker -> {preco, variacao_dia, horario, provisorio} (regra 15)."""
    saida = {}
    for t, f in ultimos_fechamentos(conn).items():
        var = f["fechamento"] / f["anterior"] - 1 if f["anterior"] else None
        saida[t] = {"preco": f["fechamento"], "variacao_dia": var, "horario": f"{f['data']}T21:00:00+00:00",
                    "provisorio": False}
    for t, preco, var, horario in conn.execute(
            "SELECT ticker, preco, variacao_dia, horario_cotacao FROM cotacao_atual"):
        oficial = saida.get(t)
        if oficial is None or _data_brt(horario).isoformat() > oficial["horario"][:10]:
            saida[t] = {"preco": preco, "variacao_dia": var, "horario": horario, "provisorio": True}
    return saida


def fatores_desdobramento(conn: sqlite3.Connection, ticker: str) -> pd.Series:
    df = pd.read_sql_query("SELECT data_ex, fator FROM proventos WHERE ticker = ? AND tipo = 'desdobramento'",
                           conn, params=(ticker,))
    return pd.Series(df["fator"].values, index=pd.to_datetime(df["data_ex"])).sort_index()


def historico_precos(conn: sqlite3.Connection, ticker: str, dias: int = 365) -> pd.DataFrame:
    """OHLCV ajustado por desdobramentos (sem degrau falso no gráfico). Preço de hoje na escala atual."""
    desde = (date.today() - timedelta(days=dias)).isoformat()
    df = pd.read_sql_query("SELECT data, abertura, maxima, minima, fechamento, volume FROM cotacoes "
                           "WHERE ticker = ? AND data >= ? ORDER BY data", conn, params=(ticker, desde))
    if df.empty:
        return df
    datas = pd.to_datetime(df["data"])
    divisor = pd.Series(1.0, index=df.index)
    for data_ex, fator in fatores_desdobramento(conn, ticker).items():
        divisor[datas < data_ex] *= fator
    for c in ("abertura", "maxima", "minima", "fechamento"):
        df[c] = df[c] / divisor
    return df


def retorno_desde(conn: sqlite3.Connection, ticker: str, desde: date, preco_atual: float | None) -> float | None:
    """Retorno de preço do papel desde o último fechamento ANTES de `desde` (ajustado por desdobramentos)."""
    hist = historico_precos(conn, ticker, dias=(date.today() - desde).days + 15)
    base = hist[pd.to_datetime(hist["data"]) < pd.Timestamp(desde)]
    if base.empty or preco_atual is None:
        return None
    return preco_atual / float(base["fechamento"].iloc[-1]) - 1


# ---------------------------------------------------------------- telas

def tabela_ranking(conn: sqlite3.Connection, vigor: dict | None, carteira: set[str] = frozenset()) -> list[dict]:
    if not vigor:
        return []
    px, nm = precos(conn), nomes(conn)
    extras = {}
    data_sinais = conn.execute("SELECT MAX(data) FROM sinais WHERE nome = 'vol_fin_rel21' AND data <= ?",
                               (vigor["data"],)).fetchone()[0]          # com nome: usa o índice (nome, data)
    for t, nome, valor in conn.execute(
            "SELECT ticker, nome, valor FROM sinais WHERE data = ? AND nome IN ('sent_media_21d', 'vol_fin_rel21')",
            (data_sinais,)):
        extras.setdefault(t, {})[nome] = valor
    linhas = []
    for t, pos, score in conn.execute(
            "SELECT ticker, posicao, score FROM ranking WHERE data = ? AND versao_modelo = ? ORDER BY posicao",
            (vigor["data"], vigor["versao"])):
        p = px.get(t, {})
        linhas.append({"posicao": pos, "ticker": t, "nome": nm.get(t), "score": score,
                       "preco": p.get("preco"), "variacao_dia": p.get("variacao_dia"),
                       "sentimento_21d": extras.get(t, {}).get("sent_media_21d"),
                       "volume_relativo": extras.get(t, {}).get("vol_fin_rel21"),
                       "na_carteira": t in carteira})
    return linhas


def macro(conn: sqlite3.Connection) -> dict:
    saida = {}
    for serie in ("selic_meta", "ipca", "ptax_venda", "cdi"):
        r = conn.execute("SELECT data, valor, disponivel_em FROM macro WHERE serie = ? ORDER BY data DESC LIMIT 1",
                         (serie,)).fetchone()
        if r:
            saida[serie] = {"valor": r[1], "referencia": r[0], "disponivel_em": r[2]}
    return saida


def ibovespa(conn: sqlite3.Connection) -> dict | None:
    """Ibovespa do momento (yfinance ^BVSP); sem ele, o BOVA11 oficial como referência."""
    r = conn.execute("SELECT preco, variacao_dia, horario_cotacao FROM cotacao_atual WHERE ticker = 'IBOV'").fetchone()
    f = ultimos_fechamentos(conn).get("BOVA11")
    if r and (f is None or _data_brt(r[2]).isoformat() > f["data"]):  # nunca o intradiário de um dia já fechado
        return {"nome": "Ibovespa", "valor": r[0], "variacao_dia": r[1], "horario": r[2], "provisorio": True}
    if f:
        return {"nome": "BOVA11", "valor": f["fechamento"],
                "variacao_dia": f["fechamento"] / f["anterior"] - 1 if f["anterior"] else None,
                "horario": f"{f['data']}T21:00:00+00:00", "provisorio": False}
    return None


def status_fontes(conn: sqlite3.Connection) -> list[dict]:
    """Última execução de cada coleta (para a tela mostrar fonte com falha, regra 15)."""
    return [{"fonte": r[0], "status": r[1], "inicio": r[2], "erro": r[3]} for r in conn.execute(
        "SELECT e.fonte, e.status, e.inicio, e.erro FROM execucoes_coleta e "
        "JOIN (SELECT fonte, MAX(id) id FROM execucoes_coleta GROUP BY fonte) u ON u.id = e.id ORDER BY e.fonte")]


def sinais_atuais(conn: sqlite3.Connection, ticker: str) -> dict:
    """Sinais do último pregão: valor, percentil no universo do dia e descrição."""
    dia = conn.execute("SELECT MAX(data) FROM sinais WHERE ticker = ?", (ticker,)).fetchone()[0]
    if not dia:
        return {"data": None, "sinais": []}
    df = pd.read_sql_query(
        "SELECT s.ticker, s.nome, s.valor FROM sinais s JOIN universo u ON u.data = s.data AND u.ticker = s.ticker "
        "WHERE s.data = ?", conn, params=(dia,))
    df["percentil"] = df.groupby("nome")["valor"].rank(pct=True)
    minhas = df[df["ticker"] == ticker]
    if minhas.empty:  # fora do universo do dia: valores sem percentil
        minhas = pd.read_sql_query("SELECT nome, valor FROM sinais WHERE ticker = ? AND data = ?", conn,
                                   params=(ticker, dia)).assign(percentil=None)
    sinais = [{"sinal": r.nome, "nome": descricoes.nome(r.nome), "valor": float(r.valor),
               "percentil": None if pd.isna(r.percentil) else float(r.percentil),
               "nivel": descricoes.nivel(None if pd.isna(r.percentil) else r.percentil, r.nome in descricoes.FEMININOS)}
              for r in minhas.sort_values("nome").itertuples()]
    return {"data": dia, "sinais": sinais}


def historico_score(conn: sqlite3.Connection, ticker: str, dias: int = 365) -> list[dict]:
    """Posição e score ao longo do tempo: walk-forward (fora da amostra) + oficial."""
    desde = (date.today() - timedelta(days=dias)).isoformat()
    linhas = conn.execute(
        "SELECT r.data, r.versao_modelo, r.posicao, r.score, "
        "(SELECT COUNT(*) FROM ranking x WHERE x.data = r.data AND x.versao_modelo = r.versao_modelo) "
        "FROM ranking r WHERE r.ticker = ? AND r.versao_modelo IN (?, ?) AND r.data >= ? ORDER BY r.data",
        (ticker, HISTORICO, OFICIAL, desde)).fetchall()
    por_data = {}
    for d, v, pos, score, total in linhas:  # oficial tem prioridade sobre o walk-forward no mesmo dia
        if d not in por_data or v == OFICIAL:
            por_data[d] = {"data": d, "posicao": pos, "total": total, "score": score}
    return list(por_data.values())


def noticias(conn: sqlite3.Connection, ticker: str, n: int = 20) -> list[dict]:
    return [{"titulo": r[0], "url": r[1], "fonte": r[2], "disponivel_em": r[3], "sentimento": r[4]}
            for r in conn.execute(
                "SELECT n.titulo, n.url, n.fonte, n.disponivel_em, s.score FROM noticias_ativos na "
                "JOIN noticias n ON n.id = na.noticia_id LEFT JOIN sentimento_noticias s ON s.noticia_id = n.id "
                "WHERE na.ticker = ? ORDER BY n.disponivel_em DESC LIMIT ?", (ticker, n))]


def fatos_relevantes(conn: sqlite3.Connection, ticker: str | None = None, desde: str | None = None,
                     n: int = 10) -> list[dict]:
    """Fatos da CVM com a classificação do LLM (texto completo tem prioridade sobre o título)."""
    filtro, params = [], []
    if ticker:
        filtro.append("a.ticker = ?")
        params.append(ticker)
    if desde:
        filtro.append("d.disponivel_em >= ?")
        params.append(desde)
    onde = " AND ".join(filtro) or "1 = 1"
    linhas = conn.execute(
        "SELECT a.ticker, d.id, d.disponivel_em, d.tipo, d.assunto, d.url, e.tipo_evento, e.direcao, e.resumo, e.modelo "
        "FROM documentos d JOIN ativos dono ON dono.ticker = d.ticker "
        "JOIN ativos a ON a.codigo_cvm = dono.codigo_cvm "
        "LEFT JOIN eventos_documentos e ON e.documento_id = d.id "
        f"WHERE d.tipo = 'Fato Relevante' AND {onde} ORDER BY d.disponivel_em DESC, e.modelo LIKE '%:titulos' LIMIT ?",
        (*params, n * 4)).fetchall()
    saida, vistos = [], set()
    for t, doc, disp, tipo, assunto, url, evento, direcao, resumo, _ in linhas:
        if (t, doc) in vistos:
            continue
        vistos.add((t, doc))
        saida.append({"ticker": t, "data": _data_brt(disp).isoformat(), "assunto": assunto, "url": url,
                      "evento": evento, "direcao": direcao, "resumo": resumo})
    return saida[:n]
