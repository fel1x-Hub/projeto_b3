"""Cliente da API para o app desktop (regra 10: o app só fala com a API).

Endereço em API_URL (padrão http://127.0.0.1:8000; "127.0.0.1" e não
"localhost": no Windows, localhost tenta IPv6 antes e custa ~2 s por chamada).
Se não houver API no ar e o endereço for local, o app sobe uma embutida.
"""

import os
import threading
import time

import httpx
from dotenv import load_dotenv

from config import settings

load_dotenv(settings.BASE_DIR / ".env")
API_URL = os.getenv("API_URL", "http://127.0.0.1:8000").rstrip("/")


class ErroAPI(Exception):
    pass


class ClienteAPI:
    def __init__(self, url: str = API_URL, token: str | None = None, timeout: float = 120):
        self.url = url
        self._http = httpx.Client(base_url=url, timeout=timeout,
                                  headers={"Authorization": f"Bearer {token or os.getenv('API_TOKEN', '')}"})

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

    def no_ar(self) -> bool:
        try:
            return self._http.get("/saude", timeout=2).status_code == 200
        except httpx.HTTPError:
            return False


def garantir_api(cliente: ClienteAPI, espera: float = 30) -> bool:
    """Sobe a API embutida (thread do próprio app) se não houver uma no ar. True = ok."""
    if cliente.no_ar():
        return True
    if not cliente.url.startswith(("http://127.0.0.1", "http://localhost")):
        return False                                   # API remota fora do ar: não há o que subir
    import uvicorn

    from src.api.main import app

    porta = int(cliente.url.rsplit(":", 1)[1])
    servidor = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=porta, log_level="warning"))
    threading.Thread(target=servidor.run, daemon=True, name="api-embutida").start()
    fim = time.monotonic() + espera
    while time.monotonic() < fim:
        if cliente.no_ar():
            return True
        time.sleep(0.3)
    return False
