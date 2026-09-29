"""Inserção e leitura básica em cada tabela, e as restrições do schema."""

import sqlite3

import pytest

from tests.conftest import TS

COTACAO = {
    "ticker": "PETR4", "data": "2026-01-02", "abertura": 30.0, "maxima": 31.0,
    "minima": 29.5, "fechamento": 30.5, "fechamento_ajustado": 30.1, "volume": 1000,
    "fonte": "brapi", "disponivel_em": TS, "coletado_em": TS,
}


def _inserir(conn, tabela, dados):
    colunas = ", ".join(dados)
    marcadores = ", ".join(f":{c}" for c in dados)
    with conn:
        return conn.execute(f"INSERT INTO {tabela} ({colunas}) VALUES ({marcadores})", dados).lastrowid


def test_cotacoes(conn):
    _inserir(conn, "cotacoes", COTACAO)
    linha = conn.execute("SELECT * FROM cotacoes WHERE ticker = 'PETR4'").fetchone()
    assert linha["fechamento"] == 30.5 and linha["data"] == "2026-01-02"


def test_cotacao_duplicada_e_rejeitada(conn):
    _inserir(conn, "cotacoes", COTACAO)
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        _inserir(conn, "cotacoes", COTACAO)
    # mesma data vinda de outra fonte é permitida
    _inserir(conn, "cotacoes", {**COTACAO, "fonte": "yfinance"})


def test_fk_rejeita_ticker_inexistente(conn):
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        _inserir(conn, "cotacoes", {**COTACAO, "ticker": "XXXX3"})


@pytest.mark.parametrize("campo, valor", [
    ("disponivel_em", "2026-01-02 18:00:00"),        # sem T e sem fuso
    ("disponivel_em", "2026-01-02T18:00:00-03:00"),  # fuso diferente de UTC
    ("data", "02/01/2026"),
    ("data", "2026-02-30"),
    ("fechamento", 0),
    ("volume", -1),
])
def test_valores_invalidos_sao_rejeitados(conn, campo, valor):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        _inserir(conn, "cotacoes", {**COTACAO, campo: valor})


def test_disponivel_em_e_obrigatorio(conn):
    dados = {k: v for k, v in COTACAO.items() if k != "disponivel_em"}
    with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
        _inserir(conn, "cotacoes", dados)


def test_filtro_anti_look_ahead_por_texto(conn):
    _inserir(conn, "cotacoes", COTACAO)
    _inserir(conn, "cotacoes", {**COTACAO, "data": "2026-01-05",
                                "disponivel_em": "2026-01-05T21:00:00+00:00"})
    datas = [r[0] for r in conn.execute(
        "SELECT data FROM cotacoes WHERE disponivel_em <= ? ORDER BY data",
        ("2026-01-03T00:00:00+00:00",),
    )]
    assert datas == ["2026-01-02"]


def test_macro(conn):
    dados = {"serie": "ipca", "data": "2026-03-01", "valor": 0.42, "fonte": "bcb_sgs",
             "disponivel_em": "2026-04-10T12:00:00+00:00", "coletado_em": TS}
    _inserir(conn, "macro", dados)
    assert conn.execute("SELECT valor FROM macro").fetchone()[0] == 0.42
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        _inserir(conn, "macro", dados)


def test_noticias_e_associacao(conn):
    noticia = {"titulo": "Petrobras anuncia dividendos", "resumo": None,
               "url": "https://exemplo.com/a", "fonte": "rss_x", "publicado_em": TS,
               "disponivel_em": TS, "coletado_em": TS, "hash": "abc"}
    nid = _inserir(conn, "noticias", noticia)
    _inserir(conn, "noticias_ativos", {"noticia_id": nid, "ticker": "PETR4", "metodo": "nome_no_texto"})
    linha = conn.execute(
        "SELECT n.titulo, na.ticker FROM noticias n JOIN noticias_ativos na ON na.noticia_id = n.id"
    ).fetchone()
    assert tuple(linha) == ("Petrobras anuncia dividendos", "PETR4")

    # mesmo hash com outra URL: duplicata
    with pytest.raises(sqlite3.IntegrityError, match="noticias.hash"):
        _inserir(conn, "noticias", {**noticia, "url": "https://exemplo.com/b"})
    # mesma URL com outro hash: duplicata
    with pytest.raises(sqlite3.IntegrityError, match="noticias.url"):
        _inserir(conn, "noticias", {**noticia, "hash": "def"})
    # associação repetida
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        _inserir(conn, "noticias_ativos", {"noticia_id": nid, "ticker": "PETR4", "metodo": "x"})

    # apagar a notícia remove as associações
    with conn:
        conn.execute("DELETE FROM noticias WHERE id = ?", (nid,))
    assert conn.execute("SELECT COUNT(*) FROM noticias_ativos").fetchone()[0] == 0


