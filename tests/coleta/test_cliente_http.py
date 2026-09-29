import pytest
import requests

from src.coleta.cliente_http import ClienteHTTP, NaoEncontrado
from tests.coleta.conftest import resposta


class SessaoFalsa:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.headers = {}
        self.chamadas = 0

    def get(self, url, params=None, timeout=None, stream=False):
        self.chamadas += 1
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _cliente(respostas, **kw):
    esperas = []
    sessao = SessaoFalsa(respostas)
    cliente = ClienteHTTP(sessao=sessao, dormir=esperas.append, relogio=lambda: 0.0,
                          intervalo_por_host=0, **kw)
    return cliente, sessao, esperas


def test_sucesso_direto():
    cliente, sessao, esperas = _cliente([resposta(json_={"ok": 1})])
    assert cliente.get_json("http://x/a") == {"ok": 1}
    assert sessao.chamadas == 1 and esperas == []


def test_retry_com_backoff_em_5xx_e_timeout():
    cliente, sessao, esperas = _cliente([
        resposta(503), requests.Timeout("lento"), requests.ConnectionError("caiu"), resposta(corpo=b"ok"),
    ])
    assert cliente.get_texto("http://x/a") == b"ok"
    assert sessao.chamadas == 4
    assert esperas == [1.0, 2.0, 4.0]


def test_429_respeita_retry_after():
    cliente, _, esperas = _cliente([resposta(429, headers={"Retry-After": "7"}), resposta(corpo=b"ok")])
    assert cliente.get_texto("http://x/a") == b"ok"
    assert esperas == [7.0]


def test_desiste_apos_todas_as_tentativas():
    cliente, sessao, _ = _cliente([requests.Timeout("lento")] * 3, tentativas=3)
    with pytest.raises(requests.Timeout):
        cliente.get("http://x/a")
    assert sessao.chamadas == 3


def test_404_nao_repete():
    cliente, sessao, _ = _cliente([resposta(404)])
    with pytest.raises(NaoEncontrado):
        cliente.get("http://x/a")
    assert sessao.chamadas == 1


def test_400_nao_repete():
    cliente, sessao, _ = _cliente([resposta(400)])
    with pytest.raises(requests.HTTPError):
        cliente.get("http://x/a")
    assert sessao.chamadas == 1


def test_intervalo_minimo_por_host():
    esperas = []
    sessao = SessaoFalsa([resposta(), resposta(), resposta()])
    cliente = ClienteHTTP(sessao=sessao, dormir=esperas.append, relogio=lambda: 10.0, intervalo_por_host=0.5)
    cliente.get("http://a.com/1")
    cliente.get("http://a.com/2")  # mesmo host, logo em seguida: espera
    cliente.get("http://b.com/1")  # outro host: não espera
    assert esperas == [0.5]


def test_baixar_arquivo_usa_cache(tmp_path):
    cliente, sessao, _ = _cliente([resposta(corpo=b"conteudo")])
    destino = tmp_path / "sub" / "a.zip"
    assert cliente.baixar_arquivo("http://x/a.zip", destino).read_bytes() == b"conteudo"
    cliente.baixar_arquivo("http://x/a.zip", destino)  # segunda vez: cache, sem requisição
    assert sessao.chamadas == 1
    assert not (tmp_path / "sub" / "a.zip.parcial").exists()
