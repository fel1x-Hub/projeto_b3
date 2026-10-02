"""Cliente da API para o app desktop (regra 10: o app só fala com a API).

Ordem de conexão (etapa 8.5):
1. a API configurada (nuvem, ex.: https://projeto-b3.onrender.com). O Render
   grátis dorme sem uso e leva ~1 min para acordar, por isso a espera é longa;
2. uma API local em http://127.0.0.1:8000 (se você a estiver rodando);
3. rodando do código-fonte (não do .exe): sobe a API embutida no próprio app.
"127.0.0.1" e não "localhost": no Windows, localhost tenta IPv6 antes e custa ~2 s.
"""

import os
import sys
import threading
import time

import httpx
from dotenv import load_dotenv

from config import settings

load_dotenv(settings.BASE_DIR / ".env")
LOCAL = "http://127.0.0.1:8000"
EMPACOTADO = getattr(sys, "frozen", False)      # rodando como .exe (PyInstaller)


class ErroAPI(Exception):
    pass


class ClienteAPI:
    def __init__(self, url: str = LOCAL, token: str | None = None, timeout: float = 120):
        self.url = url.rstrip("/")
        self.token = token if token is not None else os.getenv("API_TOKEN", "")
        self._http = httpx.Client(base_url=self.url, timeout=timeout,
                                  headers={"Authorization": f"Bearer {self.token}"})

    def _tratar(self, r: httpx.Response):
        if r.status_code >= 400:
            try:
                detalhe = r.json().get("detail")
            except ValueError:
                detalhe = r.text[:200]
            raise ErroAPI(detalhe if isinstance(detalhe, str) else str(detalhe))
        return r.json()

    def get(self, caminho: str, **params):
        return self._tratar(self._http.get(caminho, params={k: v for k, v in params.items() if v is not None}))

    def post(self, caminho: str, json=None, files=None):
        return self._tratar(self._http.post(caminho, json=json, files=files))

    def delete(self, caminho: str):
        return self._tratar(self._http.delete(caminho))

    def no_ar(self, timeout: float = 2) -> bool:
        try:
            return self._http.get("/saude", timeout=timeout).status_code == 200
        except httpx.HTTPError:
            return False

    def token_valido(self) -> bool:
        """Sessão de login (ou API_TOKEN local) aceita pela API."""
        try:
            r = self._http.get("/eu", timeout=30)
            return r.status_code == 200 and r.json().get("logado", False)
        except (httpx.HTTPError, ValueError):
            return False


def entrar(url: str, usuario: str, senha: str) -> str:
    """Faz login e devolve a sessão (a senha não é guardada). Espera o servidor acordar."""
    r = httpx.post(url.rstrip("/") + "/login", json={"usuario": usuario, "senha": senha}, timeout=120)
    if r.status_code == 401:
        raise ErroAPI("usuário ou senha incorretos")
    if r.status_code == 429:
        raise ErroAPI("muitas tentativas; espere um minuto")
    r.raise_for_status()
    return r.json()["sessao"]


def _local(url: str) -> bool:
    return url.startswith(("http://127.0.0.1", "http://localhost"))


def esperar(cliente: ClienteAPI, segundos: float, aviso=None) -> bool:
    """Espera a API responder (a da nuvem pode estar acordando)."""
    fim = time.monotonic() + segundos
    while time.monotonic() < fim:
        if cliente.no_ar(timeout=10 if not _local(cliente.url) else 2):
            return True
        if aviso:
            aviso(f"Esperando a API em {cliente.url} (o servidor grátis pode levar ~1 min para acordar)…")
        time.sleep(1 if _local(cliente.url) else 3)
    return False


def subir_embutida(porta: int = 8000, espera: float = 30) -> bool:
    """Sobe a API no próprio processo (só rodando do código-fonte, com o banco local)."""
    if EMPACOTADO:
        return False
    import uvicorn

    from src.api.main import app
    servidor = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=porta, log_level="warning"))
    threading.Thread(target=servidor.run, daemon=True, name="api-embutida").start()
    return esperar(ClienteAPI(f"http://127.0.0.1:{porta}"), espera)


def conectar(url: str | None, token: str | None, aviso=None) -> ClienteAPI | None:
    """Primeira API que responder, na ordem: configurada (nuvem), local, embutida."""
    candidatos = []
    if url:
        candidatos.append((url, 90))
    if not url or not _local(url):
        candidatos.append((LOCAL, 2))
    for endereco, espera in candidatos:
        c = ClienteAPI(endereco, token)
        if esperar(c, espera, aviso):
            return c
    if subir_embutida():
        return ClienteAPI(LOCAL, token)
    return None
