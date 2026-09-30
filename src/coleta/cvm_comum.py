"""Utilidades comuns às fontes do Portal de Dados Abertos da CVM.

Os arquivos são CSV separados por ';' em latin-1, publicados por ano (ZIP) e
atualizados semanalmente (ano corrente e anterior). Licença: ODbL.
"""

import csv
import io
import sqlite3
import zipfile
from pathlib import Path

from config import settings
from src.db.tempo import hoje_brt

BASE_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA"


def normalizar_codigo_cvm(codigo: str | int) -> str:
    """'009512', '9512' e 9512 viram '9512' (a CVM usa os dois formatos)."""
    return str(int(str(codigo).strip()))


def baixar(http, caminho_url: str, ano: int | None = None) -> Path:
    """Baixa um arquivo da CVM para data/raw/cvm/, reaproveitando o cache só
    para anos fechados (a CVM reprocessa o ano corrente e o anterior)."""
    nome = caminho_url.rsplit("/", 1)[-1]
    reusar = ano is not None and ano < hoje_brt().year - 1
    return http.baixar_arquivo(f"{BASE_URL}/{caminho_url}", settings.RAW_DIR / "cvm" / nome, reusar=reusar)


def ler_csv(caminho: Path, nome_interno: str | None = None) -> list[dict]:
    """Lê um CSV da CVM (solto ou dentro de um ZIP)."""
    if nome_interno is not None:
        with zipfile.ZipFile(caminho) as z:
            if nome_interno not in z.namelist():
                return []
            bruto = z.read(nome_interno)
    else:
        bruto = Path(caminho).read_bytes()
    return list(csv.DictReader(io.StringIO(bruto.decode("latin-1")), delimiter=";"))


def empresas_acompanhadas(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """{codigo_cvm: [tickers]} das ações ativas com código CVM conhecido.
    O primeiro ticker (exceção manual, senão ordem alfabética) é o representativo
    gravado em `documentos.ticker`; os sinais estendem o documento a todos os
    tickers da empresa."""
    empresas: dict[str, list[str]] = {}
    for r in conn.execute(
        "SELECT codigo_cvm, ticker FROM ativos "
        "WHERE ativo = 1 AND tipo = 'acao' AND codigo_cvm IS NOT NULL "
        "ORDER BY origem = 'manual' DESC, ticker"  # 1º da lista = ticker representativo (estável)
    ):
        empresas.setdefault(r["codigo_cvm"], []).append(r["ticker"])
    return empresas
