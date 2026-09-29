"""Sinais fundamentalistas a partir das demonstrações da CVM (DFP/ITR).

Ponto-no-tempo: para o pregão D, só entram documentos com
`disponivel_em <= corte(D)`, usando para cada (tipo, data de referência) a
maior versão disponível naquele momento.

Contas são localizadas pela DESCRIÇÃO (não só pelo código), porque bancos usam
outro plano de contas (ex.: lucro em 3.09.01 no Itaú e 3.11.01 nas demais).
Instituições financeiras (receita = "Intermediação Financeira") e holdings
(lucro maior que a receita, ex.: Itaúsa) não têm EBITDA, margens, dívida
líquida nem crescimento de receita: esses sinais ficam ausentes para elas.

Fluxos dos últimos 12 meses (TTM), assumindo exercício = ano civil:
    documento anual (DFP) em R:  TTM = valor anual
    trimestral (ITR) em R:       TTM = acumulado do ano em R
                                       + ano anterior (DFP)
                                       - acumulado do ano até R-1 ano (ITR)

Aproximações (documentadas em docs/sinais.md):
- Valor de mercado = total de ações (menos tesouraria) x preço do ticker
  acompanhado; empresas com ON e PN de preços diferentes ficam aproximadas.
- Units: o preço é dividido pelo número de ações por unit (BPAC11 = 3).
- Ações informadas na data de referência são ajustadas por desdobramentos
  posteriores já conhecidos em D.
- Ações informadas em milhares são detectadas pelo P/VP implausível (< 0,03).
"""

import re
import sqlite3
from datetime import date

import numpy as np
import pandas as pd

from src.sinais import base

VERSAO = 1
ACOES_POR_UNIDADE = {"BPAC11": 3}
NOMES = ["fund_pl", "fund_lp", "fund_pvp", "fund_roe", "fund_margem_liq", "fund_margem_ebitda",
         "fund_divliq_ebitda", "fund_cresc_receita", "fund_cresc_lucro"]
VERSOES = {nome: VERSAO for nome in NOMES}
FLUXOS = ["receita", "ebit", "lucro", "da"]


# ---------------------------------------------------------------- extração por documento

def _nivel(cd: pd.Series) -> pd.Series:
    return cd.str.count(r"\.") + 1


def _buscar(df: pd.DataFrame, padrao: str, nivel: int | None = None) -> pd.DataFrame:
    achados = df[df["ds_conta"].str.contains(padrao, flags=re.IGNORECASE, regex=True, na=False)]
    if nivel is not None:
        achados = achados[_nivel(achados["cd_conta"]) == nivel]
    return achados


def _fluxo(linhas: pd.DataFrame, data_ref: str) -> float:
    """Valor do maior período (acumulado do ano) que termina na data de referência."""
    linhas = linhas[linhas["data_fim"] == data_ref]
    if linhas.empty:
        return np.nan
    return float(linhas.sort_values("data_ini").iloc[0]["valor"])


def _saldo(linhas: pd.DataFrame) -> float:
    return float(linhas["valor"].sum()) if not linhas.empty else np.nan


def extrair_documento(doc: pd.DataFrame, data_ref: str) -> dict:
    """Valores de interesse de um documento (todas as linhas de uma versão)."""
    dre = doc[doc["demonstrativo"] == "DRE"]
    bpa = doc[doc["demonstrativo"] == "BPA"]
    bpp = doc[doc["demonstrativo"] == "BPP"]
    dva = doc[doc["demonstrativo"] == "DVA"]
    cap = doc[doc["demonstrativo"] == "CAPITAL"].set_index("cd_conta")["valor"]

    receita = dre[dre["cd_conta"] == "3.01"]
    financeira = bool(receita["ds_conta"].str.contains("Intermedia", case=False).any())

    # lucro atribuído aos controladores: filho da última conta de lucro do período
    lucro = np.nan
    liquido = _buscar(dre, r"^(?:lucro|resultado l[ií]quido).*per[ií]odo", nivel=2)
    if not liquido.empty:
        conta = liquido.sort_values("cd_conta")["cd_conta"].iloc[-1]
        filhos = dre[dre["cd_conta"].str.startswith(conta + ".")]
        controladora = _buscar(filhos, r"atribu[ií]do.*controladora")
        total = _fluxo(dre[dre["cd_conta"] == conta], data_ref)
        lucro = _fluxo(controladora, data_ref) if not controladora.empty else np.nan
        # algumas empresas sem minoritários (ex.: Sabesp) deixam a linha dos
        # controladores zerada e informam o lucro só na conta-mãe
        if (np.isnan(lucro) or lucro == 0) and not np.isnan(total):
            lucro = total

    pl = np.nan
    total_pl = _buscar(bpp, r"^patrim[oô]nio l[ií]quido", nivel=2)
    if not total_pl.empty:
        conta = total_pl["cd_conta"].iloc[0]
        nao_controladores = _buscar(bpp[bpp["cd_conta"].str.startswith(conta + ".")], r"n[aã]o controladores")
        pl = _saldo(total_pl) - (_saldo(nao_controladores) if not nao_controladores.empty else 0.0)

    acoes = np.nan
    if "QT_ACAO_TOTAL_CAP_INTEGR" in cap:
        acoes = cap["QT_ACAO_TOTAL_CAP_INTEGR"] - cap.get("QT_ACAO_TOTAL_TESOURO", 0.0)

    valores = {"financeira": financeira, "lucro": lucro, "pl": pl, "acoes": acoes,
               "receita": np.nan, "ebit": np.nan, "da": np.nan, "divida": np.nan, "caixa": np.nan}
    if not financeira:
        valores["receita"] = _fluxo(receita, data_ref)
        valores["ebit"] = _fluxo(_buscar(dre, r"^resultado antes do resultado financeiro", nivel=2), data_ref)
        valores["da"] = abs(_fluxo(_buscar(dva, r"^deprecia[cç][aã]o, amortiza[cç][aã]o", nivel=3), data_ref))
        valores["divida"] = _saldo(_buscar(bpp, r"^empr[eé]stimos e financiamentos$", nivel=3))
        caixa = bpa[bpa["cd_conta"].str.startswith("1.01.")]
        valores["caixa"] = _saldo(_buscar(caixa, r"^(?:caixa e equivalentes|aplica[cç][oõ]es financeiras)", nivel=3))
    return valores