def test_data_opcional_invalida_e_rejeitada(conn):
    doc = {"tipo": "dfp", "fonte": "cvm", "id_externo": "1", "url": "u",
           "data_referencia": "31/12/2025", "disponivel_em": TS, "coletado_em": TS}
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        _inserir(conn, "documentos", doc)
    _inserir(conn, "documentos", {**doc, "data_referencia": None})


def test_documentos(conn):
    doc = {"tipo": "fato_relevante", "ticker": "PETR4", "data_referencia": "2026-01-02",
           "fonte": "cvm", "id_externo": "000123", "url": "https://cvm/doc",
           "disponivel_em": TS, "coletado_em": TS}
    _inserir(conn, "documentos", doc)
    assert conn.execute("SELECT tipo FROM documentos").fetchone()[0] == "fato_relevante"
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        _inserir(conn, "documentos", doc)
    # sem conteúdo, arquivo nem URL não há como chegar ao documento
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        _inserir(conn, "documentos", {**doc, "id_externo": "000124", "url": None})


def test_execucoes_coleta(conn):
    eid = _inserir(conn, "execucoes_coleta", {"fonte": "brapi", "inicio": TS, "status": "em_andamento"})
    with conn:
        conn.execute("UPDATE execucoes_coleta SET fim = ?, status = 'sucesso', registros_novos = 10 "
                     "WHERE id = ?", (TS, eid))
    linha = conn.execute("SELECT status, registros_novos FROM execucoes_coleta").fetchone()
    assert tuple(linha) == ("sucesso", 10)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        _inserir(conn, "execucoes_coleta", {"fonte": "brapi", "inicio": TS, "status": "ok"})


def test_revisoes(conn):
    rev = {"tabela": "cotacoes", "chave_registro": '{"ticker": "PETR4", "data": "2026-01-02"}',
           "campo": "fechamento", "valor_antigo": "30.5", "valor_novo": "30.6",
           "fonte": "brapi", "detectado_em": TS}
    _inserir(conn, "revisoes", rev)
    assert conn.execute("SELECT campo FROM revisoes").fetchone()[0] == "fechamento"
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        _inserir(conn, "revisoes", {**rev, "chave_registro": "não é json"})


PROVENTO = {"ticker": "PETR4", "tipo": "dividendo", "data_ex": "2026-08-24", "valor": 1.35,
            "fator": None, "fonte": "yfinance", "disponivel_em": TS, "coletado_em": TS}


def test_proventos(conn):
    _inserir(conn, "proventos", PROVENTO)
    _inserir(conn, "proventos", {**PROVENTO, "tipo": "desdobramento", "valor": None, "fator": 2.0})
    assert conn.execute("SELECT COUNT(*) FROM proventos").fetchone()[0] == 2
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        _inserir(conn, "proventos", PROVENTO)


@pytest.mark.parametrize("mudanca", [
    {"valor": None},                    # dividendo sem valor
    {"valor": -1.0},                    # valor negativo
    {"fator": 2.0},                     # dividendo com fator
    {"tipo": "bonus"},                  # tipo desconhecido
])
def test_proventos_invalidos(conn, mudanca):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        _inserir(conn, "proventos", {**PROVENTO, **mudanca})


def test_demonstracoes_unicidade_com_datas_nulas(conn):
    linha = {"codigo_cvm": "9512", "tipo_doc": "DFP", "data_referencia": "2025-12-31", "versao": 1,
             "demonstrativo": "BPA", "consolidado": 1, "data_ini": None, "data_fim": "2025-12-31",
             "cd_conta": "1", "ds_conta": "Ativo Total", "valor": 1e12,
             "disponivel_em": TS, "coletado_em": TS}
    _inserir(conn, "demonstracoes", linha)
    # data_ini nula não pode abrir brecha para duplicata
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        _inserir(conn, "demonstracoes", linha)
    # outra versão (reapresentação) é outra linha
    _inserir(conn, "demonstracoes", {**linha, "versao": 2})
