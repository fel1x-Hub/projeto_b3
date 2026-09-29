"""Resumo de uma execução de coleta, para mostrar ao usuário."""

import sqlite3

from src.coleta.execucao import ResultadoExecucao

TABELAS = ("cotacoes", "proventos", "macro", "documentos", "demonstracoes", "noticias", "noticias_ativos")


def contar_tabelas(conn: sqlite3.Connection) -> dict[str, int]:
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABELAS}


def montar(conn: sqlite3.Connection, resultados: list[ResultadoExecucao],
           antes: dict[str, int], inicio_execucao: str) -> str:
    depois = contar_tabelas(conn)
    linhas = ["", "=== Fontes ==="]
    for r in resultados:
        linhas.append(f"  {r.fonte:<14} {r.status:<8} {r.novos:>8} novos" + (f"   ({r.erro})" if r.erro else ""))

    linhas += ["", "=== Registros por tabela (total / novos nesta execução) ==="]
    linhas += [f"  {t:<16} {depois[t]:>9} / {depois[t] - antes[t]:>7}" for t in TABELAS]

    revisoes = conn.execute("SELECT COUNT(*) FROM revisoes WHERE detectado_em >= ?", (inicio_execucao,)).fetchone()[0]
    linhas.append(f"  {'revisoes':<16} {revisoes:>9} nesta execução (correções feitas pelas fontes)")

    linhas += ["", "=== Cobertura por ativo ===",
               f"  {'ticker':<8} {'cotações de':<11} {'até':<10} {'pregões':>7} {'proventos':>9} {'docs':>5} {'notícias':>8}"]
    for r in conn.execute("""
        SELECT a.ticker,
               (SELECT MIN(data) FROM cotacoes c WHERE c.ticker = a.ticker) AS ini,
               (SELECT MAX(data) FROM cotacoes c WHERE c.ticker = a.ticker) AS fim,
               (SELECT COUNT(*) FROM cotacoes c WHERE c.ticker = a.ticker) AS pregoes,
               (SELECT COUNT(*) FROM proventos p WHERE p.ticker = a.ticker) AS proventos,
               (SELECT COUNT(*) FROM documentos d WHERE d.ticker = a.ticker) AS docs,
               (SELECT COUNT(*) FROM noticias_ativos n WHERE n.ticker = a.ticker) AS noticias
        FROM ativos a WHERE a.ativo = 1 ORDER BY a.tipo, a.ticker
    """):
        linhas.append(f"  {r['ticker']:<8} {r['ini'] or '-':<11} {r['fim'] or '-':<10} {r['pregoes']:>7} "
                      f"{r['proventos']:>9} {r['docs']:>5} {r['noticias']:>8}")

    linhas += ["", "=== Séries macro ==="]
    for r in conn.execute("SELECT serie, MIN(data) ini, MAX(data) fim, COUNT(*) n FROM macro GROUP BY serie ORDER BY serie"):
        linhas.append(f"  {r['serie']:<12} {r['ini']} a {r['fim']}  ({r['n']} valores)")

    linhas += ["", "=== Demonstrações (CVM) ==="]
    for r in conn.execute("""
        SELECT tipo_doc, COUNT(DISTINCT codigo_cvm) empresas, MIN(data_referencia) ini, MAX(data_referencia) fim,
               COUNT(DISTINCT codigo_cvm || data_referencia || versao) docs
        FROM demonstracoes GROUP BY tipo_doc"""):
        linhas.append(f"  {r['tipo_doc']}: {r['docs']} documentos de {r['empresas']} empresas, {r['ini']} a {r['fim']}")

    sem_cvm = [r[0] for r in conn.execute(
        "SELECT ticker FROM ativos WHERE ativo = 1 AND tipo = 'acao' AND codigo_cvm IS NULL")]
    falhas = [r for r in resultados if r.status != "sucesso"]
    linhas += ["", "=== Alertas ==="]
    if sem_cvm:
        linhas.append(f"  Ações sem código CVM (sem documentos/demonstrações): {', '.join(sem_cvm)}")
    for r in falhas:
        linhas.append(f"  {r.fonte}: {r.status} - {r.erro}")
    if not sem_cvm and not falhas:
        linhas.append("  nenhum")
    return "\n".join(linhas)
