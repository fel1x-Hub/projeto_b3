"""Sincronização da tabela `ativos` com a lista em config/ativos.csv."""

import logging
import sqlite3

from src.db.tempo import agora_utc_iso

logger = logging.getLogger(__name__)


def sincronizar_ativos(conn: sqlite3.Connection, ativos: list[dict]) -> dict[str, int]:
    """Faz upsert dos ativos da lista e desativa os que saíram dela.

    - Ticker novo: inserido.
    - Ticker existente com dados diferentes: atualizado. Um CNPJ vazio no CSV
      não apaga o que já estiver no banco (a etapa 2 preenche via CVM).
    - Ticker no banco que não está na lista: vira ativo = 0 (nunca é apagado).

    Devolve contagens {inseridos, atualizados, desativados}; rodar de novo com a
    mesma lista devolve tudo zero.
    """
    agora = agora_utc_iso()
    contagem = {"inseridos": 0, "atualizados": 0, "desativados": 0}
    tickers = [a["ticker"] for a in ativos]

    with conn:
        for a in ativos:
            existe = conn.execute("SELECT 1 FROM ativos WHERE ticker = ?", (a["ticker"],)).fetchone()
            dados = {"apelidos": None, "tipo": "acao", **a, "agora": agora}
            cur = conn.execute(
                """
                INSERT INTO ativos (ticker, nome, setor, cnpj, ativo, apelidos, tipo, criado_em, atualizado_em)
                VALUES (:ticker, :nome, :setor, :cnpj, :ativo, :apelidos, :tipo, :agora, :agora)
                ON CONFLICT (ticker) DO UPDATE SET
                    nome = excluded.nome,
                    setor = excluded.setor,
                    cnpj = COALESCE(excluded.cnpj, ativos.cnpj),
                    ativo = excluded.ativo,
                    apelidos = excluded.apelidos,
                    tipo = excluded.tipo,
                    atualizado_em = excluded.atualizado_em
                WHERE ativos.nome IS NOT excluded.nome
                   OR ativos.setor IS NOT excluded.setor
                   OR ativos.cnpj IS NOT COALESCE(excluded.cnpj, ativos.cnpj)
                   OR ativos.ativo IS NOT excluded.ativo
                   OR ativos.apelidos IS NOT excluded.apelidos
                   OR ativos.tipo IS NOT excluded.tipo
                """,
                dados,
            )
            if cur.rowcount:
                contagem["atualizados" if existe else "inseridos"] += 1

        marcadores = ",".join("?" * len(tickers))
        cur = conn.execute(
            f"UPDATE ativos SET ativo = 0, atualizado_em = ? "
            f"WHERE ativo = 1 AND ticker NOT IN ({marcadores})",
            [agora, *tickers],
        )
        contagem["desativados"] = cur.rowcount

    logger.info(
        "Ativos sincronizados: %(inseridos)d inseridos, %(atualizados)d atualizados, "
        "%(desativados)d desativados",
        contagem,
    )
    return contagem
