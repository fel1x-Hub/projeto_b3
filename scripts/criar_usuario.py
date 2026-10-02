"""Cria o usuário de login ou troca a senha dele. A senha nunca é gravada em texto, só o hash PBKDF2.

Uso:
    python scripts/criar_usuario.py "Miguel Felix"       # pede a senha sem mostrar
    python scripts/criar_usuario.py "Miguel Felix" --nuvem   # grava no Neon (usa DATABASE_URL)

Sem --nuvem, grava no banco local (SQLite). A senha é lida do teclado, sem
eco, ou da entrada padrão (para automação), nunca da linha de comando.
"""

import argparse
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.api import autenticacao  # noqa: E402
from src.db import schema_nuvem  # noqa: E402
from src.db.migracoes import migrar  # noqa: E402
from src.db.nuvem import ConexaoPG, conectar_api  # noqa: E402
from src.db.tempo import agora_utc_iso  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("usuario")
    parser.add_argument("--nuvem", action="store_true", help="gravar no Postgres da nuvem (DATABASE_URL)")
    args = parser.parse_args(argv)
    if args.nuvem and not os.getenv("DATABASE_URL"):
        print("DATABASE_URL ausente.")
        return 1
    if not args.nuvem:
        os.environ.pop("DATABASE_URL", None)
    senha = getpass.getpass("Senha: ") if sys.stdin.isatty() else sys.stdin.readline().rstrip("\r\n")
    conn = conectar_api()
    try:
        if isinstance(conn, ConexaoPG):
            schema_nuvem.garantir(conn)
        else:
            migrar(conn)
        autenticacao.gravar_usuario(conn, args.usuario, senha, agora_utc_iso())
    except ValueError as e:
        print(e)
        return 1
    finally:
        conn.close()
    print(f"Usuário '{autenticacao.normalizar_usuario(args.usuario)}' gravado ({'nuvem' if args.nuvem else 'local'}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
