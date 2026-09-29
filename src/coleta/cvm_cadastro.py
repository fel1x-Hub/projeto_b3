"""Cadastro CVM: preenche `cnpj` e `codigo_cvm` dos ativos e valida os tickers.

- FCA (valor mobiliário): ticker -> CNPJ. Usa o ano corrente e o anterior,
  porque o FCA do ano só existe depois que a empresa o entrega.
- Units nem sempre aparecem como código de negociação; nesse caso busca pelo
  radical (4 letras) se ele levar a um único CNPJ e, por último, usa o CNPJ
  informado manualmente na coluna `cnpj` de config/ativos.csv.
- cad_cia_aberta.csv: CNPJ -> código CVM (preferindo o registro ATIVO).
Benchmarks (ETFs) não são empresas e ficam de fora.
"""

import logging
import sqlite3
from datetime import date

from src.coleta import cvm_comum
from src.coleta.cliente_http import ClienteHTTP
from src.coleta.execucao import ColetaParcial
from src.db.tempo import agora_utc_iso, hoje_brt

logger = logging.getLogger(__name__)

FONTE = "cvm_cadastro"


def _mapa_ticker_cnpj(linhas_fca: list[dict]) -> tuple[dict[str, str], dict[str, set[str]]]:
    """Devolve ({ticker: cnpj}, {radical: {cnpjs}}), com a informação mais recente
    prevalecendo (linhas ordenadas por data de referência e versão)."""
    por_ticker: dict[str, str] = {}
    por_radical: dict[str, set[str]] = {}
    linhas = sorted(linhas_fca, key=lambda r: (r["Data_Referencia"], int(r["Versao"] or 0)))
    for r in linhas:
        ticker = (r["Codigo_Negociacao"] or "").strip().upper()
        if not ticker or r["Data_Fim_Negociacao"]:
            continue
        por_ticker[ticker] = r["CNPJ_Companhia"]
        por_radical.setdefault(ticker[:4], set()).add(r["CNPJ_Companhia"])
    return por_ticker, por_radical


def _mapa_cnpj_codigo(linhas_cad: list[dict]) -> dict[str, str]:
    mapa: dict[str, str] = {}
    for r in sorted(linhas_cad, key=lambda r: r["SIT"] == "ATIVO"):  # ATIVO por último = prevalece
        if r["CD_CVM"]:
            mapa[r["CNPJ_CIA"]] = cvm_comum.normalizar_codigo_cvm(r["CD_CVM"])
    return mapa


def coletar(conn: sqlite3.Connection, desde: date, http: ClienteHTTP | None = None) -> int:
    http = http or ClienteHTTP()
    ano = hoje_brt().year

    linhas_fca: list[dict] = []
    for a in (ano - 1, ano):
        try:
            zip_fca = cvm_comum.baixar(http, f"DOC/FCA/DADOS/fca_cia_aberta_{a}.zip", ano=a)
        except Exception as e:  # o FCA do ano pode ainda não existir em janeiro
            logger.warning("FCA %d indisponível: %s", a, e)
            continue
        linhas_fca += cvm_comum.ler_csv(zip_fca, f"fca_cia_aberta_valor_mobiliario_{a}.csv")
    if not linhas_fca:
        raise RuntimeError("nenhum arquivo FCA disponível")
    por_ticker, por_radical = _mapa_ticker_cnpj(linhas_fca)

    cad = cvm_comum.baixar(http, "CAD/DADOS/cad_cia_aberta.csv")
    cnpj_para_codigo = _mapa_cnpj_codigo(cvm_comum.ler_csv(cad))

    atualizados, nao_encontrados = 0, []
    acoes = conn.execute("SELECT ticker, cnpj, codigo_cvm FROM ativos WHERE ativo = 1 AND tipo = 'acao'").fetchall()
    with conn:
        for a in acoes:
            ticker = a["ticker"]
            cnpj = por_ticker.get(ticker)
            if cnpj is None and len(por_radical.get(ticker[:4], ())) == 1:
                cnpj = next(iter(por_radical[ticker[:4]]))
                logger.info("%s não consta no FCA; identificado pelo radical %s", ticker, ticker[:4])
            if cnpj is None and a["cnpj"]:
                # a própria empresa pode preencher o FCA errado (ex: BTG informa a
                # unit como '000000'); vale o CNPJ informado em config/ativos.csv
                cnpj = a["cnpj"]
                logger.info("%s não consta no FCA; usando CNPJ do ativos.csv", ticker)
            codigo = cnpj_para_codigo.get(cnpj) if cnpj else None
            if not cnpj or not codigo:
                nao_encontrados.append(ticker)
                continue
            if (a["cnpj"], a["codigo_cvm"]) != (cnpj, codigo):
                conn.execute(
                    "UPDATE ativos SET cnpj = ?, codigo_cvm = ?, atualizado_em = ? WHERE ticker = ?",
                    (cnpj, codigo, agora_utc_iso(), ticker),
                )
                atualizados += 1

    if nao_encontrados:
        raise ColetaParcial(atualizados, f"tickers não encontrados na CVM: {', '.join(nao_encontrados)}")
    return atualizados
