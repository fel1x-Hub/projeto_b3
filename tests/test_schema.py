import sqlite3

import pytest

from src.db.migracoes import MIGRACOES, migrar, versao_atual

TABELAS = {
    "ativos", "cotacoes", "macro", "noticias", "noticias_ativos",
    "documentos", "execucoes_coleta", "revisoes", "schema_versao",
    "proventos", "demonstracoes",
    "sinais", "sentimento_noticias", "eventos_documentos", "llm_cache", "llm_erros", "universo", "ranking", "paper_config", "paper_carteira", "paper_patrimonio", "ranking_fatores", "cotacao_atual",
    "carteira_operacoes", "carteira_sincronizada", "relatorios", "usuarios", "calibracao", "padroes_efeito", "venda", "venda_calibracao",
}
INDICES = {
    "idx_noticias_disponivel_em", "idx_noticias_ativos_ticker",
    "idx_documentos_ticker_disponivel", "idx_execucoes_fonte_inicio",
    "uq_demonstracoes", "idx_demonstracoes_documento", "idx_demonstracoes_cia_disponivel",
    "idx_sinais_nome_data", "idx_universo_ticker", "idx_ranking_versao_data", "idx_carteira_operacoes_ticker",
}


def _nomes(conn, tipo):
    return {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = ? AND name NOT LIKE 'sqlite_%'", (tipo,)
    )}


def test_cria_banco_do_zero(conn_vazia):
    versao = migrar(conn_vazia)
    assert versao == MIGRACOES[-1][0]
    assert _nomes(conn_vazia, "table") == TABELAS
    assert INDICES <= _nomes(conn_vazia, "index")


def test_pragmas_da_conexao(conn_vazia):
    assert conn_vazia.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn_vazia.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_migracao_com_erro_nao_deixa_nada_pela_metade(conn_vazia):
    migracoes = [
        (1, "CREATE TABLE a (x INTEGER);"),
        (2, "CREATE TABLE b (x INTEGER); CREATE TABLE a (x INTEGER);"),  # 'a' já existe
    ]
    with pytest.raises(sqlite3.OperationalError):
        migrar(conn_vazia, migracoes)
    assert versao_atual(conn_vazia) == 1
    assert "b" not in _nomes(conn_vazia, "table")
    # corrigida a migração, ela é aplicada normalmente
    migracoes[1] = (2, "CREATE TABLE b (x INTEGER);")
    assert migrar(conn_vazia, migracoes) == 2


def test_aplica_somente_migracoes_novas(conn_vazia):
    migrar(conn_vazia, [(1, "CREATE TABLE a (x INTEGER);")])
    # se a v1 rodasse de novo, daria erro de tabela existente
    assert migrar(conn_vazia, [(1, "CREATE TABLE a (x INTEGER);"), (2, "CREATE TABLE b (x);")]) == 2


def test_rejeita_versoes_fora_de_ordem(conn_vazia):
    with pytest.raises(ValueError, match="crescentes"):
        migrar(conn_vazia, [(2, "SELECT 1;"), (1, "SELECT 1;")])


def test_migracao_2_sobre_banco_v1_com_dados(conn_vazia):
    migrar(conn_vazia, MIGRACOES[:1])
    with conn_vazia:
        conn_vazia.execute("INSERT INTO ativos (ticker, nome, ativo, criado_em, atualizado_em) "
                           "VALUES ('PETR4', 'Petrobras', 1, '2026-01-02T21:00:00+00:00', "
                           "'2026-01-02T21:00:00+00:00')")
    assert migrar(conn_vazia) == len(MIGRACOES)
    linha = conn_vazia.execute("SELECT tipo, apelidos FROM ativos").fetchone()
    assert tuple(linha) == ("acao", None)
