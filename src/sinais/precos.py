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


SALTO_MINIMO = 0.5      # |variação de preço| mínima para suspeitar de evento não registrado
TOLERANCIA_RAZAO = 0.04  # razão a até 4% de um inteiro (ou do inverso de um inteiro)
ALTA_MAXIMA_SEM_EVENTO = 3.0  # preço mais que triplica num dia sem evento: tratado como contábil


def evento_nao_registrado(razao: float) -> bool:
    """Razão de preço P_t / P_{t-1} típica de grupamento ou desdobramento que a
    fonte de proventos não registrou: ~k ou ~1/k com k inteiro entre 2 e 100
    (ex.: grupamento 10:1 multiplica o preço por ~10). Colapsos e disparadas
    reais raramente caem tão perto de um inteiro (Americanas em 12/01/2023: x0,23)."""
    if not np.isfinite(razao) or razao <= 0 or abs(razao - 1) < SALTO_MINIMO:
        return False
    k = razao if razao >= 1 else 1 / razao
    return 2 <= round(k) <= 100 and abs(k / round(k) - 1) <= TOLERANCIA_RAZAO


def retornos_totais(cotacoes: pd.DataFrame, proventos: pd.DataFrame) -> pd.Series:
    """Retornos diários de um único ativo (índice = datas dos pregões).

    Dia com salto de preço típico de grupamento/desdobramento sem registro na
    tabela de proventos (ver `evento_nao_registrado`) recebe retorno 0: o salto
    é contábil, não ganho nem perda do acionista. A detecção só usa P_t e P_{t-1}
    (causal). Limitação: o movimento real de mercado daquele dia se perde."""
    cot = cotacoes.sort_values("data").reset_index(drop=True)
    fator, dividendo = _eventos_por_pregao(cot["data"], proventos)
    preco = cot["fechamento"]
    retorno = (preco * fator + dividendo) / preco.shift(1) - 1
    sem_evento = (fator.to_numpy() == 1.0) & (dividendo.to_numpy() == 0.0)
    razao = (preco / preco.shift(1)).to_numpy()
    suspeito = sem_evento & np.array([evento_nao_registrado(x) for x in razao])
    # conservador para quem compra: alta de mais de 3x num dia sem evento registrado também é
    # tratada como contábil (grupamento com razão distorcida pelo pregão); quedas reais ficam
    suspeito |= sem_evento & (np.nan_to_num(razao, nan=1.0) > ALTA_MAXIMA_SEM_EVENTO)
    retorno[suspeito] = 0.0
    return pd.Series(retorno.to_numpy(), index=pd.DatetimeIndex(cot["data"]), name="retorno")


def indice_retorno_total(cotacoes: pd.DataFrame, proventos: pd.DataFrame) -> pd.Series:
    """Índice começando em 1 no primeiro pregão disponível."""
    r = retornos_totais(cotacoes, proventos).fillna(0.0)
    return (1 + r).cumprod().rename("indice")
