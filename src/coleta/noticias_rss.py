"""Notícias por RSS dos portais listados em config/feeds.csv.

RSS só traz os itens mais recentes (10 a 100 por feed): não existe carga
histórica, o acervo cresce a cada execução, e `desde` não se aplica.
Guarda título, um trecho do resumo (até 500 caracteres) e o link; nunca o
texto integral.

`disponivel_em` = horário de publicação. Data sem fuso (ex: Exame) é lida
como horário de Brasília; sem data, ou com data no futuro, usa o momento da
coleta.

Deduplicação: `hash` = sha256(título normalizado + fonte) e URL única.

Associação notícia -> ativo (limitações conhecidas):
- procura o ticker e os apelidos do ativo (ou o nome, se não houver
  apelidos) no título e no resumo, com fronteira de palavra e diferenciando
  maiúsculas;
- nomes que também são palavras comuns geram falsos positivos (ex: "Vale"
  no início de frase), por isso os apelidos devem ser específicos;
- não entende contexto: uma notícia que só cita a empresa de passagem também
  é associada.
"""

import csv
import hashlib
import html
import logging
import re
import sqlite3
import unicodedata
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser

from config import settings
from src.coleta.cliente_http import ClienteHTTP
from src.coleta.execucao import ColetaParcial
from src.db.tempo import FUSO_B3, para_iso_utc

logger = logging.getLogger(__name__)

FONTE_PREFIXO = "rss"
TAMANHO_RESUMO = 500
_TAG = re.compile(r"<[^>]+>")


def carregar_feeds(caminho=None) -> list[dict]:
    with open(caminho or settings.FEEDS_CSV, encoding="utf-8-sig", newline="") as f:
        return [{"nome": r["nome"].strip(), "url": r["url"].strip()} for r in csv.DictReader(f) if r.get("url")]


def limpar_texto(texto: str | None, limite: int | None = None) -> str | None:
    if not texto:
        return None
    texto = " ".join(html.unescape(_TAG.sub(" ", texto)).split())
    if limite and len(texto) > limite:
        texto = texto[:limite].rsplit(" ", 1)[0] + "…"
    return texto or None


def normalizar_titulo(titulo: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", titulo).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^\w\s]", " ", sem_acento.casefold()).split())


def calcular_hash(titulo: str, fonte: str) -> str:
    return hashlib.sha256(f"{normalizar_titulo(titulo)}|{fonte}".encode()).hexdigest()


def interpretar_data(texto: str | None) -> datetime | None:
    """RFC 822 ou ISO 8601. Sem fuso -> horário de Brasília."""
    if not texto:
        return None
    dt = None
    try:
        dt = parsedate_to_datetime(texto)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(texto.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=FUSO_B3)
    return dt


def disponibilidade(publicado: datetime | None, agora: datetime) -> str:
    if publicado is None or publicado > agora:
        return para_iso_utc(agora)
    return para_iso_utc(publicado)


def _padroes_ativos(conn: sqlite3.Connection) -> list[tuple[str, re.Pattern, re.Pattern]]:
    padroes = []
    for r in conn.execute("SELECT ticker, nome, apelidos FROM ativos WHERE ativo = 1 AND tipo = 'acao'"):
        termos = [t for t in (r["apelidos"] or r["nome"]).split("|") if t]
        def compilar(lista):
            return re.compile(r"(?<!\w)(?:" + "|".join(re.escape(t) for t in lista) + r")(?!\w)")
        padroes.append((r["ticker"], compilar([r["ticker"]]), compilar(termos)))
    return padroes


def associar(texto: str, padroes) -> list[tuple[str, str]]:
    """[(ticker, metodo)] dos ativos citados no texto."""
    achados = []
    for ticker, por_ticker, por_nome in padroes:
        if por_ticker.search(texto):
            achados.append((ticker, "ticker_no_texto"))
        elif por_nome.search(texto):
            achados.append((ticker, "nome_no_texto"))
    return achados


def _gravar(conn, entradas, fonte: str, padroes, agora: datetime) -> int:
    coletado = para_iso_utc(agora)
    novos = 0
    with conn:
        for e in entradas:
            titulo = limpar_texto(e.get("title"))
            if not titulo:
                continue
            resumo = limpar_texto(e.get("summary"), TAMANHO_RESUMO)
            url = e.get("link") or None
            publicado = interpretar_data(e.get("published") or e.get("updated"))
            cur = conn.execute(
                "INSERT OR IGNORE INTO noticias (titulo, resumo, url, fonte, publicado_em, disponivel_em, coletado_em, hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (titulo, resumo, url, fonte, para_iso_utc(publicado) if publicado else None,
                 disponibilidade(publicado, agora), coletado, calcular_hash(titulo, fonte)),
            )
            if not cur.rowcount:  # já existia (mesmo hash ou mesma URL)
                continue
            novos += 1
            for ticker, metodo in associar(f"{titulo} {resumo or ''}", padroes):
                conn.execute("INSERT OR IGNORE INTO noticias_ativos (noticia_id, ticker, metodo) VALUES (?, ?, ?)",
                             (cur.lastrowid, ticker, metodo))
    return novos


def coletar(conn: sqlite3.Connection, desde: date | None = None, http: ClienteHTTP | None = None,
            feeds: list[dict] | None = None) -> int:
    http = http or ClienteHTTP()
    feeds = feeds if feeds is not None else carregar_feeds()
    padroes = _padroes_ativos(conn)
    agora = datetime.now(timezone.utc).replace(microsecond=0)
    novos, falhas = 0, []
    for feed in feeds:
        fonte = f"{FONTE_PREFIXO}_{feed['nome']}"
        try:
            documento = feedparser.parse(http.get_texto(feed["url"]))
            if documento.bozo and not documento.entries:
                raise ValueError(f"feed inválido: {documento.bozo_exception}")
            n = _gravar(conn, documento.entries, fonte, padroes, agora)
        except Exception as e:  # noqa: BLE001 - um feed não derruba os outros
            logger.warning("Feed %s falhou: %s", feed["nome"], e)
            falhas.append(feed["nome"])
            continue
        logger.info("Feed %s: %d notícias novas", feed["nome"], n)
        novos += n

    if falhas and len(falhas) == len(feeds):
        raise RuntimeError(f"todos os feeds falharam ({', '.join(falhas)})")
    if falhas:
        raise ColetaParcial(novos, f"feeds com falha: {', '.join(falhas)}")
    return novos
