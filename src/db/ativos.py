"""Sincronização da tabela `ativos` com config/ativos.csv (lista de EXCEÇÕES).

O universo é detectado automaticamente nos arquivos da B3 (origem 'auto').
O CSV só registra exceções (origem 'manual'):
- linha com ativo = 1: papel incluído à força (entra no universo mesmo sem liquidez);
- linha com ativo = 0: papel excluído;
- papel que sai do CSV deixa de ser exceção e volta ao critério automático
  (origem 'auto'); nunca é apagado nem desativado por isso.
"""

import logging
import sqlite3

from src.db.tempo import agora_utc_iso

logger = logging.getLogger(__name__)


def sincronizar_ativos(conn: sqlite3.Connection, ativos: list[dict]) -> dict[str, int]:
    """Faz upsert das exceções do CSV e devolve ao automático as que saíram dele.

    Um CNPJ vazio no CSV não apaga o que já estiver no banco (a coleta CVM
    preenche). Devolve {inseridos, atualizados, liberados}; rodar de novo com a
    mesma lista devolve tudo zero.
    """
    agora = agora_utc_iso()
    contagem = {"inseridos": 0, "atualizados": 0, "liberados": 0}
    tickers = [a["ticker"] for a in ativos]

    with conn:
        for a in ativos:
            existe = conn.execute("SELECT 1 FROM ativos WHERE ticker = ?", (a["ticker"],)).fetchone()
            dados = {"apelidos": None, "tipo": "acao", **a, "agora": agora}
            cur = conn.execute(
                """
                INSERT INTO ativos (ticker, nome, setor, cnpj, ativo, apelidos, tipo, origem, criado_em, atualizado_em)
                VALUES (:ticker, :nome, :setor, :cnpj, :ativo, :apelidos, :tipo, 'manual', :agora, :agora)
                ON CONFLICT (ticker) DO UPDATE SET
                    nome = excluded.nome,
                    setor = excluded.setor,
                    cnpj = COALESCE(excluded.cnpj, ativos.cnpj),
                    ativo = excluded.ativo,
                    apelidos = excluded.apelidos,
                    tipo = excluded.tipo,
                    origem = 'manual',
                    atualizado_em = excluded.atualizado_em
                WHERE ativos.nome IS NOT excluded.nome
                   OR ativos.setor IS NOT excluded.setor
                   OR ativos.cnpj IS NOT COALESCE(excluded.cnpj, ativos.cnpj)
                   OR ativos.ativo IS NOT excluded.ativo
                   OR ativos.apelidos IS NOT excluded.apelidos
                   OR ativos.tipo IS NOT excluded.tipo
                   OR ativos.origem IS NOT 'manual'
                """,
                dados,
            )
            if cur.rowcount:
                contagem["atualizados" if existe else "inseridos"] += 1

        marcadores = ",".join("?" * len(tickers))
        cur = conn.execute(
            f"UPDATE ativos SET origem = 'auto', ativo = 1, atualizado_em = ? "
            f"WHERE origem = 'manual' AND ticker NOT IN ({marcadores})",
            [agora, *tickers],
        )
        contagem["liberados"] = cur.rowcount

    logger.info(
        "Exceções do ativos.csv: %(inseridos)d inseridas, %(atualizados)d atualizadas, "
        "%(liberados)d devolvidas ao critério automático",
        contagem,
    )
    return contagem


def registrar_automaticos(conn: sqlite3.Connection, papeis: dict[str, str]) -> int:
    """Cadastra papéis detectados nos arquivos da B3 ({ticker: nome resumido}).
    Não altera papéis já cadastrados (inclusive exceções manuais)."""
    agora = agora_utc_iso()
    with conn:
        antes = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO ativos (ticker, nome, ativo, tipo, origem, criado_em, atualizado_em) "
            "VALUES (?, ?, 1, 'acao', 'auto', ?, ?)",
            [(t, n or t, agora, agora) for t, n in papeis.items()],
        )
        novos = conn.total_changes - antes
    if novos:
        logger.info("%d papéis novos detectados na B3", novos)
    return novos
