"""Métricas de classificação (acurácia, precisão, revocação, F1, matriz de
confusão) para avaliar o sentimento contra rótulos de referência."""

CLASSES = ("positivo", "neutro", "negativo")


def matriz_confusao(reais: list[str], previstos: list[str]) -> dict[str, dict[str, int]]:
    """matriz[real][previsto] = contagem."""
    m = {r: {p: 0 for p in CLASSES} for r in CLASSES}
    for r, p in zip(reais, previstos):
        m[r][p] += 1
    return m


def metricas(reais: list[str], previstos: list[str]) -> dict:
    m = matriz_confusao(reais, previstos)
    por_classe = {}
    for c in CLASSES:
        vp = m[c][c]
        previstos_c = sum(m[r][c] for r in CLASSES)
        reais_c = sum(m[c].values())
        precisao = vp / previstos_c if previstos_c else 0.0
        revocacao = vp / reais_c if reais_c else 0.0
        f1 = 2 * precisao * revocacao / (precisao + revocacao) if precisao + revocacao else 0.0
        por_classe[c] = {"precisao": precisao, "revocacao": revocacao, "f1": f1, "suporte": reais_c}
    total = len(reais)
    return {
        "n": total,
        "acuracia": sum(m[c][c] for c in CLASSES) / total if total else 0.0,
        "f1_macro": sum(v["f1"] for v in por_classe.values()) / len(CLASSES),
        "por_classe": por_classe,
        "matriz": m,
    }
