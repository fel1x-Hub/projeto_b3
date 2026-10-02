"""Nomes legíveis dos sinais, para relatório e explicações no app (regra 16).

`explicar(sinal, percentil)` traduz um fator do ranking em frase curta, por
exemplo: ("fund_lp", 0.92) -> "lucro/preço alto (percentil 92 do universo)".
"""

NOMES = {
    "ret_1d": "retorno de 1 dia", "ret_5d": "retorno de 5 dias", "ret_21d": "retorno de 1 mês",
    "ret_63d": "retorno de 3 meses", "dist_mm21": "distância da média de 21 dias",
    "dist_mm50": "distância da média de 50 dias", "dist_mm200": "distância da média de 200 dias",
    "rsi14": "RSI de 14 dias", "vol_21d": "volatilidade de 1 mês", "vol_63d": "volatilidade de 3 meses",
    "vol_fin_rel21": "volume negociado vs. média",
    "fund_pl": "P/L", "fund_lp": "lucro/preço", "fund_pvp": "P/VP", "fund_roe": "ROE",
    "fund_margem_liq": "margem líquida", "fund_margem_ebitda": "margem EBITDA",
    "fund_divliq_ebitda": "dívida líquida/EBITDA", "fund_cresc_receita": "crescimento da receita",
    "fund_cresc_lucro": "crescimento do lucro",
    "evt_saldo": "saldo de fatos relevantes recentes", "evt_n_21d": "fatos relevantes no mês",
    "sent_media_dia": "sentimento das notícias do dia", "sent_media_21d": "sentimento das notícias no mês",
}


# Sinais de nome feminino, para a concordância ("volatilidade baixa").
FEMININOS = {"vol_21d", "vol_63d", "dist_mm21", "dist_mm50", "dist_mm200",
             "fund_margem_liq", "fund_margem_ebitda", "fund_divliq_ebitda"}


def nome(sinal: str) -> str:
    return NOMES.get(sinal, sinal)


def nivel(percentil: float | None, feminino: bool = False) -> str:
    if percentil is None:
        return "sem dado"
    if percentil >= 0.8:
        texto = "muito alto"
    elif percentil >= 0.6:
        texto = "alto"
    elif percentil > 0.4:
        texto = "mediano"
    elif percentil > 0.2:
        texto = "baixo"
    else:
        texto = "muito baixo"
    return texto[:-1] + "a" if feminino else texto


def explicar(sinal: str, percentil: float | None, contribuicao: float) -> str:
    efeito = "favorece" if contribuicao > 0 else "pesa contra"
    pct = f" (percentil {round(percentil * 100)} do universo)" if percentil is not None else ""
    return f"{nome(sinal)} {nivel(percentil, sinal in FEMININOS)}{pct}: {efeito}"
