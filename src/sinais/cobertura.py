"""Relatório de cobertura dos sinais: quais sinais existem para cada ativo e
período, e o percentual de valores faltantes.

Faltante = pregão do ativo (em `cotacoes`) sem valor gravado para o sinal.
"""

import sqlite3

import pandas as pd

FAMILIAS = {"ret_": "técnicos", "dist_": "técnicos", "rsi": "técnicos", "vol_": "técnicos",
            "fund_": "fundamentalistas", "sent_": "sentimento", "evt_": "eventos"}


def familia(nome: str) -> str:
    return next((f for prefixo, f in FAMILIAS.items() if nome.startswith(prefixo)), "outros")


def _tabela(df: pd.DataFrame, indice: str, colunas: str) -> str:
    return df.pivot_table(index=indice, columns=colunas, values="faltantes", aggfunc="mean").map(
        lambda v: f"{v:5.0%}" if pd.notna(v) else "    -").to_string()


def relatorio(conn: sqlite3.Connection) -> str:
    pregoes = pd.read_sql_query(
        "SELECT c.ticker, c.data FROM cotacoes c JOIN ativos a ON a.ticker = c.ticker "
        "WHERE a.ativo = 1 AND a.tipo = 'acao' AND c.fonte = 'b3_cotahist'", conn)
    sinais = pd.read_sql_query("SELECT ticker, data, nome FROM sinais", conn)
    if sinais.empty:
        return "Nenhum sinal gravado."
    nomes = sorted(sinais["nome"].unique())
    pregoes["ano"] = pregoes["data"].str[:4]

    # grade completa (pregão x sinal) marcando o que existe
    grade = pregoes.merge(pd.DataFrame({"nome": nomes}), how="cross")
    existe = sinais.assign(ok=1)
    grade = grade.merge(existe, on=["ticker", "data", "nome"], how="left")
    grade["faltantes"] = grade["ok"].isna().astype(float)
    grade["familia"] = grade["nome"].map(familia)

    por_sinal = grade.groupby("nome").agg(faltantes=("faltantes", "mean")).join(
        sinais.groupby("nome").agg(ativos=("ticker", "nunique"), inicio=("data", "min"), fim=("data", "max")))
    linhas = ["=== Por sinal ===",
              f"  {'sinal':<20} {'ativos':>6}  {'início':<10}  {'fim':<10}  {'faltantes':>9}"]
    for nome, r in por_sinal.iterrows():
        linhas.append(f"  {nome:<20} {int(r.ativos):>6}  {r.inicio:<10}  {r.fim:<10}  {r.faltantes:>9.1%}")
    linhas += ["", "=== Faltantes por ativo e família ===", _tabela(grade, "ticker", "familia"),
               "", "=== Faltantes por ano e família ===", _tabela(grade, "ano", "familia")]
    return "\n".join(linhas)
