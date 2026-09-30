"""Backtest de carteira a partir de scores diários (ranking fora da amostra).

Regra principal (decidida pelo usuário ANTES de ver resultados, 30/09/2026):
top 30 do ranking, pesos iguais, rebalanceamento a cada 10 pregões, universo
todo (>= R$ 100 mil/dia), só comprada.

Premissas (conservadoras):
- O ranking da data D usa o fechamento de D (sai às 19h). A carteira é
  montada no FECHAMENTO do pregão seguinte (D+1) e passa a render de D+2.
- Entre rebalanceamentos os pesos flutuam com os preços (compra e segura).
- Retornos totais: incluem dividendos, JCP e desdobramentos (etapa 3).
- Custo de cada operação = emolumentos da B3 + meio spread da faixa de
  liquidez do papel, cobrado sobre o valor negociado (giro).
- Papel que para de negociar fica com preço parado até o próximo
  rebalanceamento e é vendido pelo último preço (otimista em falências).
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

DIAS_ANO = 252


@dataclass(frozen=True)
class Regra:
    n_acoes: int = 30
    intervalo: int = 10              # pregões entre rebalanceamentos
    liquidez_minima: float = 0.0     # além do universo (R$/dia); 0 = universo todo
    folga: int | None = None         # vende só se sair do top `folga` (None = sai do top N)


@dataclass(frozen=True)
class Custos:
    emolumentos: float = 0.0003      # B3, por operação (compra ou venda)
    # meio spread + impacto por faixa de volume médio (R$/dia): (limite inferior, custo)
    faixas: tuple = ((5e6, 0.0005), (1e6, 0.0015), (0.0, 0.0050))
    multiplicador: float = 1.0

    def por_papel(self, volume_medio: pd.Series) -> pd.Series:
        custo = pd.Series(self.faixas[-1][1], index=volume_medio.index)
        for limite, valor in reversed(self.faixas):
            custo[volume_medio >= limite] = valor
        return (custo + self.emolumentos) * self.multiplicador


@dataclass
class Resultado:
    valor: pd.Series                 # patrimônio diário (começa em 1)
    retorno: pd.Series               # retorno diário líquido
    giro: pd.Series                  # giro por rebalanceamento (soma |Δpeso| / 2)
    custos: pd.Series                # custo cobrado em cada rebalanceamento
    carteiras: dict = field(default_factory=dict)  # data de montagem -> tickers


def escolher(scores_dia: pd.DataFrame, atuais: list[str], regra: Regra) -> list[str]:
    """Top N por score; com folga, mantém quem ainda está no top `folga`."""
    ordem = scores_dia.sort_values("score", ascending=False)["ticker"].tolist()
    if regra.folga is None:
        return ordem[:regra.n_acoes]
    mantidos = [t for t in atuais if t in ordem[:regra.folga]]
    novos = [t for t in ordem if t not in mantidos][: max(0, regra.n_acoes - len(mantidos))]
    return (mantidos + novos)[:regra.n_acoes]


def simular(scores: pd.DataFrame, retornos: pd.DataFrame, universo: pd.DataFrame,
            regra: Regra = Regra(), custos: Custos = Custos()) -> Resultado:
    """scores: data, ticker, score · retornos: índice = pregões, colunas = tickers
    (retorno total diário; NaN = sem negócio) · universo: data, ticker, volume_medio."""
    calendario = retornos.index
    datas_score = sorted(set(scores["data"]) & set(calendario))
    if not datas_score:
        raise ValueError("scores insuficientes para o backtest")
    pos = {d: i for i, d in enumerate(calendario)}
    rebal = datas_score[:: regra.intervalo]
    universo = universo.set_index(["data", "ticker"])["volume_medio"]
    scores_por_dia = {d: g for d, g in scores.groupby("data")}
    r = retornos.fillna(0.0)

    pesos = pd.Series(dtype=float)
    carteiras, giros, custos_reb = {}, {}, {}
    serie_ret = pd.Series(0.0, index=calendario)
    inicio = pos[rebal[0]] + 1  # primeira montagem no fechamento de D+1
    montagens = {pos[d] + 1: d for d in rebal if pos[d] + 1 < len(calendario)}

    for i in range(inicio, len(calendario)):
        dia = calendario[i]
        ret_dia, custo = 0.0, 0.0
        # 1) rende o dia com os pesos da véspera (no dia da 1ª montagem ainda não há posição)
        if i > inicio and not pesos.empty:
            ret_papeis = r.loc[dia, pesos.index]
            ret_dia = float((pesos * ret_papeis).sum())
            pesos = pesos * (1 + ret_papeis) / (1 + ret_dia)  # deriva dos pesos
        # 2) rebalanceia no fechamento, se for dia de montagem
        if i in montagens:
            d_score = montagens[i]
            elegiveis = scores_por_dia[d_score]
            vol = universo.reindex(pd.MultiIndex.from_arrays([[d_score] * len(elegiveis), elegiveis["ticker"]]))
            elegiveis = elegiveis.assign(volume_medio=vol.to_numpy())
            elegiveis = elegiveis[elegiveis["volume_medio"].fillna(0) >= regra.liquidez_minima]
            tickers = escolher(elegiveis, list(pesos.index), regra)
            novos = pd.Series(1.0 / len(tickers), index=tickers) if tickers else pd.Series(dtype=float)
            todos = novos.index.union(pesos.index)
            delta = (novos.reindex(todos, fill_value=0) - pesos.reindex(todos, fill_value=0)).abs()
            vol_todos = universo.reindex(pd.MultiIndex.from_arrays([[d_score] * len(todos), todos])).fillna(0)
            custo = float((delta * custos.por_papel(pd.Series(vol_todos.to_numpy(), index=todos))).sum())
            giros[dia], custos_reb[dia] = float(delta.sum() / 2), custo
            carteiras[dia] = tickers
            pesos = novos
        serie_ret[dia] = (1 + ret_dia) * (1 - custo) - 1

    ret = serie_ret.iloc[inicio:]
    return Resultado(valor=(1 + ret).cumprod(), retorno=ret, giro=pd.Series(giros),
                     custos=pd.Series(custos_reb), carteiras=carteiras)


def metricas(ret: pd.Series, cdi_diario: pd.Series | None = None, giro: pd.Series | None = None) -> dict:
    """Retorno acumulado/anualizado, volatilidade, Sharpe (sobre o CDI), drawdown máximo e giro anual."""
    valor = (1 + ret).cumprod()
    anos = len(ret) / DIAS_ANO
    excesso = ret - (cdi_diario.reindex(ret.index).fillna(0.0) if cdi_diario is not None else 0.0)
    vol = ret.std() * np.sqrt(DIAS_ANO)
    return {
        "retorno_total": valor.iloc[-1] - 1,
        "retorno_anual": valor.iloc[-1] ** (1 / anos) - 1 if anos > 0 else np.nan,
        "volatilidade": vol,
        "sharpe": excesso.mean() / ret.std() * np.sqrt(DIAS_ANO) if ret.std() > 0 else np.nan,
        "drawdown_max": (valor / valor.cummax() - 1).min(),
        "giro_anual": float(giro.sum() / anos) if giro is not None and anos > 0 else np.nan,
    }


def drawdown(valor: pd.Series) -> pd.Series:
    return valor / valor.cummax() - 1
