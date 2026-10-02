"""Gera o app desktop como um único ProjetoB3.exe (etapa 8.5), sem precisar de administrador.

Uso:  python desktop/construir.py      -> dist/ProjetoB3.exe

O .exe é um cliente fino da API (nuvem ou local): a API embutida, o pipeline e
as bibliotecas pesadas ficam de fora (só servem rodando do código-fonte).
"""

import sys
from pathlib import Path

import PyInstaller.__main__

RAIZ = Path(__file__).resolve().parent.parent
FORA = ["src", "uvicorn", "fastapi", "starlette", "pandas", "lightgbm", "scipy", "torch", "transformers",
        "matplotlib", "yfinance", "sklearn", "pytest", "psycopg", "google", "pypdf", "feedparser",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore", "PySide6.QtQuick"]


def main() -> int:
    argumentos = [str(RAIZ / "desktop" / "main.py"), "--name", "ProjetoB3", "--onefile", "--windowed",
                  "--noconfirm", "--clean", "--paths", str(RAIZ),
                  "--distpath", str(RAIZ / "dist"), "--workpath", str(RAIZ / "build"), "--specpath", str(RAIZ / "build")]
    for modulo in FORA:
        argumentos += ["--exclude-module", modulo]
    PyInstaller.__main__.run(argumentos)
    return 0


if __name__ == "__main__":
    sys.exit(main())
