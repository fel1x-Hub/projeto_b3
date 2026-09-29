"""Eventos societários que o Yahoo não registra (ex: cisões com entrega de
ações de outra empresa), mantidos à mão em config/eventos_manuais.csv.

Cada linha precisa de uma `referencia` ao documento oficial que justifica o
valor. Distribuições em ativos entram como `dividendo` com o valor equivalente
em reais por ação (o ajuste que a B3 aplicou ao preço no dia ex), o que basta
para o índice de retorno total não mostrar uma perda que o acionista não teve.
`disponivel_em` = data ex às 00:00 BRT (o evento é anunciado antes).
"""

import csv
import sqlite3
from datetime import date, time
from pathlib import Path

from config import settings
from src.coleta.persistencia import salvar
from src.db.tempo import iso_brt

FONTE = "manual"
CAMINHO = settings.BASE_DIR / "config" / "eventos_manuais.csv"
CHAVES = ["ticker", "fonte", "tipo", "data_ex"]


def carregar(caminho: Path | None = None) -> list[dict]:
    registros = []
    with open(caminho or CAMINHO, encoding="utf-8-sig", newline="") as f:
        for n, r in enumerate(csv.DictReader(f), start=2):
            if not (r.get("referencia") or "").strip():
                raise ValueError(f"eventos_manuais.csv:{n}: evento sem referência ao documento oficial")
            data_ex = date.fromisoformat(r["data_ex"].strip())
            registros.append({
                "ticker": r["ticker"].strip().upper(),
                "tipo": r["tipo"].strip(),
                "data_ex": data_ex.isoformat(),
                "valor": float(r["valor"]) if (r.get("valor") or "").strip() else None,
                "fator": float(r["fator"]) if (r.get("fator") or "").strip() else None,
                "fonte": FONTE,
                "disponivel_em": iso_brt(data_ex, time(0, 0)),
            })
    return registros


def coletar(conn: sqlite3.Connection, desde: date, caminho: Path | None = None) -> int:
    acompanhados = {r[0] for r in conn.execute("SELECT ticker FROM ativos")}
    registros = [r for r in carregar(caminho) if r["ticker"] in acompanhados and r["data_ex"] >= desde.isoformat()]
    return salvar(conn, "proventos", CHAVES, registros, fonte=FONTE).novos
