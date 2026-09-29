"""Retorno total a partir do preço BRUTO da B3 e da tabela de proventos.

Na data ex de um evento, o retorno do dia considera o que o acionista de
1 ação na véspera passa a ter:
    r_t = (P_t * S_t + D_t) / P_{t-1} - 1
    S_t = fator de desdobramento/grupamento (ações novas por antiga; 1 se não houver)
    D_t = dividendo/JCP por ação, na escala bruta da época
Nos outros dias, r_t = P_t / P_{t-1} - 1.

Evento com data ex em dia sem pregão do ativo é aplicado no pregão seguinte.
Tudo é causal: o retorno de t só usa preços até t e eventos com data ex <= t.
"""

import numpy as np
import pandas as pd


def _eventos_por_pregao(datas: pd.Series, proventos: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """(fator de desdobramento, dividendo) alinhados aos pregões."""
    fator = pd.Series(1.0, index=datas.index)
    dividendo = pd.Series(0.0, index=datas.index)
    valores = datas.to_numpy()
    for ev in proventos.itertuples(index=False):
        pos = np.searchsorted(valores, np.datetime64(ev.data_ex))  # primeiro pregão >= data ex
        if pos == 0 or pos >= len(valores):
            continue  # antes do histórico (já refletido) ou ainda sem pregão
        rotulo = datas.index[pos]
        if ev.tipo == "desdobramento":
            fator[rotulo] *= ev.fator
        else:
            dividendo[rotulo] += ev.valor
    return fator, dividendo


def retornos_totais(cotacoes: pd.DataFrame, proventos: pd.DataFrame) -> pd.Series:
    """Retornos diários de um único ativo (índice = datas dos pregões)."""
    cot = cotacoes.sort_values("data").reset_index(drop=True)
    fator, dividendo = _eventos_por_pregao(cot["data"], proventos)
    preco = cot["fechamento"]
    retorno = (preco * fator + dividendo) / preco.shift(1) - 1
    return pd.Series(retorno.to_numpy(), index=pd.DatetimeIndex(cot["data"]), name="retorno")


def indice_retorno_total(cotacoes: pd.DataFrame, proventos: pd.DataFrame) -> pd.Series:
    """Índice começando em 1 no primeiro pregão disponível."""
    r = retornos_totais(cotacoes, proventos).fillna(0.0)
    return (1 + r).cumprod().rename("indice")
