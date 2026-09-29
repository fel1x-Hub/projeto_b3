"""Cliente HTTP comum a todas as fontes.

- Timeout em toda requisição.
- Retry com espera exponencial em 429, 5xx, timeout e erro de conexão,
  respeitando o cabeçalho Retry-After.
- Intervalo mínimo entre requisições ao mesmo host (educação com as fontes).
- Download em streaming com cache local: arquivo já baixado não é baixado de novo
  quando `reusar=True`.
Erros 4xx (exceto 429) não são repetidos; 404 vira `NaoEncontrado`.
"""

import logging
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

USER_AGENT = "projeto_b3/0.2 (uso pessoal; +https://github.com/fel1x-Hub/projeto_b3)"
STATUS_REPETIR = {429, 500, 502, 503, 504}


class NaoEncontrado(requests.HTTPError):
    """HTTP 404: o recurso não existe (ex: arquivo diário de um feriado)."""


class ClienteHTTP:
    def __init__(
        self,
        timeout: float = 60,
        tentativas: int = 5,
        espera_base: float = 1.0,
        espera_max: float = 60.0,
        intervalo_por_host: float = 0.5,
        sessao: requests.Session | None = None,
        dormir=time.sleep,
        relogio=time.monotonic,
    ):
        self.timeout = timeout
        self.tentativas = tentativas
        self.espera_base = espera_base
        self.espera_max = espera_max
        self.intervalo_por_host = intervalo_por_host
        self.sessao = sessao or requests.Session()
        self.sessao.headers.setdefault("User-Agent", USER_AGENT)
        self._dormir = dormir
        self._relogio = relogio
        self._ultima_por_host: dict[str, float] = {}

    def _respeitar_intervalo(self, url: str) -> None:
        host = urlparse(url).netloc
        ultima = self._ultima_por_host.get(host)
        if ultima is not None:
            falta = self.intervalo_por_host - (self._relogio() - ultima)
            if falta > 0:
                self._dormir(falta)
        self._ultima_por_host[host] = self._relogio()

    def _espera(self, tentativa: int, resposta: requests.Response | None) -> float:
        if resposta is not None:
            retry_after = resposta.headers.get("Retry-After", "")
            if retry_after.isdigit():
                return min(float(retry_after), self.espera_max)
        return min(self.espera_base * 2 ** tentativa, self.espera_max)

    def get(self, url: str, params: dict | None = None, stream: bool = False, **kwargs) -> requests.Response:
        """GET com retry. Devolve a resposta 2xx ou levanta a última exceção."""
        for tentativa in range(self.tentativas):
            self._respeitar_intervalo(url)
            resposta = None
            try:
                resposta = self.sessao.get(url, params=params, timeout=self.timeout, stream=stream, **kwargs)
                if resposta.status_code == 404:
                    raise NaoEncontrado(f"404 em {url}", response=resposta)
                if resposta.status_code not in STATUS_REPETIR:
                    resposta.raise_for_status()
                    return resposta
                erro: Exception = requests.HTTPError(f"HTTP {resposta.status_code} em {url}", response=resposta)
            except (requests.Timeout, requests.ConnectionError) as e:
                erro = e
            if tentativa == self.tentativas - 1:
                raise erro
            espera = self._espera(tentativa, resposta)
            logger.warning("%s; tentativa %d/%d, nova tentativa em %.1fs",
                           erro, tentativa + 1, self.tentativas, espera)
            self._dormir(espera)
        raise AssertionError("inalcançável")

    def get_json(self, url: str, params: dict | None = None):
        return self.get(url, params=params).json()

    def get_texto(self, url: str, params: dict | None = None) -> bytes:
        return self.get(url, params=params).content

    def baixar_arquivo(self, url: str, destino: Path, reusar: bool = True) -> Path:
        """Baixa `url` para `destino` (via arquivo temporário, para nunca deixar
        arquivo pela metade). Com `reusar=True`, não baixa se já existir."""
        destino = Path(destino)
        if reusar and destino.exists():
            logger.debug("Usando cache: %s", destino)
            return destino
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporario = destino.with_suffix(destino.suffix + ".parcial")
        logger.info("Baixando %s", url)
        resposta = self.get(url, stream=True)
        try:
            with open(temporario, "wb") as f:
                for bloco in resposta.iter_content(chunk_size=1 << 20):
                    f.write(bloco)
        finally:
            resposta.close()
        temporario.replace(destino)
        return destino
