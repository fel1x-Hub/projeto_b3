"""Posições da carteira real na XP via Meu Pluggy / Open Finance (regras 11 e 16).

Como configurar (uma vez, pelo usuário):
1. Criar conta em pluggy.ai (o trial de 15 dias é necessário só para CONECTAR;
   a conexão continua depois dele) e conectar a XP em meu.pluggy.ai,
   autorizando pelo app da XP. Nenhuma senha passa por este sistema.
2. No dashboard.pluggy.ai: criar uma Application → Client ID e Client Secret;
   em "Ir para Demo", copiar o Item ID da conexão.
3. No .env: PLUGGY_CLIENT_ID, PLUGGY_CLIENT_SECRET e PLUGGY_ITEM_IDS
   (vários itens separados por vírgula).

API (docs.pluggy.ai, conferida em 01/10/2026): POST /auth {clientId,
clientSecret} -> {apiKey}; GET /investments?itemId=... com header X-API-KEY
-> {results: [{code, type, quantity, amount, amountOriginal, date, ...}]}.
A instituição atualiza os dados ~1 vez por dia; o ganho "ao vivo" é calculado
aqui (quantidade × cotação do momento).
"""

import logging
import os
import re
import sqlite3
from datetime import date, datetime, timezone

from src.coleta.cliente_http import ClienteHTTP
from src.db.tempo import agora_utc_iso, para_iso_utc

logger = logging.getLogger(__name__)

URL = "https://api.pluggy.ai"
TIPOS = ("EQUITY", "ETF")                      # ações, units, FIIs e ETFs negociados na B3
TICKER = re.compile(r"^([A-Z][A-Z0-9]{3}\d{1,2})F?$")


def credenciais() -> tuple[str, str, list[str]] | None:
    cid, segredo = os.getenv("PLUGGY_CLIENT_ID", ""), os.getenv("PLUGGY_CLIENT_SECRET", "")
    itens = [i.strip() for i in os.getenv("PLUGGY_ITEM_IDS", "").split(",") if i.strip()]
    return (cid, segredo, itens) if cid and segredo and itens else None


def _api_key(cliente: ClienteHTTP, cid: str, segredo: str) -> str:
    r = cliente.sessao.post(f"{URL}/auth", json={"clientId": cid, "clientSecret": segredo}, timeout=cliente.timeout)
    if r.status_code in (401, 403):
        raise RuntimeError("Pluggy recusou as credenciais (confira PLUGGY_CLIENT_ID/SECRET no .env)")
    r.raise_for_status()
    return r.json()["apiKey"]


def investimentos(cliente: ClienteHTTP, api_key: str, item_id: str) -> list[dict]:
    saida, pagina = [], 1
    while True:
        dados = cliente.get(f"{URL}/investments", params={"itemId": item_id, "page": pagina, "pageSize": 500},
                            headers={"X-API-KEY": api_key}).json()
        saida += dados.get("results", [])
        if pagina >= dados.get("totalPages", 1):
            return saida
        pagina += 1


def _ts(valor: str | None) -> str | None:
    """'2026-09-30T00:00:00.000Z' -> timestamp UTC padrão (sem fuso = UTC, padrão da API)."""
    if not valor:
        return None
    try:
        dt = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return None
    return para_iso_utc(dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


def posicoes(investimentos_: list[dict]) -> list[tuple]:
    """Investimentos da Pluggy -> linhas de carteira_sincronizada (só papéis de bolsa)."""
    agregado: dict[str, dict] = {}
    for inv in investimentos_:
        m = TICKER.match(str(inv.get("code") or "").strip().upper())
        if inv.get("type") not in TIPOS or not m or not inv.get("quantity"):
            continue
        a = agregado.setdefault(m.group(1), {"quantidade": 0.0, "aplicado": None, "valor": None,
                                             "instituicao": "", "data": None})
        a["quantidade"] += float(inv["quantity"])
        for campo, chave in (("aplicado", "amountOriginal"), ("valor", "amount")):
            if inv.get(chave) is not None:
                a[campo] = (a[campo] or 0.0) + float(inv[chave])
        a["instituicao"] = (inv.get("institution") or {}).get("name") or "Open Finance"
        a["data"] = inv.get("date") or a["data"]
    agora = agora_utc_iso()
    return [(t, a["quantidade"], a["aplicado"], a["valor"], a["instituicao"],
             _ts(a["data"]), agora) for t, a in sorted(agregado.items())]


def coletar(conn: sqlite3.Connection, desde: date | None = None, cliente: ClienteHTTP | None = None) -> int:
    cred = credenciais()
    if cred is None:
        logger.info("Pluggy não configurado (.env sem PLUGGY_*); carteira só com operações manuais/importadas")
        return 0
    cid, segredo, itens = cred
    cliente = cliente or ClienteHTTP(timeout=30)
    chave = _api_key(cliente, cid, segredo)
    todas = [inv for item in itens for inv in investimentos(cliente, chave, item)]
    linhas = posicoes(todas)
    with conn:                                  # a foto substitui a anterior por inteiro
        conn.execute("DELETE FROM carteira_sincronizada")
        conn.executemany("INSERT INTO carteira_sincronizada VALUES (?, ?, ?, ?, ?, ?, ?)", linhas)
    logger.info("Pluggy: %d posições de bolsa sincronizadas (%d investimentos lidos)", len(linhas), len(todas))
    return len(linhas)
