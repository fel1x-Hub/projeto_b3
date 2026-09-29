"""Configuração de logging do projeto.

Os módulos usam `logging.getLogger(__name__)`; apenas os pontos de entrada
(scripts) chamam `configurar_logging()`.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import settings

FORMATO = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_MARCA = "_b3_handler"  # identifica os handlers criados aqui


def configurar_logging(nivel: str | None = None, log_dir: Path | str | None = None) -> None:
    """Envia logs para o console e para `<log_dir>/app.log` (com rotação).

    Idempotente: chamar de novo substitui os handlers deste módulo em vez de
    duplicá-los.
    """
    raiz = logging.getLogger()
    raiz.setLevel((nivel or settings.LOG_LEVEL).upper())

    for h in [h for h in raiz.handlers if getattr(h, _MARCA, False)]:
        raiz.removeHandler(h)
        h.close()

    log_dir = Path(log_dir) if log_dir else settings.LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(FORMATO)
    console = logging.StreamHandler(sys.stderr)
    arquivo = RotatingFileHandler(
        log_dir / "app.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    for h in (console, arquivo):
        h.setFormatter(formatter)
        setattr(h, _MARCA, True)
        raiz.addHandler(h)
