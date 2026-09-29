from datetime import date

import pytest
import requests

from src.coleta import bcb_sgs
from tests.coleta.conftest import HTTPFalso

HOJE = date(2026, 9, 29)

SGS = {
    432: [{"data": "28/09/2026", "valor": "13.75"},
          {"data": "29/09/2026", "valor": "13.75"},
          {"data": "03/11/2026", "valor": "13.75"}],     # data futura: descartar
    12: [{"data": "28/09/2026", "valor": "0.050788"}],
    1: [{"data": "28/09/2026", "valor": "5.2132"}],
    433: [{"data": "01/07/2026", "valor": "0.07"},
          {"data": "01/08/2026", "valor": "-0.32"}],
}
IBGE = [{"id": "202607", "modificacao": "11/08/2026"}]  # agosto ainda sem data no IBGE


def _rota_sgs(dados):
    def responder(url, params):
        codigo = int(url.split("bcdata.sgs.")[1].split("/")[0])
        ini, fim = (bcb_sgs._data_br(params[k]) for k in ("dataInicial", "dataFinal"))
        return [d for d in dados.get(codigo, []) if ini <= bcb_sgs._data_br(d["data"]) <= fim]
    return responder


@pytest.fixture(autouse=True)
def hoje_fixo(monkeypatch):
    monkeypatch.setattr(bcb_sgs, "hoje_brt", lambda: HOJE)


def _macro(conn):
    return {(r["serie"], r["data"]): (r["valor"], r["disponivel_em"])
            for r in conn.execute("SELECT * FROM macro")}


def test_coleta_regras_de_disponibilidade(conn):
    http = HTTPFalso({"api.bcb.gov.br": _rota_sgs(SGS), "servicodados.ibge.gov.br": IBGE})
    assert bcb_sgs.coletar(conn, date(2026, 6, 1), http=http) == 6
    m = _macro(conn)
    assert ("selic_meta", "2026-11-03") not in m                                   # futuro descartado
    assert m[("cdi", "2026-09-28")] == (0.050788, "2026-09-29T02:59:59+00:00")     # fim do dia BRT
    assert m[("ipca", "2026-07-01")] == (0.07, "2026-08-11T12:00:00+00:00")        # divulgação IBGE 9h
    assert m[("ipca", "2026-08-01")][1] == "2026-09-15T12:00:00+00:00"             # fallback dia 15


def test_incremental(conn):
    http = HTTPFalso({"api.bcb.gov.br": _rota_sgs(SGS), "servicodados.ibge.gov.br": IBGE})
    bcb_sgs.coletar(conn, date(2026, 6, 1), http=http)
    http2 = HTTPFalso({"api.bcb.gov.br": _rota_sgs(SGS), "servicodados.ibge.gov.br": IBGE})
    assert bcb_sgs.coletar(conn, date(2026, 6, 1), http=http2) == 0


def test_periodo_sem_dados_404_e_vazio(conn):
    # sem rota -> HTTPFalso responde 404, como o SGS real
    assert bcb_sgs.coletar(conn, date(2026, 9, 1), http=HTTPFalso({})) == 0


def test_ibge_fora_do_ar_usa_fallback(conn):
    http = HTTPFalso({"api.bcb.gov.br": _rota_sgs(SGS),
                      "servicodados.ibge.gov.br": requests.ConnectionError("fora")})
    bcb_sgs.coletar(conn, date(2026, 6, 1), http=http)
    assert _macro(conn)[("ipca", "2026-07-01")][1] == "2026-08-15T12:00:00+00:00"


def test_janelas_de_consulta():
    chamadas = []
    http = HTTPFalso({"api.bcb.gov.br": lambda url, p: chamadas.append(p) or []})
    bcb_sgs.buscar_sgs(http, 1, date(2011, 1, 1), date(2026, 1, 1))
    assert len(chamadas) == 4  # 15 anos em janelas de 5
    assert chamadas[0]["dataInicial"] == "01/01/2011"
