"""Posições da carteira recalculadas das operações (etapa 7, regra 11).

A posição nunca é gravada: sai sempre de `carteira_operacoes`, processadas em
ordem de data junto com os eventos do papel:
- desdobramento/grupamento (`proventos.fator` = ações novas por ação antiga):
  multiplica a quantidade e divide o preço médio, sem mudar o custo;
- dividendo/JCP (valor por ação na escala da data ex): soma
  quantidade × valor aos proventos recebidos.
Eventos da data ex valem para quem tinha o papel ANTES dela, então no mesmo
dia o evento é aplicado antes das operações.

Preço médio pela regra da Receita: compras somam custo (com corretagem e
emolumentos); vendas baixam custo pelo preço médio e não o alteram.
"""

from dataclasses import dataclass, field
from datetime import date

import pandas as pd


@dataclass
class Posicao:
    ticker: str
    quantidade: float = 0.0
    custo: float = 0.0               # custo da quantidade atual (preço médio × quantidade)
    lucro_realizado: float = 0.0     # vendas: valor líquido − custo médio do que foi vendido
    proventos: float = 0.0           # dividendos/JCP recebidos (bruto)
    primeira_compra: date | None = None
    avisos: list[str] = field(default_factory=list)

    @property
    def preco_medio(self) -> float | None:
        return self.custo / self.quantidade if self.quantidade > 0 else None


def calcular(operacoes: pd.DataFrame, proventos: pd.DataFrame | None = None) -> dict[str, Posicao]:
    """Posições por ticker.

    operacoes: ticker, tipo ('compra'/'venda'), data, quantidade, preco, custos.
    proventos: ticker, tipo ('dividendo'/'desdobramento'), data_ex, valor, fator.
    Inclui papéis já zerados (quantidade 0), que guardam lucro e proventos.
    """
    posicoes: dict[str, Posicao] = {}
    if operacoes.empty:
        return posicoes
    ops = operacoes.assign(data=pd.to_datetime(operacoes["data"]).dt.date)
    eventos = pd.DataFrame(columns=["ticker", "tipo", "data_ex", "valor", "fator"])
    if proventos is not None and not proventos.empty:
        eventos = proventos.assign(data_ex=pd.to_datetime(proventos["data_ex"]).dt.date)

    for ticker, grupo in ops.groupby("ticker", sort=True):
        p = Posicao(ticker)
        inicio = grupo["data"].min()
        evs = eventos[(eventos["ticker"] == ticker) & (eventos["data_ex"] > inicio)]
        # (data, ordem, linha): ordem 0 = evento, 1 = operação (evento da data ex vem antes)
        fila = [(e.data_ex, 0, e) for e in evs.itertuples(index=False)]
        fila += [(o.data, 1, o) for o in grupo.itertuples(index=False)]
        fila.sort(key=lambda x: (x[0], x[1]))
        for dia, ordem, linha in fila:
            if ordem == 0:
                if linha.tipo == "desdobramento" and pd.notna(linha.fator):
                    p.quantidade *= float(linha.fator)
                elif linha.tipo == "dividendo" and pd.notna(linha.valor):
                    p.proventos += p.quantidade * float(linha.valor)
                continue
            q, preco, custos = float(linha.quantidade), float(linha.preco), float(linha.custos or 0)
            if linha.tipo == "compra":
                p.quantidade += q
                p.custo += q * preco + custos
                p.primeira_compra = p.primeira_compra or dia
            else:
                if q > p.quantidade + 1e-9:
                    p.avisos.append(f"venda de {q:g} em {dia} maior que a posição ({p.quantidade:g}); "
                                    "faltam operações anteriores?")
                    q = p.quantidade
                if q <= 0:
                    continue
                custo_vendido = p.custo * q / p.quantidade
                p.lucro_realizado += q * preco - custos - custo_vendido
                p.custo -= custo_vendido
                p.quantidade -= q
                if p.quantidade < 1e-9:
                    p.quantidade, p.custo = 0.0, 0.0
        posicoes[ticker] = p
    return posicoes


def quantidade_em(operacoes: pd.DataFrame, proventos: pd.DataFrame | None, dias: pd.DatetimeIndex) -> pd.DataFrame:
    """Quantidade de cada papel no fechamento de cada dia (para a evolução do patrimônio)."""
    tickers = sorted(operacoes["ticker"].unique()) if not operacoes.empty else []
    saida = pd.DataFrame(0.0, index=dias, columns=tickers)
    for d in dias:
        ate = operacoes[pd.to_datetime(operacoes["data"]) <= d]
        provs = None
        if proventos is not None and not proventos.empty:
            provs = proventos[pd.to_datetime(proventos["data_ex"]) <= d]
        for t, p in calcular(ate, provs).items():
            saida.loc[d, t] = p.quantidade
    return saida
