"""Login por usuário e senha (pedido do usuário, 02/10/2026).

- Senha: guardada só como hash PBKDF2-SHA256 com sal aleatório (tabela
  `usuarios`), nunca em texto. Comparação em tempo constante.
- Sessão: token assinado (HMAC-SHA256) com usuário e validade (30 dias). A
  chave vem de SESSAO_SEGREDO ou, na falta, é derivada do API_TOKEN, que já é
  segredo em todos os ambientes. Trocar a chave derruba todas as sessões.
- O API_TOKEN continua aceito (scripts e testes); o site e o app usam a sessão.
"""

import base64
import hashlib
import hmac
import os
import secrets
import time

ITERACOES = 600_000          # recomendação OWASP para PBKDF2-SHA256
VALIDADE_DIAS = 30


def normalizar_usuario(usuario: str) -> str:
    return " ".join(usuario.split()).casefold()    # "Miguel  Felix" = "miguel felix"


def hash_senha(senha: str, sal: bytes | None = None, iteracoes: int = ITERACOES) -> str:
    sal = sal or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", senha.encode(), sal, iteracoes)
    return f"pbkdf2_sha256${iteracoes}${sal.hex()}${dk.hex()}"


def verificar_senha(senha: str, guardado: str) -> bool:
    try:
        _, iteracoes, sal, esperado = guardado.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", senha.encode(), bytes.fromhex(sal), int(iteracoes))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk.hex(), esperado)


def _chave() -> bytes:
    base = os.getenv("SESSAO_SEGREDO") or os.getenv("API_TOKEN", "")
    if not base:
        raise RuntimeError("sem SESSAO_SEGREDO nem API_TOKEN para assinar sessões")
    return hashlib.sha256(b"sessao:" + base.encode()).digest()


def _b64(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).decode().rstrip("=")


def _de_b64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def emitir_sessao(usuario: str, agora: float | None = None, dias: int = VALIDADE_DIAS) -> str:
    expira = int((agora or time.time()) + dias * 86400)
    corpo = _b64(f"{normalizar_usuario(usuario)}|{expira}".encode())
    assinatura = _b64(hmac.new(_chave(), corpo.encode(), hashlib.sha256).digest())
    return f"s1.{corpo}.{assinatura}"


def validar_sessao(token: str, agora: float | None = None) -> str | None:
    """Usuário da sessão, ou None se inválida/expirada."""
    try:
        versao, corpo, assinatura = token.split(".")
        if versao != "s1":
            return None
        certa = _b64(hmac.new(_chave(), corpo.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(certa, assinatura):
            return None
        usuario, expira = _de_b64(corpo).decode().rsplit("|", 1)
    except (ValueError, UnicodeDecodeError):
        return None
    return usuario if int(expira) > (agora or time.time()) else None


def autenticar_usuario(conn, usuario: str, senha: str) -> str | None:
    """Confere usuário e senha no banco; devolve o nome normalizado ou None."""
    nome = normalizar_usuario(usuario)
    linha = conn.execute("SELECT senha_hash FROM usuarios WHERE usuario = ?", (nome,)).fetchone()
    if linha is None:
        verificar_senha(senha, hash_senha("x", b"0" * 16))   # mesmo custo com ou sem usuário
        return None
    return nome if verificar_senha(senha, linha[0]) else None


def gravar_usuario(conn, usuario: str, senha: str, agora_iso: str) -> None:
    if len(senha) < 8:
        raise ValueError("senha precisa ter pelo menos 8 caracteres")
    with conn:
        conn.execute("INSERT INTO usuarios (usuario, senha_hash, criado_em) VALUES (?, ?, ?) "
                     "ON CONFLICT (usuario) DO UPDATE SET senha_hash = excluded.senha_hash",
                     (normalizar_usuario(usuario), hash_senha(senha), agora_iso))
