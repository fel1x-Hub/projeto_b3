"""Utilitários para testar coletores sem rede."""

import io
import zipfile
from pathlib import Path

import pytest
import requests

from src.coleta.cliente_http import NaoEncontrado

AMOSTRAS = Path(__file__).parent / "amostras"


def resposta(status=200, corpo=b"", json_=None, headers=None):
    """Monta um requests.Response real (sem rede)."""
    r = requests.Response()
    r.status_code = status
    if json_ is not None:
        import json as _json
        corpo = _json.dumps(json_).encode()
    r.raw = io.BytesIO(corpo if isinstance(corpo, bytes) else corpo.encode())  # lido sob demanda
    r.headers.update(headers or {})
    r.url = "http://teste"
    return r


def zip_com(nome: str, conteudo: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(nome, conteudo)
    return buf.getvalue()


class HTTPFalso:
    """Substitui ClienteHTTP nos coletores.

    `rotas` mapeia um trecho de URL para: bytes (conteúdo), dict/list (JSON),
    uma Exception (levantada) ou um callable(url, params) -> qualquer um desses.
    URLs sem rota levantam NaoEncontrado (como um 404).
    """

    def __init__(self, rotas: dict):
        self.rotas = rotas
        self.chamadas: list[str] = []

    def _resolver(self, url, params=None):
        self.chamadas.append(url)
        for trecho, valor in self.rotas.items():
            if trecho in url:
                if callable(valor) and not isinstance(valor, type):
                    valor = valor(url, params)
                if isinstance(valor, Exception):
                    raise valor
                return valor
        raise NaoEncontrado(f"404 em {url}", response=resposta(404))

    def get_json(self, url, params=None):
        return self._resolver(url, params)

    def get_texto(self, url, params=None):
        return self._resolver(url, params)

    def baixar_arquivo(self, url, destino, reusar=True):
        destino = Path(destino)
        if reusar and destino.exists():
            return destino
        conteudo = self._resolver(url)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(conteudo)
        return destino


@pytest.fixture
def raw_tmp(tmp_path, monkeypatch):
    """Cache de arquivos brutos em tmp (nunca em data/raw)."""
    from config import settings
    pasta = tmp_path / "raw"
    monkeypatch.setattr(settings, "RAW_DIR", pasta)
    return pasta
