"""Padrões gráficos clássicos (pedido do usuário, 02/10/2026), detectados SÓ com
preços até o dia analisado (sem olhar o futuro).

Detectados nos últimos ~120 pregões, a partir de topos e fundos relevantes
(proeminência mínima de 4% do preço):
- topo duplo / fundo duplo: dois extremos parecidos (até 3%) separados por
  >= 15 pregões, confirmados quando o preço rompe a "linha do pescoço";
- ombro-cabeça-ombro (OCO) / OCO invertido: três extremos, o do meio >= 3%
  além dos ombros, ombros parecidos (até 5%), confirmado no rompimento;
- triângulo ascendente / descendente: topos planos e fundos subindo, ou o
  contrário (inclinação relativa das retas de topos e de fundos).

Padrão gráfico é a parte da análise com menos evidência de funcionar: o efeito
de cada um é MEDIDO no histórico (scripts/calibrar.py) e mostrado ao lado.
"""

import numpy as np
import pandas as pd
from scipy.signal import find_peaks

JANELA = 120
PROEMINENCIA = 0.04
NOMES = {
    "topo_duplo": ("Topo duplo", "baixa"), "fundo_duplo": ("Fundo duplo", "alta"),
    "oco": ("Ombro-cabeça-ombro", "baixa"), "oco_invertido": ("OCO invertido", "alta"),
    "triangulo_ascendente": ("Triângulo ascendente", "alta"), "triangulo_descendente": ("Triângulo descendente", "baixa"),
}


def _extremos(precos: np.ndarray):
    prom = PROEMINENCIA * np.nanmedian(precos)
    topos, _ = find_peaks(precos, prominence=prom, distance=5)
    fundos, _ = find_peaks(-precos, prominence=prom, distance=5)
    return topos, fundos


def _parecidos(a: float, b: float, tolerancia: float) -> bool:
    return abs(a - b) / max(abs(a), abs(b)) <= tolerancia


def detectar(fechamentos: pd.Series | np.ndarray) -> str | None:
    """Padrão confirmado mais recente nos últimos JANELA pregões, ou None."""
    p = np.asarray(fechamentos, dtype=float)[-JANELA:]
    if len(p) < 60 or np.isnan(p).mean() > 0.1:
        return None
    p = pd.Series(p).ffill().bfill().to_numpy()
    ultimo = p[-1]
    topos, fundos = _extremos(p)

    # topo duplo / OCO (bearish): rompimento para baixo da linha do pescoço
    if len(topos) >= 2:
        t1, t2 = topos[-2], topos[-1]
        vale = fundos[(fundos > t1) & (fundos < t2)]
        if (t2 - t1 >= 15 and _parecidos(p[t1], p[t2], 0.03) and len(vale)
                and p[vale].min() < 0.95 * min(p[t1], p[t2]) and ultimo < p[vale].min()):
            if len(topos) >= 3:
                o1, c, o2 = topos[-3], topos[-2], topos[-1]
                if (p[c] >= 1.03 * max(p[o1], p[o2]) and _parecidos(p[o1], p[o2], 0.05)):
                    return "oco"
            return "topo_duplo"
    if len(topos) >= 3:
        o1, c, o2 = topos[-3], topos[-2], topos[-1]
        vales = fundos[(fundos > o1) & (fundos < o2)]
        if (len(vales) and p[c] >= 1.03 * max(p[o1], p[o2]) and _parecidos(p[o1], p[o2], 0.05)
                and ultimo < p[vales].min()):
            return "oco"

    # fundo duplo / OCO invertido (bullish): rompimento para cima
    if len(fundos) >= 2:
        f1, f2 = fundos[-2], fundos[-1]
        pico = topos[(topos > f1) & (topos < f2)]
        if (f2 - f1 >= 15 and _parecidos(p[f1], p[f2], 0.03) and len(pico)
                and p[pico].max() > 1.05 * max(p[f1], p[f2]) and ultimo > p[pico].max()):
            if len(fundos) >= 3:
                o1, c, o2 = fundos[-3], fundos[-2], fundos[-1]
                if p[c] <= 0.97 * min(p[o1], p[o2]) and _parecidos(p[o1], p[o2], 0.05):
                    return "oco_invertido"
            return "fundo_duplo"

    if len(fundos) >= 3:                     # OCO invertido: ombros parecidos, cabeça mais funda
        o1, c, o2 = fundos[-3], fundos[-2], fundos[-1]
        picos = topos[(topos > o1) & (topos < o2)]
        if (len(picos) and p[c] <= 0.97 * min(p[o1], p[o2]) and _parecidos(p[o1], p[o2], 0.05)
                and ultimo > p[picos].max()):
            return "oco_invertido"

    # triângulos: retas pelos últimos topos e fundos (inclinação relativa por pregão)
    if len(topos) >= 3 and len(fundos) >= 3:
        it, ifu = topos[-3:], fundos[-3:]
        inc_t = np.polyfit(it, p[it], 1)[0] / np.mean(p[it])
        inc_f = np.polyfit(ifu, p[ifu], 1)[0] / np.mean(p[ifu])
        plano, sobe = 0.0005, 0.001        # 0,05% e 0,1% ao pregão
        if abs(inc_t) < plano and inc_f > sobe and ultimo > p[it].max():
            return "triangulo_ascendente"
        if abs(inc_f) < plano and inc_t < -sobe and ultimo < p[ifu].min():
            return "triangulo_descendente"
    return None


def descrever(codigo: str | None) -> dict | None:
    if codigo is None:
        return None
    nome, direcao = NOMES[codigo]
    return {"codigo": codigo, "nome": nome, "direcao_classica": direcao}
