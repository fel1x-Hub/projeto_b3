"""Importação de extratos de negociação (etapa 7.3).

Formatos aceitos (CSV, `;` ou `,`, ou XLSX), reconhecidos pelos cabeçalhos:
- Área do Investidor da B3 → Extratos → Negociação: "Data do Negócio",
  "Tipo de Movimentação", "Código de Negociação", "Quantidade", "Preço". Cobre
  a XP e qualquer corretora; o mercado fracionário (PETR4F) vira PETR4.
- Planilha simples: ticker/ativo, tipo/operação (compra/venda/C/V), data,
  quantidade, preço e, opcionalmente, custos/corretagem/taxas.

O parser é tolerante: linhas que não entende vão para `nao_reconhecidas`, com
o motivo, e o resto é importado. A chave `referencia` é o conteúdo da linha
(+ ordem entre linhas idênticas), então reimportar um extrato, ou outro com
período sobreposto, não duplica operações.
"""

import hashlib
import io
import logging
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd

from src.db.tempo import agora_utc_iso

logger = logging.getLogger(__name__)

APELIDOS = {
    "ticker": ["codigo de negociacao", "ticker", "ativo", "codigo", "papel", "produto"],
    "tipo": ["tipo de movimentacao", "tipo", "operacao", "c/v", "compra/venda", "natureza"],
    "data": ["data do negocio", "data", "data da operacao", "data pregao"],
    "quantidade": ["quantidade", "qtd", "qtde", "quant"],
    "preco": ["preco", "preco unitario", "preco medio", "valor unitario"],
    "custos": ["custos", "corretagem", "taxas", "custo", "despesas"],
}
OBRIGATORIAS = ("ticker", "tipo", "data", "quantidade", "preco")
TICKER = re.compile(r"^([A-Z][A-Z0-9]{3}\d{1,2})F?$")


@dataclass
class ResultadoImportacao:
    importadas: int = 0
    ja_existiam: int = 0
    nao_reconhecidas: list[tuple[int, str]] = field(default_factory=list)  # (linha do arquivo, motivo)
    formato: str = ""


def _norm(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sem_acento.strip().lower())


def numero(valor) -> float | None:
    """'1.234,56', 'R$ 30,50', '30.5' ou número → float."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    s = re.sub(r"[^\d,.\-]", "", str(valor))
    if not s or s in "-.,":
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _data(valor) -> date | None:
    if isinstance(valor, (datetime, pd.Timestamp)):
        return valor.date()
    if isinstance(valor, date):
        return valor
    s = str(valor).strip()[:10]
    for formato in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, formato).date()
        except ValueError:
            continue
    return None


def _tipo(valor) -> str | None:
    s = _norm(valor)
    if s in ("c", "compra", "credito", "buy") or s.startswith("compra"):
        return "compra"
    if s in ("v", "venda", "debito", "sell") or s.startswith("venda"):
        return "venda"
    return None


def ler_tabela(conteudo: bytes, nome_arquivo: str = "") -> pd.DataFrame:
    if nome_arquivo.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(conteudo), dtype=object)
    for codificacao in ("utf-8-sig", "latin-1"):
        try:
            texto = conteudo.decode(codificacao)
            break
        except UnicodeDecodeError:
            continue
    separador = ";" if texto.count(";") >= texto.count(",") else ","
    return pd.read_csv(io.StringIO(texto), sep=separador, dtype=str, keep_default_na=False)


def mapear_colunas(colunas) -> dict[str, str]:
    """Campo interno -> coluna do arquivo, pelo primeiro apelido que bater."""
    normalizadas = {_norm(c): c for c in colunas}
    mapa = {}
    for campo, apelidos in APELIDOS.items():
        for apelido in apelidos:
            if apelido in normalizadas:
                mapa[campo] = normalizadas[apelido]
                break
    return mapa


def interpretar(tabela: pd.DataFrame) -> tuple[list[dict], list[tuple[int, str]], str]:
    mapa = mapear_colunas(tabela.columns)
    faltando = [c for c in OBRIGATORIAS if c not in mapa]
    if faltando:
        raise ValueError(f"colunas não encontradas: {', '.join(faltando)} (cabeçalhos: {', '.join(map(str, tabela.columns))})")
    formato = "b3_negociacao" if mapa["ticker"] == next(
        (c for c in tabela.columns if _norm(c) == "codigo de negociacao"), None) else "planilha"
    validas, ruins, vistas = [], [], {}
    for i, linha in enumerate(tabela.to_dict("records"), start=2):  # linha 1 = cabeçalho
        if all(str(v).strip() in ("", "nan", "None") for v in linha.values()):
            continue
        bruto = str(linha[mapa["ticker"]]).split(" - ")[0].strip().upper()   # "PETR4 - PETROBRAS" -> PETR4
        m = TICKER.match(bruto)
        tipo, dia = _tipo(linha[mapa["tipo"]]), _data(linha[mapa["data"]])
        qtd, preco = numero(linha[mapa["quantidade"]]), numero(linha[mapa["preco"]])
        custos = numero(linha[mapa["custos"]]) if "custos" in mapa else 0.0
        motivo = (None if m else f"ticker não reconhecido: {bruto!r}") or \
                 (None if tipo else f"tipo não é compra nem venda: {linha[mapa['tipo']]!r}") or \
                 (None if dia else f"data inválida: {linha[mapa['data']]!r}") or \
                 (None if qtd and qtd > 0 else f"quantidade inválida: {linha[mapa['quantidade']]!r}") or \
                 (None if preco and preco > 0 else f"preço inválido: {linha[mapa['preco']]!r}")
        if motivo:
            ruins.append((i, motivo))
            continue
        op = {"ticker": m.group(1), "tipo": tipo, "data": dia.isoformat(), "quantidade": qtd,
              "preco": preco, "custos": abs(custos or 0.0)}
        chave = f"{op['ticker']}|{tipo}|{op['data']}|{qtd:g}|{preco:g}"
        vistas[chave] = vistas.get(chave, 0) + 1          # fills idênticos no mesmo dia são legítimos
        op["referencia"] = "imp:" + hashlib.sha256(f"{chave}|{vistas[chave]}".encode()).hexdigest()[:24]
        validas.append(op)
    return validas, ruins, formato


def importar(conn: sqlite3.Connection, conteudo: bytes, nome_arquivo: str = "") -> ResultadoImportacao:
    validas, ruins, formato = interpretar(ler_tabela(conteudo, nome_arquivo))
    agora = agora_utc_iso()
    r = ResultadoImportacao(nao_reconhecidas=ruins, formato=formato)
    with conn:
        for op in validas:
            cur = conn.execute(
                "INSERT OR IGNORE INTO carteira_operacoes (ticker, tipo, data, quantidade, preco, custos, origem, "
                "referencia, criado_em) VALUES (?, ?, ?, ?, ?, ?, 'importacao', ?, ?)",
                (op["ticker"], op["tipo"], op["data"], op["quantidade"], op["preco"], op["custos"],
                 op["referencia"], agora))
            if cur.rowcount:
                r.importadas += 1
            else:
                r.ja_existiam += 1
    logger.info("Importação (%s): %d novas, %d já existiam, %d não reconhecidas",
                formato, r.importadas, r.ja_existiam, len(ruins))
    return r
