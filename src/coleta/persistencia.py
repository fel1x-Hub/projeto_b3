"""Gravação no banco sem sobrescrita silenciosa.

`salvar()` compara cada registro com o que já existe pela chave natural:
- não existe          -> INSERT (conta como novo)
- existe e é igual    -> nada
- existe e é diferente -> UPDATE dos campos alterados + uma linha em `revisoes`
                          por campo (fonte corrigiu o dado)
`coletado_em` não entra na comparação.
"""

import json
import logging
import math
import sqlite3
from dataclasses import dataclass

from src.db.tempo import agora_utc_iso

logger = logging.getLogger(__name__)

IGNORAR_NA_COMPARACAO = {"id", "coletado_em"}


@dataclass
class ResultadoGravacao:
    novos: int = 0
    revisados: int = 0


def _iguais(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        if a is None or b is None:
            return a is b
        return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-12)
    return a == b


def salvar(
    conn: sqlite3.Connection,
    tabela: str,
    chaves: list[str],
    registros: list[dict],
    fonte: str | None = None,
) -> ResultadoGravacao:
    """Grava `registros` em `tabela` usando `chaves` como identidade natural.

    `tabela` e `chaves` vêm do código (nunca do usuário), por isso podem ir
    direto no SQL. Tudo roda numa transação: ou grava o lote inteiro ou nada.
    """
    resultado = ResultadoGravacao()
    if not registros:
        return resultado
    agora = agora_utc_iso()
    filtro = " AND ".join(f"{c} IS ?" for c in chaves)

    with conn:
        for reg in registros:
            reg = {**reg, "coletado_em": reg.get("coletado_em") or agora}
            existente = conn.execute(
                f"SELECT * FROM {tabela} WHERE {filtro}", [reg[c] for c in chaves]
            ).fetchone()

            if existente is None:
                colunas = ", ".join(reg)
                marcadores = ", ".join("?" * len(reg))
                conn.execute(f"INSERT INTO {tabela} ({colunas}) VALUES ({marcadores})", list(reg.values()))
                resultado.novos += 1
                continue

            mudancas = {
                c: (existente[c], v) for c, v in reg.items()
                if c not in IGNORAR_NA_COMPARACAO and c not in chaves and not _iguais(existente[c], v)
            }
            if not mudancas:
                continue

            atribuicoes = ", ".join(f"{c} = ?" for c in [*mudancas, "coletado_em"])
            conn.execute(
                f"UPDATE {tabela} SET {atribuicoes} WHERE id = ?",
                [*(novo for _, novo in mudancas.values()), reg["coletado_em"], existente["id"]],
            )
            chave_json = json.dumps({c: reg[c] for c in chaves}, ensure_ascii=False)
            for campo, (antigo, novo) in mudancas.items():
                conn.execute(
                    "INSERT INTO revisoes (tabela, chave_registro, campo, valor_antigo, valor_novo, fonte, detectado_em) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (tabela, chave_json, campo,
                     None if antigo is None else str(antigo),
                     None if novo is None else str(novo),
                     fonte, agora),
                )
            logger.info("Revisão em %s %s: %s", tabela, chave_json, sorted(mudancas))
            resultado.revisados += 1

    return resultado
