"""Checagem automática do relatório: todo número citado no texto precisa
existir nos insumos (regra 2: o LLM não calcula nada).

Números são extraídos com o formato brasileiro (vírgula decimal, "%", "+").
Dígitos colados a letras (tickers como PETR4, "3T25") não contam como número.
Datas dos insumos (AAAA-MM-DD) também valem nos formatos DD/MM/AAAA e DD/MM.
"""

import json
import re

_NUMERO = re.compile(r"(?<![A-Za-zÀ-ÿ\d])[+\-−]?(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?(?:\s?%)?(?![A-Za-zÀ-ÿ\d])")
_DATA_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
PEQUENOS = {str(i) for i in range(0, 32)}  # contagens e posições (só inteiros SEM %)


def normalizar(token: str) -> str:
    """'+1,03 %' -> '1,03%' · '185.713' -> '185713' · '−0,5' -> '-0,5'."""
    t = token.replace("−", "-").replace(" ", "").lstrip("+")
    if t.startswith("-"):
        t = "-" + t[1:]
    return t.replace(".", "") if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?%?", t) else t


def numeros(texto: str) -> set[str]:
    return {normalizar(m.group()) for m in _NUMERO.finditer(texto)}


def permitidos(insumos: dict) -> set[str]:
    bruto = json.dumps(insumos, ensure_ascii=False)
    datas = {f"{d}/{m}/{a}" for a, m, d in _DATA_ISO.findall(bruto)} | {f"{d}/{m}" for a, m, d in _DATA_ISO.findall(bruto)}
    base = numeros(bruto.replace("-", " - ")) | numeros(" ".join(datas).replace("/", " "))
    com_sinal = {n.lstrip("-") for n in base} | {f"-{n.lstrip('-')}" for n in base}
    return base | com_sinal | PEQUENOS


def numeros_sem_origem(texto: str, insumos: dict) -> list[str]:
    """Números do texto que não aparecem nos insumos (vazio = relatório aprovado)."""
    texto_sem_datas = re.sub(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b", " ", texto)
    datas_texto = re.findall(r"\b\d{1,2}/\d{1,2}(?:/\d{4})?\b", texto)
    ok = permitidos(insumos)
    bruto = json.dumps(insumos, ensure_ascii=False)
    datas_ok = {f"{d}/{m}/{a}" for a, m, d in _DATA_ISO.findall(bruto)} | {f"{d}/{m}" for a, m, d in _DATA_ISO.findall(bruto)}
    problemas = sorted({n for n in numeros(texto_sem_datas) if n not in ok and n.lstrip("-") not in ok})
    return problemas + sorted({d for d in datas_texto if d not in datas_ok})
