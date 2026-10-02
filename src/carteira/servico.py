"""Carteira do usuário montada para as telas (regra 16): posições × preço do
momento × ranking em vigor, com indicações e alertas.

Fonte da quantidade: a foto sincronizada da corretora (Meu Pluggy), quando
existe; senão, as operações. O custo vem das operações (preço médio) e, se o
papel não tiver operações, do valor aplicado que a corretora informa.
"""

import sqlite3
from datetime import date

import pandas as pd

from src.api import consultas
from src.carteira import posicoes as pos
from src.db.nuvem import ler_df


def operacoes(conn: sqlite3.Connection) -> pd.DataFrame:
    return ler_df(conn, "SELECT id, ticker, tipo, data, quantidade, preco, custos, origem FROM carteira_operacoes "
                        "ORDER BY data, id")


def proventos_de(conn: sqlite3.Connection, tickers: list[str]) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame(columns=["ticker", "tipo", "data_ex", "valor", "fator"])
    return ler_df(conn, f"SELECT ticker, tipo, data_ex, valor, fator FROM proventos "
                        f"WHERE ticker IN ({','.join('?' * len(tickers))})", tickers)


ISENCAO_MENSAL_ACOES = 20_000.0   # vendas de ações no mês até este valor: lucro isento de IR (pessoa física)
ALIQUOTA_ACOES = 0.15             # operações comuns (não day trade)


def simular_venda(valor: float | None, custo: float | None, eh_acao: bool) -> dict | None:
    """Vender a posição inteira agora: valor, lucro e IR estimado (regra simplificada; não é orientação fiscal)."""
    if valor is None or not custo:
        return None
    lucro = valor - custo
    if not eh_acao:
        regra = "FII/ETF/BDR têm regras de IR próprias (sem a isenção de R$ 20 mil): confira antes de vender"
        ir = None
    elif lucro <= 0:
        regra = "sem lucro: não há IR (o prejuízo pode compensar lucros futuros em ações)"
        ir = 0.0
    else:
        regra = (f"isento se o total vendido em ações no mês ficar até R$ 20 mil; acima disso, 15% sobre o lucro")
        ir = ALIQUOTA_ACOES * lucro
    return {"valor": valor, "lucro": lucro, "ir_se_tributado": ir, "regra_ir": regra,
            "isento_se_so_esta_venda": eh_acao and valor <= ISENCAO_MENSAL_ACOES}


def leitura(posicao: int | None) -> str:
    """Leitura do ranking para um papel que o usuário TEM (não é recomendação)."""
    if posicao is None:
        return "sem leitura"          # fora do universo do modelo (FII, ETF, ilíquido...)
    if posicao <= consultas.TOP_COMPRA:
        return "manter"
    if posicao <= consultas.LIMITE_OBSERVAR:
        return "observar"
    return "considerar vender"


def montar(conn: sqlite3.Connection, hoje: date | None = None) -> dict:
    hoje = hoje or date.today()
    ops = operacoes(conn)
    sync = {r[0]: r for r in conn.execute(
        "SELECT ticker, quantidade, valor_aplicado, valor_corretora, instituicao, data_corretora, sincronizado_em "
        "FROM carteira_sincronizada")}
    tickers = sorted(set(ops["ticker"]) | set(sync))
    calc = pos.calcular(ops, proventos_de(conn, tickers))
    px = consultas.precos(conn)
    vigor = consultas.ranking_em_vigor(conn)
    rank = consultas.posicoes_ranking(conn, vigor)
    total_ranking = len(rank)
    fat = consultas.fatores(conn, vigor, tickers)
    notas = consultas.pontuacoes(conn, vigor)
    acoes = {r[0] for r in conn.execute("SELECT ticker FROM ativos WHERE tipo = 'acao'")}
    nomes = consultas.nomes(conn)

    linhas, avisos = [], []
    for t in tickers:
        c = calc.get(t, pos.Posicao(t))
        avisos += [f"{t}: {a}" for a in c.avisos]
        if t in sync:
            qtd = float(sync[t][1])
            if t in calc and abs(c.quantidade - qtd) > 1e-6:
                avisos.append(f"{t}: corretora informa {qtd:g}, operações registradas somam {c.quantidade:g}")
            custo = c.preco_medio * qtd if c.preco_medio else sync[t][2]
        else:
            qtd, custo = c.quantidade, c.custo
        if qtd <= 0:
            continue
        p = px.get(t, {})
        preco = p.get("preco")
        valor = qtd * preco if preco else (sync[t][3] if t in sync else None)
        var = p.get("variacao_dia")
        ganho_dia = valor - valor / (1 + var) if valor is not None and var is not None else None
        posicao_rank = rank.get(t, (None, None))[0]
        linhas.append({
            "ticker": t, "nome": nomes.get(t), "quantidade": qtd,
            "preco_medio": custo / qtd if custo else None, "custo": custo,
            "preco": preco, "preco_horario": p.get("horario"), "provisorio": p.get("provisorio", False),
            "valor": valor, "variacao_dia": var, "ganho_dia": ganho_dia,
            "ganho": valor - custo if valor is not None and custo else None,
            "ganho_pct": valor / custo - 1 if valor is not None and custo else None,
            "retorno_mes": consultas.retorno_desde(conn, t, hoje.replace(day=1), preco),
            "retorno_ano": consultas.retorno_desde(conn, t, hoje.replace(month=1, day=1), preco),
            "proventos": c.proventos, "lucro_realizado": c.lucro_realizado,
            "primeira_compra": c.primeira_compra.isoformat() if c.primeira_compra else None,
            "fonte_quantidade": "corretora" if t in sync else "operacoes",
            "posicao_ranking": posicao_rank, "total_ranking": total_ranking,
            "leitura": leitura(posicao_rank), "fatores": fat.get(t, []),
            "pontuacao_compra": notas.get(t, {}).get("compra"), "pontuacao_venda": notas.get(t, {}).get("venda"),
            "chance_cair": notas.get(t, {}).get("chance_cair"),
            "vender_agora": simular_venda(valor, custo, t in acoes),
        })

    valor_total = sum(l["valor"] or 0 for l in linhas)
    custo_total = sum(l["custo"] or 0 for l in linhas)
    for l in linhas:
        l["peso"] = (l["valor"] or 0) / valor_total if valor_total else None
    datas = [l["primeira_compra"] for l in linhas if l["primeira_compra"]]
    inicio = min(datas) if datas else None
    ibov = consultas.retorno_desde(conn, "BOVA11", date.fromisoformat(inicio), px.get("BOVA11", {}).get("preco")) \
        if inicio else None
    realizados = sum(c.lucro_realizado for c in calc.values())
    recebidos = sum(c.proventos for c in calc.values())
    return {
        "posicoes": sorted(linhas, key=lambda l: -(l["valor"] or 0)),
        "totais": {"valor": valor_total, "custo": custo_total,
                   "ganho": valor_total - custo_total if custo_total else None,
                   "ganho_pct": valor_total / custo_total - 1 if custo_total else None,
                   "ganho_dia": sum(l["ganho_dia"] or 0 for l in linhas),
                   "lucro_realizado": realizados, "proventos": recebidos,
                   "inicio": inicio, "ibovespa_desde_inicio": ibov},
        "sincronizada_em": max((s[6] for s in sync.values()), default=None),
        "instituicoes": sorted({s[4] for s in sync.values()}),
        "ranking": vigor,
        "avisos": avisos,
    }


