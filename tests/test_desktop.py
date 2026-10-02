"""Smoke test do app Qt sem tela (offscreen) e com uma API falsa."""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.path.isdir("C:/Windows/Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")    # offscreen não acha as fontes sozinho
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from desktop.main import Janela  # noqa: E402

ENV = {"atualizado_em": "2026-10-01T17:16:00+00:00", "provisorio": True, "mercado_aberto": True}
LINHA = {"posicao": 1, "ticker": "PETR4", "nome": "Petrobras", "score": 0.6, "preco": 49.77, "variacao_dia": 0.0132,
         "sentimento_21d": None, "volume_relativo": 1.1, "na_carteira": True}
POSICAO = {"ticker": "PETR4", "nome": "Petrobras", "quantidade": 100, "preco_medio": 30.1, "custo": 3010, "preco": 49.77,
           "preco_horario": ENV["atualizado_em"], "provisorio": True, "valor": 4977, "variacao_dia": 0.0132,
           "ganho_dia": 64.8, "ganho": 1967, "ganho_pct": 0.653, "retorno_mes": 0.01, "retorno_ano": 0.6,
           "proventos": 100, "lucro_realizado": 0, "primeira_compra": "2026-01-05", "fonte_quantidade": "operacoes",
           "posicao_ranking": 1, "total_ranking": 246, "leitura": "manter", "fatores": [], "peso": 1.0}
RESPOSTAS = {
    "/mercado": {"ibovespa": {"nome": "Ibovespa", "valor": 186386.8, "variacao_dia": -0.002, "horario": ENV["atualizado_em"],
                              "provisorio": True},
                 "macro": {"selic_meta": {"valor": 13.75, "referencia": "2026-09-30"}},
                 "ranking": {"data": "2026-10-01"}, "topo": [LINHA], "fundo": [dict(LINHA, ticker="GFSA3", score=0.2)]},
    "/notificacoes": [{"tipo": "ranking", "nivel": "alerta", "ticker": "PETR4", "texto": "PETR4 caiu"}],
    "/ranking": {"ranking": {"data": "2026-10-01", "provisorio": True}, "linhas": [LINHA, dict(LINHA, posicao=2, ticker="VALE3")]},
    "/carteira": {"posicoes": [POSICAO], "totais": {"valor": 4977, "custo": 3010, "ganho": 1967, "ganho_pct": 0.653,
                                                    "ganho_dia": 64.8, "lucro_realizado": 0, "proventos": 100,
                                                    "inicio": "2026-01-05", "ibovespa_desde_inicio": 0.17},
                  "sincronizada_em": None, "instituicoes": [], "ranking": {"data": "2026-10-01"}, "avisos": []},
    "/carteira/indicacoes": {"comprar": [dict(LINHA, ticker="VALE3", fatores=[])], "vender": [], "observar": [],
                             "manter": [POSICAO], "sem_leitura": [], "ranking": {"data": "2026-10-01", "provisorio": True},
                             "regra": "regra", "aviso": "Não é recomendação de investimento."},
    "/carteira/evolucao": [{"data": "2026-09-30", "valor": 4900, "investido": 3010, "ibovespa_base": 1.0},
                           {"data": "2026-10-01", "valor": 4977, "investido": 3010, "ibovespa_base": 1.01}],
}


class APIFalsa:
    url = "http://falsa"

    def __init__(self):
        self.pedidos = []

    def get(self, caminho, **params):
        self.pedidos.append(caminho)
        if caminho not in RESPOSTAS:
            raise RuntimeError(f"sem resposta para {caminho}")
        return dict(ENV, dados=RESPOSTAS[caminho])

    def post(self, caminho, json=None, files=None):
        raise RuntimeError("não usado")


def _esperar(app, condicao, segundos=5):
    fim = time.time() + segundos
    while time.time() < fim and not condicao():
        app.processEvents()
        time.sleep(0.02)
    return condicao()


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_janela_carrega_abas_e_mostra_status(app):
    api = APIFalsa()
    j = Janela(api)
    assert _esperar(app, lambda: j.l_selo.isVisible() or j.l_selo.text() == "PROVISÓRIO")
    assert _esperar(app, lambda: j.mercado.alertas.count() == 1)
    assert "186.387" in j.mercado.c_ibov.valor.text()
    assert j.l_mercado.text() == "● Pregão aberto"

    j.abas.setCurrentWidget(j.ranking)
    assert _esperar(app, lambda: j.ranking.modelo.rowCount() == 2)
    assert "PROVISÓRIO" in j.ranking.info.text()
    j.ranking.filtro.setText("vale")
    assert j.ranking.proxy.rowCount() == 1

    j.abas.setCurrentWidget(j.carteira)
    assert _esperar(app, lambda: j.carteira.m_pos.rowCount() == 1)
    assert _esperar(app, lambda: "Comprar" in j.carteira.indicacoes.toPlainText())
    assert "R$ 4.977,00" in j.carteira.c_valor.valor.text()


def test_falha_da_api_mantem_ultimo_dado_e_avisa(app):
    j = Janela(APIFalsa())
    j.abas.setCurrentWidget(j.relatorio)          # /relatorio/ultimo não existe na API falsa
    assert _esperar(app, lambda: "Falha ao atualizar" in j.statusBar().currentMessage())
