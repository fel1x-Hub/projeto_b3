"""Configuração central do projeto.

Lê o `.env` (se existir) e expõe caminhos, nível de log e a lista de ativos.
Caminhos relativos são resolvidos a partir da raiz do projeto, para que os
scripts funcionem independentemente do diretório de onde são chamados.
"""

import csv
import os
import re
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def _caminho(valor: str) -> Path:
    p = Path(valor)
    return p if p.is_absolute() else BASE_DIR / p


DB_PATH = _caminho(os.getenv("DB_PATH", "data/b3.db"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_DIR = _caminho(os.getenv("LOG_DIR", "logs"))
ATIVOS_CSV = BASE_DIR / "config" / "ativos.csv"

COLUNAS_ATIVOS = ("ticker", "nome", "setor", "cnpj", "ativo")
# Radical de 4 caracteres (começa com letra; pode ter dígito, ex: B3SA3) + 1 ou 2 dígitos
_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9]{3}\d{1,2}$")


def carregar_ativos(caminho: Path | str | None = None) -> list[dict]:
    """Lê e valida a lista de ativos do CSV editável pelo usuário.

    Regras: colunas obrigatórias presentes, ticker no formato B3 (ex: PETR4,
    BPAC11), sem tickers repetidos e `ativo` igual a 0 ou 1 (vazio = 1).
    Linhas totalmente vazias são ignoradas. Erros geram ValueError com a linha.
    """
    caminho = Path(caminho) if caminho else ATIVOS_CSV
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        leitor = csv.DictReader(f)
        faltando = [c for c in COLUNAS_ATIVOS if c not in (leitor.fieldnames or [])]
        if faltando:
            raise ValueError(f"{caminho}: colunas obrigatórias ausentes: {', '.join(faltando)}")

        ativos: list[dict] = []
        vistos: set[str] = set()
        for n_linha, linha in enumerate(leitor, start=2):
            if not any((v or "").strip() for v in linha.values()):
                continue
            ticker = (linha["ticker"] or "").strip().upper()
            if not _TICKER_RE.match(ticker):
                raise ValueError(f"{caminho}:{n_linha}: ticker inválido: {ticker!r}")
            if ticker in vistos:
                raise ValueError(f"{caminho}:{n_linha}: ticker repetido: {ticker}")
            ativo = (linha["ativo"] or "1").strip()
            if ativo not in ("0", "1"):
                raise ValueError(f"{caminho}:{n_linha}: coluna 'ativo' deve ser 0 ou 1, veio {ativo!r}")
            nome = (linha["nome"] or "").strip()
            if not nome:
                raise ValueError(f"{caminho}:{n_linha}: nome vazio para {ticker}")
            vistos.add(ticker)
            ativos.append({
                "ticker": ticker,
                "nome": nome,
                "setor": (linha["setor"] or "").strip() or None,
                "cnpj": (linha["cnpj"] or "").strip() or None,
                "ativo": int(ativo),
            })
    return ativos