def indicacoes(conn: sqlite3.Connection, carteira: dict | None = None) -> dict:
    """Comprar: top 30 fora da carteira. Vender/observar: papéis da carteira que caíram (regra 16)."""
    carteira = carteira or montar(conn)
    vigor = carteira["ranking"]
    tenho = {p["ticker"] for p in carteira["posicoes"]}
    tabela = consultas.tabela_ranking(conn, vigor, tenho)
    comprar = [l for l in tabela if l["posicao"] <= consultas.TOP_COMPRA and not l["na_carteira"]]
    fat = consultas.fatores(conn, vigor, [l["ticker"] for l in comprar])
    for l in comprar:
        l["fatores"] = fat.get(l["ticker"], [])
    por_leitura = {k: [p for p in carteira["posicoes"] if p["leitura"] == k]
                   for k in ("considerar vender", "observar", "manter", "sem leitura")}
    return {"comprar": comprar, "vender": por_leitura["considerar vender"], "observar": por_leitura["observar"],
            "manter": por_leitura["manter"], "sem_leitura": por_leitura["sem leitura"], "ranking": vigor,
            "regra": f"Comprar = top {consultas.TOP_COMPRA} do ranking fora da carteira; observar = posição "
                     f"{consultas.TOP_COMPRA + 1}–{consultas.LIMITE_OBSERVAR}; considerar vender = abaixo de "
                     f"{consultas.LIMITE_OBSERVAR}. A regra top 30 empatou com Ibovespa/CDI no backtest após custos."}


def evolucao(conn: sqlite3.Connection, dias: int = 365) -> list[dict]:
    """Patrimônio diário da carteira (operações × fechamento oficial) e Ibovespa (BOVA11) na mesma base."""
    ops = operacoes(conn)
    if ops.empty:
        return []
    inicio = max(pd.Timestamp(ops["data"].min()), pd.Timestamp.today().normalize() - pd.Timedelta(days=dias))
    tickers = sorted(set(ops["ticker"]) | {"BOVA11"})
    px = ler_df(
        conn, f"SELECT ticker, data, fechamento FROM cotacoes WHERE data >= ? AND ticker IN ({','.join('?' * len(tickers))})",
        [inicio.date().isoformat(), *tickers], parse_dates=["data"]
    ).pivot(index="data", columns="ticker", values="fechamento").sort_index().ffill()
    if px.empty:
        return []
    qtd = pos.quantidade_em(ops, proventos_de(conn, tickers), px.index)
    valor = (qtd * px.reindex(columns=qtd.columns)).sum(axis=1)
    aportes = pd.Series(0.0, index=px.index)
    for o in ops.itertuples():
        d = px.index[px.index >= pd.Timestamp(o.data)]
        if len(d):
            bruto = o.quantidade * o.preco
            aportes[d[0]] += bruto + o.custos if o.tipo == "compra" else -(bruto - o.custos)  # venda: entra líquido
    investido = aportes.cumsum()
    bova = px.get("BOVA11")
    saida = []
    for d in px.index:
        saida.append({"data": d.date().isoformat(), "valor": float(valor[d]), "investido": float(investido[d]),
                      "ibovespa_base": float(bova[d] / bova.iloc[0]) if bova is not None and pd.notna(bova[d]) else None})
    return saida
