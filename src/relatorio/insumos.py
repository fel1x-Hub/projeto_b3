"""Insumos do relatório diário, calculados em CÓDIGO (regra 2).

Todo número sai daqui já formatado em texto (ex.: "+1,03%", "0,587"): o LLM
só copia. A checagem (checagem.py) confere que cada número do texto final
aparece nestes insumos.
"""

import sqlite3
from datetime import date, timedelta

from src.ranking import gerar
from src.sinais import descricoes


def pct(x: float | None, casas: int = 2, sinal: bool = True) -> str | None:
    if x is None:
        return None
    s = f"{x * 100:+.{casas}f}%" if sinal else f"{x * 100:.{casas}f}%"
    return s.replace(".", ",")


def num(x: float | None, casas: int = 2) -> str | None:
    return None if x is None else f"{x:.{casas}f}".replace(".", ",")


def _retorno_bova(conn, dia: date, dias: int) -> float | None:
    linhas = conn.execute("SELECT fechamento FROM cotacoes WHERE ticker = 'BOVA11' AND data <= ? "
                          "ORDER BY data DESC LIMIT ?", (dia.isoformat(), dias + 1)).fetchall()
    return linhas[0][0] / linhas[-1][0] - 1 if len(linhas) == dias + 1 else None


def _macro(conn, dia: date) -> dict:
    saida = {}
    for serie, rotulo, formato in (("selic_meta", "Selic meta (% a.a.)", lambda v: num(v)),
                                   ("ipca", "IPCA do mês (%)", lambda v: num(v)),
                                   ("ptax_venda", "Dólar PTAX (R$)", lambda v: num(v, 4))):
        linha = conn.execute("SELECT data, valor FROM macro WHERE serie = ? AND disponivel_em <= ? "
                             "ORDER BY data DESC LIMIT 1", (serie, f"{dia.isoformat()}T23:59:59+00:00")).fetchone()
        if linha:
            saida[rotulo] = {"valor": formato(linha[1]), "referencia": linha[0]}
    return saida


def _acoes(conn, dia: date, versao: str, tickers: list[str], ranking: dict) -> list[dict]:
    fatores = {}
    for r in conn.execute("SELECT ticker, sinal, percentil, contribuicao FROM ranking_fatores "
                          "WHERE data = ? AND versao_modelo = ? ORDER BY ABS(contribuicao) DESC",
                          (dia.isoformat(), versao)):
        fatores.setdefault(r[0], []).append(descricoes.explicar(r[1], r[2], r[3]))
    inicio_noticias = (dia - timedelta(days=3)).isoformat()
    inicio_eventos = (dia - timedelta(days=14)).isoformat()
    saida = []
    for t in tickers:
        noticias = [{"titulo": n[0], "sentimento": num(n[1])} for n in conn.execute(
            "SELECT n.titulo, s.score FROM noticias_ativos na JOIN noticias n ON n.id = na.noticia_id "
            "LEFT JOIN sentimento_noticias s ON s.noticia_id = n.id WHERE na.ticker = ? "
            "AND n.disponivel_em BETWEEN ? AND ? ORDER BY n.disponivel_em DESC LIMIT 3",
            (t, inicio_noticias, f"{dia.isoformat()}T22:00:00+00:00"))]
        eventos = [{"data": e[0][:10], "tipo": e[1], "direcao": e[2], "resumo": e[3]} for e in conn.execute(
            "SELECT d.disponivel_em, e.tipo_evento, e.direcao, e.resumo FROM eventos_documentos e "
            "JOIN documentos d ON d.id = e.documento_id JOIN ativos a ON a.codigo_cvm = "
            "(SELECT codigo_cvm FROM ativos WHERE ticker = ?) AND a.ticker = d.ticker "
            "WHERE d.disponivel_em BETWEEN ? AND ? ORDER BY d.disponivel_em DESC LIMIT 3",
            (t, inicio_eventos, f"{dia.isoformat()}T22:00:00+00:00"))]
        pos, score = ranking[t]
        saida.append({"ticker": t, "posicao": pos, "score": num(score, 3),
                      "fatores": fatores.get(t, [])[:4], "noticias": noticias, "fatos_relevantes": eventos})
    return saida


def montar(conn: sqlite3.Connection, dia: date, versao: str = gerar.VERSAO_MODELO, n: int = 10) -> dict:
    ranking = {r[0]: (r[1], r[2]) for r in conn.execute(
        "SELECT ticker, posicao, score FROM ranking WHERE data = ? AND versao_modelo = ? ORDER BY posicao",
        (dia.isoformat(), versao))}
    if not ranking:
        raise ValueError(f"sem ranking {versao} em {dia}")
    ordem = sorted(ranking, key=lambda t: ranking[t][0])
    anterior_data = conn.execute("SELECT MAX(data) FROM ranking WHERE versao_modelo = ? AND data < ?",
                                 (versao, dia.isoformat())).fetchone()[0]
    entraram, sairam = [], []
    if anterior_data:
        antes = [r[0] for r in conn.execute("SELECT ticker FROM ranking WHERE data = ? AND versao_modelo = ? "
                                            "AND posicao <= 30", (anterior_data, versao))]
        agora = ordem[:30]
        entraram, sairam = sorted(set(agora) - set(antes)), sorted(set(antes) - set(agora))
    paper = conn.execute("SELECT valor FROM paper_patrimonio WHERE data <= ? ORDER BY data DESC LIMIT 1",
                         (dia.isoformat(),)).fetchone()
    inicio_paper = conn.execute("SELECT valor FROM paper_config WHERE chave = 'inicio'").fetchone()
    return {
        "data": dia.isoformat(),
        "acoes_no_universo": len(ordem),
        "mercado": {"BOVA11 no dia": pct(_retorno_bova(conn, dia, 1)),
                    "BOVA11 em 21 pregões": pct(_retorno_bova(conn, dia, 21))},
        "macro": _macro(conn, dia),
        "topo": _acoes(conn, dia, versao, ordem[:n], ranking),
        "fundo": _acoes(conn, dia, versao, ordem[-n:], ranking),
        "top30_mudancas": {"desde": anterior_data, "entraram": entraram, "sairam": sairam},
        "paper_trading": {"inicio": inicio_paper[0] if inicio_paper else None,
                          "retorno_acumulado": pct(paper[0] - 1) if paper else None},
        "contexto_validacao": "No backtest (10/2022 a 09/2026) a regra top 30 rendeu +12,4% ao ano, "
                              "contra Ibovespa +12,8% e CDI +13,1%: sem vantagem comprovada após custos.",
    }