def extrair_documentos(demonstracoes: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por (empresa, tipo, data de referência, versão) com os valores extraídos.

    Usa o consolidado quando o documento o tiver; senão o individual (empresas
    sem controladas, ou bancos em alguns ITRs antigos, só publicam o individual).
    A composição do capital (CAPITAL) é sempre individual."""
    linhas = []
    chaves = ["codigo_cvm", "tipo_doc", "data_referencia", "versao"]
    for (codigo, tipo, ref, versao), doc in demonstracoes.groupby(chaves):
        contabil = doc[doc["demonstrativo"] != "CAPITAL"]
        consolidado = int((contabil["consolidado"] == 1).any())
        doc = doc[(doc["demonstrativo"] == "CAPITAL") | (doc["consolidado"] == consolidado)]
        linhas.append({"codigo_cvm": codigo, "tipo_doc": tipo, "data_referencia": ref, "versao": versao,
                       "disponivel_em": doc["disponivel_em"].max(), **extrair_documento(doc, ref)})
    return pd.DataFrame(linhas)


# ---------------------------------------------------------------- fotografias ponto-no-tempo

def _um_ano_antes(ref: str) -> str:
    d = date.fromisoformat(ref)
    return d.replace(year=d.year - 1, day=28 if (d.month, d.day) == (2, 29) else d.day).isoformat()


def ttm(docs: dict[str, pd.Series], ref: str, campo: str) -> float:
    """Valor dos últimos 12 meses terminando em `ref`. `docs`: data_referencia -> valores."""
    if ref not in docs:
        return np.nan
    if ref.endswith("-12-31"):
        return docs[ref][campo]
    ano_anterior = f"{int(ref[:4]) - 1}-12-31"
    mesmo_periodo = _um_ano_antes(ref)
    if ano_anterior not in docs or mesmo_periodo not in docs:
        return np.nan
    return docs[ref][campo] + docs[ano_anterior][campo] - docs[mesmo_periodo][campo]


def fotografia(disponiveis: pd.DataFrame) -> dict:
    """Indicadores da empresa com os documentos disponíveis num instante."""
    ultimos = disponiveis.sort_values("versao").groupby(["tipo_doc", "data_referencia"]).tail(1)
    docs = {r.data_referencia: r for r in ultimos.itertuples(index=False)}  # DFP e ITR nunca coincidem na data
    ref = max(docs)
    atual = docs[ref]
    com_acoes = ultimos.dropna(subset=["acoes"]).sort_values("data_referencia")
    foto = {"data_referencia": ref, "financeira": atual.financeira, "pl": atual.pl,
            "acoes": com_acoes["acoes"].iloc[-1] if not com_acoes.empty else np.nan,
            "ref_acoes": com_acoes["data_referencia"].iloc[-1] if not com_acoes.empty else None,
            "divida_liq": atual.divida - atual.caixa}
    series = {k: pd.Series(v._asdict()) for k, v in docs.items()}
    anterior = _um_ano_antes(ref)
    for campo in FLUXOS:
        foto[f"{campo}_ttm"] = ttm(series, ref, campo)
        foto[f"{campo}_ttm_ant"] = ttm(series, anterior, campo)
    return foto


def fotografias(docs_empresa: pd.DataFrame) -> pd.DataFrame:
    """Uma fotografia a cada instante em que um novo documento ficou disponível."""
    linhas = []
    for instante in sorted(docs_empresa["disponivel_em"].unique()):
        linhas.append({"instante": instante,
                       **fotografia(docs_empresa[docs_empresa["disponivel_em"] <= instante])})
    return pd.DataFrame(linhas)


# ---------------------------------------------------------------- sinais diários

def _div(a, b, exigir_b_positivo=True):
    b = b.where(b > 0) if exigir_b_positivo else b.where(b != 0)
    return a / b


def sinais_ativo(ticker: str, cotacoes: pd.DataFrame, fotos: pd.DataFrame, proventos: pd.DataFrame) -> pd.DataFrame:
    cot = cotacoes.sort_values("data").copy()
    cot["corte"] = pd.to_datetime(cot["data"].dt.date.map(base.corte), utc=True)
    fotos = fotos.assign(instante=pd.to_datetime(fotos["instante"], utc=True)).sort_values("instante")
    dia = pd.merge_asof(cot, fotos, left_on="corte", right_on="instante", direction="backward")
    dia = dia.dropna(subset=["instante"])
    if dia.empty:
        return pd.DataFrame(columns=["data", *NOMES])

    # ações informadas na data de referência, ajustadas por desdobramentos posteriores
    desd = proventos[proventos["tipo"] == "desdobramento"]
    fator = np.ones(len(dia))
    for ev in desd.itertuples(index=False):
        depois_da_ref = pd.to_datetime(dia["ref_acoes"]) < ev.data_ex
        ate_d = dia["data"] >= ev.data_ex
        fator = np.where(depois_da_ref & ate_d, fator * ev.fator, fator)
    valor_mercado = dia["acoes"] * fator * dia["fechamento"] / ACOES_POR_UNIDADE.get(ticker, 1)
    # Algumas empresas (ex.: Ambev, Vale, Itaú) informam a composição do capital
    # em MILHARES de ações, e o arquivo da CVM não tem coluna de escala. P/VP
    # abaixo de 0,03 não existe na prática (o menor da bolsa fica perto de 0,1),
    # então nesse caso o número de ações é multiplicado por 1.000.
    pvp_bruto = valor_mercado / dia["pl"].where(dia["pl"] > 0)
    escala = pd.Series(np.where(pvp_bruto < 0.03, 1000.0, np.where(pvp_bruto.notna(), 1.0, np.nan)))
    valor_mercado = valor_mercado * escala.ffill().fillna(1.0).to_numpy()

    s = pd.DataFrame({"data": dia["data"]})
    lucro, pl = dia["lucro_ttm"], dia["pl"]
    s["fund_pl"] = _div(valor_mercado, lucro)
    s["fund_lp"] = _div(lucro, valor_mercado)
    s["fund_pvp"] = _div(valor_mercado, pl)
    s["fund_roe"] = _div(lucro, pl)
    s["fund_cresc_lucro"] = _div(lucro, dia["lucro_ttm_ant"]) - 1
    # métricas operacionais só para não financeiras cujo lucro vem da operação
    # (holdings como a Itaúsa lucram com participações: lucro > receita)
    operacional = ~dia["financeira"].astype(bool) & (dia["receita_ttm"] > lucro.abs())
    receita = dia["receita_ttm"].where(operacional)
    ebitda = (dia["ebit_ttm"] + dia["da_ttm"]).where(operacional)
    s["fund_margem_liq"] = _div(lucro, receita)
    s["fund_margem_ebitda"] = _div(ebitda, receita)
    s["fund_divliq_ebitda"] = _div(dia["divida_liq"].where(operacional), ebitda)
    s["fund_cresc_receita"] = _div(receita, dia["receita_ttm_ant"].where(operacional)) - 1
    return s


def carregar_demonstracoes(conn: sqlite3.Connection, ate: str | None = None) -> pd.DataFrame:
    return base._ler(conn, "SELECT codigo_cvm, tipo_doc, data_referencia, versao, demonstrativo, consolidado, "
                           "data_ini, data_fim, cd_conta, ds_conta, valor, disponivel_em FROM demonstracoes "
                           "WHERE demonstrativo IN ('DRE', 'BPA', 'BPP', 'DVA', 'CAPITAL')", ate)


def calcular(conn: sqlite3.Connection, ate: str | None = None) -> pd.DataFrame:
    empresas = dict(conn.execute(
        "SELECT ticker, codigo_cvm FROM ativos WHERE ativo = 1 AND tipo = 'acao' AND codigo_cvm IS NOT NULL"
    ).fetchall())
    demonstracoes = carregar_demonstracoes(conn, ate)
    cotacoes = base.carregar_cotacoes(conn, ate)
    proventos = base.carregar_proventos(conn, ate)
    if demonstracoes.empty:
        return pd.DataFrame(columns=["ticker", "data", "nome", "valor"])
    docs = extrair_documentos(demonstracoes)

    partes = []
    for ticker, codigo in empresas.items():
        docs_empresa = docs[docs["codigo_cvm"] == codigo]
        cot = cotacoes[cotacoes["ticker"] == ticker]
        if docs_empresa.empty or cot.empty:
            continue
        largo = sinais_ativo(ticker, cot, fotografias(docs_empresa), proventos[proventos["ticker"] == ticker])
        longo = largo.melt(id_vars="data", var_name="nome", value_name="valor").dropna(subset=["valor"])
        longo = longo[np.isfinite(longo["valor"])]
        longo["ticker"] = ticker
        partes.append(longo)
    if not partes:
        return pd.DataFrame(columns=["ticker", "data", "nome", "valor"])
    return pd.concat(partes, ignore_index=True)[["ticker", "data", "nome", "valor"]]
