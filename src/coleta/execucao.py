"""Execução isolada de cada fonte, com registro em `execucoes_coleta`.

Uma fonte que falha é registrada como 'falha' e NÃO interrompe as demais.
Um módulo pode sinalizar sucesso parcial (ex: 2 de 21 tickers falharam)
levantando `ColetaParcial` no fim, com o total de registros novos.
"""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import Callable

from src.db.tempo import agora_utc_iso

logger = logging.getLogger(__name__)


class ColetaParcial(Exception):
    def __init__(self, novos: int, mensagem: str):
        super().__init__(mensagem)
        self.novos = novos


@dataclass
class ResultadoExecucao:
    fonte: str
    status: str
    novos: int
    erro: str | None = None


def executar(
    conn: sqlite3.Connection,
    fonte: str,
    funcao: Callable[[sqlite3.Connection, date], int],
    desde: date,
) -> ResultadoExecucao:
    with conn:
        execucao_id = conn.execute(
            "INSERT INTO execucoes_coleta (fonte, inicio, status) VALUES (?, ?, 'em_andamento')",
            (fonte, agora_utc_iso()),
        ).lastrowid

    logger.info("Coletando %s desde %s", fonte, desde)
    try:
        novos = funcao(conn, desde)
        resultado = ResultadoExecucao(fonte, "sucesso", novos)
    except ColetaParcial as e:
        resultado = ResultadoExecucao(fonte, "parcial", e.novos, str(e))
        logger.warning("%s: coleta parcial: %s", fonte, e)
    except Exception as e:  # noqa: BLE001 - erro de uma fonte não derruba as outras
        if conn.in_transaction:
            conn.rollback()
        resultado = ResultadoExecucao(fonte, "falha", 0, f"{type(e).__name__}: {e}")
        logger.exception("%s: falha na coleta", fonte)

    with conn:
        conn.execute(
            "UPDATE execucoes_coleta SET fim = ?, status = ?, registros_novos = ?, erro = ? WHERE id = ?",
            (agora_utc_iso(), resultado.status, resultado.novos, resultado.erro, execucao_id),
        )
    logger.info("%s: %s, %d registros novos", fonte, resultado.status, resultado.novos)
    return resultado
