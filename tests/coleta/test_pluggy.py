import pytest

from src.coleta import pluggy

INVESTIMENTOS = [
    {"code": "PETR4", "type": "EQUITY", "subtype": "STOCK", "quantity": 100, "amount": 4969.0,
     "amountOriginal": 3050.0, "date": "2026-09-30T00:00:00.000Z", "institution": {"name": "XP Investimentos"}},
    {"code": "PETR4F", "type": "EQUITY", "subtype": "STOCK", "quantity": 7, "amount": 347.8, "date": None},
    {"code": "BOVA11", "type": "ETF", "quantity": 10, "amount": 1500.0},
    {"code": "CDB XYZ", "type": "FIXED_INCOME", "quantity": 1, "amount": 10000.0},
    {"code": "VALE3", "type": "EQUITY", "quantity": 0, "amount": 0},
]


class Resposta:
    def __init__(self, dados, status=200):
        self.dados, self.status_code = dados, status

    def json(self):
        return self.dados

    def raise_for_status(self):
        pass


class Sessao:
    def __init__(self):
        self.pedidos = []

    def post(self, url, json, timeout):
        self.pedidos.append(("POST", url, json))
        return Resposta({"apiKey": "chave-teste"})


class Cliente:
    timeout = 1

    def __init__(self):
        self.sessao, self.gets = Sessao(), []

    def get(self, url, params=None, headers=None):
        self.gets.append((url, params, headers))
        pagina = params["page"]
        return Resposta({"page": pagina, "totalPages": 2,
                         "results": INVESTIMENTOS[:3] if pagina == 1 else INVESTIMENTOS[3:]})


def test_so_papeis_de_bolsa_e_fracionario_somado():
    linhas = {l[0]: l for l in pluggy.posicoes(INVESTIMENTOS)}
    assert set(linhas) == {"PETR4", "BOVA11"}
    assert linhas["PETR4"][1:4] == (107.0, 3050.0, 4969.0 + 347.8)
    assert linhas["PETR4"][5] == "2026-09-30T00:00:00+00:00"


def test_sem_credenciais_nao_faz_nada(conn, monkeypatch):
    monkeypatch.delenv("PLUGGY_CLIENT_ID", raising=False)
    assert pluggy.coletar(conn, cliente=Cliente()) == 0


def test_sincroniza_paginas_e_substitui_a_foto(conn, monkeypatch):
    monkeypatch.setenv("PLUGGY_CLIENT_ID", "id")
    monkeypatch.setenv("PLUGGY_CLIENT_SECRET", "segredo")
    monkeypatch.setenv("PLUGGY_ITEM_IDS", "item-1")
    with conn:
        conn.execute("INSERT INTO carteira_sincronizada VALUES ('ABEV3', 5, NULL, NULL, 'x', NULL, "
                     "'2026-09-01T00:00:00+00:00')")
    cliente = Cliente()
    assert pluggy.coletar(conn, cliente=cliente) == 2
    assert [g[2] for g in cliente.gets] == [{"X-API-KEY": "chave-teste"}] * 2
    assert {r[0] for r in conn.execute("SELECT ticker FROM carteira_sincronizada")} == {"PETR4", "BOVA11"}
