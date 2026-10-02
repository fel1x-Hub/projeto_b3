"""Empacota o banco de trabalho para subir à nuvem (etapa 8): data/banco.tar.gz.

Uso:
    python scripts/empacotar_banco.py

O pacote vai para um Release PÚBLICO do GitHub (o workflow "Inicializar nuvem"
o baixa), então a cópia empacotada sai SEM dados pessoais: as tabelas da
carteira são esvaziadas na cópia (o banco original não é alterado). O resto são
dados públicos (B3, CVM, BCB, notícias) e os cálculos do sistema.
"""

import sqlite3
import sys
import tarfile
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402

PESSOAIS = ("carteira_operacoes", "carteira_sincronizada")


def empacotar(origem: Path, modelos: Path, destino: Path) -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        copia = Path(tmp) / "b3.db"
        fonte = sqlite3.connect(f"file:{origem}?mode=ro", uri=True)
        alvo = sqlite3.connect(copia)
        fonte.backup(alvo)                       # cópia consistente mesmo com o agendador rodando
        fonte.close()
        with alvo:
            for tabela in PESSOAIS:
                alvo.execute(f"DELETE FROM {tabela}")
        restantes = sum(alvo.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in PESSOAIS)
        alvo.execute("PRAGMA journal_mode = DELETE")
        alvo.close()
        if restantes:
            raise RuntimeError("a cópia ainda tem dados da carteira; abortando")
        with tarfile.open(destino, "w:gz", compresslevel=1) as tar:
            tar.add(copia, arcname="data/b3.db")
            tar.add(modelos, arcname="data/modelos")
    return destino


def main() -> int:
    destino = settings.BASE_DIR / "data" / "banco.tar.gz"
    empacotar(settings.DB_PATH, settings.BASE_DIR / "data" / "modelos", destino)
    print(f"Pacote pronto (sem dados da carteira): {destino} ({destino.stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
