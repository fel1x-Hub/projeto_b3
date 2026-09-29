from datetime import datetime, timezone

import pytest

from src.coleta import noticias_rss as rss
from src.coleta.execucao import ColetaParcial
from src.db.ativos import sincronizar_ativos
from tests.coleta.conftest import HTTPFalso


def _item(titulo, link, data=None, resumo=""):
    pub = f"<pubDate>{data}</pubDate>" if data else ""
    return f"<item><title>{titulo}</title><link>{link}</link>{pub}<description>{resumo}</description></item>"


def _feed(*itens):
    return ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>t</title>'
            + "".join(itens) + "</channel></rss>").encode("utf-8")


FEED = _feed(
    _item("PETR4 sobe após balanço", "https://a/1", "Tue, 29 Sep 2026 16:17:21 +0000",
          "&lt;p&gt;A &lt;b&gt;Petrobras&lt;/b&gt; divulgou lucro&lt;/p&gt;"),
    _item("Vale a pena investir em renda fixa?", "https://a/2", "2026-09-29T13:10:49"),   # sem fuso
    _item("Mineradora Vale S.A. anuncia recompra", "https://a/3", "Wed, 30 Dec 2099 10:00:00 +0000"),  # futuro
    _item("Notícia sem data", "https://a/4"),
    _item("PETR4 SOBE após balanço!", "https://a/5"),          # mesmo título normalizado -> duplicata
    _item("Outro título", "https://a/1"),                        # mesma URL -> duplicata
)
AGORA = datetime(2026, 9, 29, 17, 0, tzinfo=timezone.utc)


@pytest.fixture
def conn_rss(conn, monkeypatch):
    sincronizar_ativos(conn, [
        {"ticker": "PETR4", "nome": "Petrobras", "setor": None, "cnpj": None, "ativo": 1},
        {"ticker": "VALE3", "nome": "Vale", "setor": None, "cnpj": None, "ativo": 1,
         "apelidos": "Vale S.A.|mineradora Vale"},
    ])

    class DatetimeFixo(datetime):
        @classmethod
        def now(cls, tz=None):
            return AGORA

    monkeypatch.setattr(rss, "datetime", DatetimeFixo)
    return conn


FEEDS = [{"nome": "teste", "url": "https://feed/teste"}]


def test_coleta_datas_dedup_e_associacao(conn_rss):
    assert rss.coletar(conn_rss, http=HTTPFalso({"feed/teste": FEED}), feeds=FEEDS) == 4
    n = {r["url"]: dict(r) for r in conn_rss.execute("SELECT * FROM noticias")}
    assert n["https://a/1"]["disponivel_em"] == "2026-09-29T16:17:21+00:00"
    assert n["https://a/1"]["resumo"] == "A Petrobras divulgou lucro"                  # HTML removido
    assert n["https://a/2"]["disponivel_em"] == "2026-09-29T16:10:49+00:00"          # sem fuso = BRT
    assert n["https://a/3"]["disponivel_em"] == "2026-09-29T17:00:00+00:00"          # futuro -> coleta
    assert n["https://a/4"]["disponivel_em"] == "2026-09-29T17:00:00+00:00"          # sem data -> coleta
    assert n["https://a/4"]["publicado_em"] is None
    assert n["https://a/1"]["fonte"] == "rss_teste"

    assoc = {(r["noticia_id"], r["ticker"]): r["metodo"] for r in conn_rss.execute("SELECT * FROM noticias_ativos")}
    ids = {url: d["id"] for url, d in n.items()}
    assert assoc == {
        (ids["https://a/1"], "PETR4"): "ticker_no_texto",
        (ids["https://a/3"], "VALE3"): "nome_no_texto",
    }  # "Vale a pena" NÃO é associado à VALE3


def test_segunda_execucao_nao_duplica(conn_rss):
    rss.coletar(conn_rss, http=HTTPFalso({"feed/teste": FEED}), feeds=FEEDS)
    assert rss.coletar(conn_rss, http=HTTPFalso({"feed/teste": FEED}), feeds=FEEDS) == 0


def test_feed_com_erro_nao_derruba_os_outros(conn_rss):
    feeds = FEEDS + [{"nome": "quebrado", "url": "https://feed/quebrado"}]
    http = HTTPFalso({"feed/teste": FEED, "feed/quebrado": ConnectionError("timeout")})
    with pytest.raises(ColetaParcial, match="quebrado") as e:
        rss.coletar(conn_rss, http=http, feeds=feeds)
    assert e.value.novos == 4


def test_feed_vazio_ou_invalido(conn_rss):
    http = HTTPFalso({"feed/teste": b"isto nao e xml"})
    with pytest.raises(RuntimeError, match="todos"):
        rss.coletar(conn_rss, http=http, feeds=FEEDS)


def test_resumo_cortado():
    texto = rss.limpar_texto("palavra " * 200, 50)
    assert len(texto) <= 51 and texto.endswith("…")


def test_feeds_do_projeto():
    assert {f["nome"] for f in rss.carregar_feeds()} == {"infomoney", "moneytimes", "exame", "valor"}
