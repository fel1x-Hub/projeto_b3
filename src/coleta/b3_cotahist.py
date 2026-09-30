"""Cotações diárias pelo arquivo oficial da B3 (Séries Históricas / COTAHIST).

Arquivos (ZIP com TXT de largura fixa, 245 caracteres por registro):
    COTAHIST_A2025.ZIP     ano inteiro
    COTAHIST_M082026.ZIP   um mês
    COTAHIST_D25092026.ZIP um pregão (publicado na noite do próprio dia)
Layout: https://www.b3.com.br/data/files/33/67/B9/50/D84057102C784E47AC094EA8/SeriesHistoricas_Layout.pdf

Preços são BRUTOS (sem ajuste por proventos); o ajuste é feito na etapa 3 com
a tabela `proventos`. Para cada intervalo faltante usa o maior arquivo que faz
sentido (ano > mês > dia); se um arquivo ainda não existe (404), desce para o
nível menor. Dia sem arquivo = feriado ou pregão ainda não publicado.
"""

import io
import logging
import sqlite3
import zipfile
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, time, timedelta
from pathlib import Path

from config import settings
from src.coleta.cliente_http import ClienteHTTP, NaoEncontrado
from src.coleta.execucao import ColetaParcial
from src.coleta.persistencia import salvar
from src.db.ativos import registrar_automaticos
from src.db.tempo import hoje_brt, iso_brt

logger = logging.getLogger(__name__)

FONTE = "b3_cotahist"
URL_BASE = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist"
HORA_DISPONIVEL = time(19, 0)  # fechamento (inclui call de fechamento) com folga
MERCADO_A_VISTA = "010"
CHAVES = ["ticker", "data", "fonte"]


@dataclass(frozen=True)
class Arquivo:
    nivel: str  # 'A', 'M' ou 'D'
    inicio: date
    fim: date

    @property
    def nome(self) -> str:
        if self.nivel == "A":
            return f"COTAHIST_A{self.inicio:%Y}.ZIP"
        if self.nivel == "M":
            return f"COTAHIST_M{self.inicio:%m%Y}.ZIP"
        return f"COTAHIST_D{self.inicio:%d%m%Y}.ZIP"


def _mes(ano: int, mes: int) -> Arquivo:
    return Arquivo("M", date(ano, mes, 1), date(ano, mes, monthrange(ano, mes)[1]))


def _dias_uteis(inicio: date, fim: date) -> list[Arquivo]:
    dias, d = [], inicio
    while d <= fim:
        if d.weekday() < 5:
            dias.append(Arquivo("D", d, d))
        d += timedelta(days=1)
    return dias


def planejar(inicio: date, hoje: date) -> list[Arquivo]:
    """Arquivos para cobrir [inicio, hoje], preferindo os maiores.

    - Ano já encerrado, precisando dele desde janeiro: arquivo anual.
    - Mês já encerrado: arquivo mensal.
    - Mês corrente: arquivos diários.
    """
    if inicio > hoje:
        return []
    arquivos: list[Arquivo] = []
    for ano in range(inicio.year, hoje.year + 1):
        if ano < hoje.year and inicio <= date(ano, 1, 31):
            arquivos.append(Arquivo("A", date(ano, 1, 1), date(ano, 12, 31)))
            continue
        mes_ini = inicio.month if ano == inicio.year else 1
        mes_fim = 12 if ano < hoje.year else hoje.month - 1
        arquivos += [_mes(ano, m) for m in range(mes_ini, mes_fim + 1)]
    corrente = date(hoje.year, hoje.month, 1)
    arquivos += _dias_uteis(max(inicio, corrente), hoje)
    return arquivos


def _subdividir(arq: Arquivo) -> list[Arquivo]:
    """Quando um arquivo ainda não existe (404), cobre o mesmo período com menores."""
    if arq.nivel == "A":
        return [_mes(arq.inicio.year, m) for m in range(1, 13)]
    if arq.nivel == "M":
        return _dias_uteis(arq.inicio, arq.fim)
    return []


def eh_acao(linha: str) -> bool:
    """Ação ou unit de lote padrão: código BDI 02 e espécie ON, PN(A/B...) ou UNT.
    Ficam de fora FIIs (BDI 12), ETFs (BDI 14), BDRs, direitos e recibos."""
    return linha[10:12] == "02" and linha[39:49].lstrip().startswith(("ON", "PN", "UNT"))


def ler_registros(caminho_zip: Path, tickers: set[str], desde: date, automaticos: bool = True,
                  excluidos: frozenset[str] = frozenset(), detectados: dict | None = None) -> list[dict]:
    """Extrai as linhas de mercado à vista a partir de `desde`: dos `tickers`
    pedidos e, se `automaticos`, de toda ação/unit em lote padrão (menos os
    `excluidos`). Papéis automáticos encontrados vão para `detectados`
    ({ticker: nome resumido})."""
    registros = []
    with zipfile.ZipFile(caminho_zip) as z:
        with z.open(z.namelist()[0]) as bruto:
            for linha in io.TextIOWrapper(bruto, encoding="latin-1"):
                if linha[:2] != "01" or linha[24:27] != MERCADO_A_VISTA:
                    continue
                ticker = linha[12:24].strip()
                if ticker in excluidos:
                    continue
                if ticker not in tickers:
                    if not (automaticos and eh_acao(linha)):
                        continue
                    if detectados is not None:
                        detectados.setdefault(ticker, linha[27:39].strip())
                dia = date(int(linha[2:6]), int(linha[6:8]), int(linha[8:10]))
                if dia < desde:
                    continue
                fator = int(linha[210:217]) or 1  # cotação por lote de FATCOT ações

                def preco(ini: int, fim: int) -> float:
                    return int(linha[ini:fim]) / 100 / fator

                registros.append({
                    "ticker": ticker,
                    "data": dia.isoformat(),
                    "abertura": preco(56, 69),
                    "maxima": preco(69, 82),
                    "minima": preco(82, 95),
                    "fechamento": preco(108, 121),
                    "volume": int(linha[152:170]),
                    "fonte": FONTE,
                    "disponivel_em": iso_brt(dia, HORA_DISPONIVEL),
                })
    return registros


def _inicio_incremental(conn: sqlite3.Connection, tickers: list[str], desde: date) -> date:
    """Primeiro dia que falta para algum ticker (ticker sem dados começa em `desde`)."""
    ultimos = dict(conn.execute(
        "SELECT ticker, MAX(data) FROM cotacoes WHERE fonte = ? GROUP BY ticker", (FONTE,)
    ).fetchall())
    inicios = [
        max(desde, date.fromisoformat(ultimos[t]) + timedelta(days=1)) if ultimos.get(t) else desde
        for t in tickers
    ]
    return min(inicios)


def _inicio(conn: sqlite3.Connection, manuais: list[str], desde: date) -> date:
    """Primeiro dia a coletar.
    - Primeira coleta do universo automático (nenhum papel 'auto' ainda):
      reprocessa desde `desde` (os arquivos antigos já estão em cache).
    - Depois: dia seguinte ao último pregão salvo, ou antes, se uma exceção
      manual nova ainda não tiver dados."""
    if not conn.execute("SELECT 1 FROM ativos WHERE origem = 'auto' LIMIT 1").fetchone():
        return desde
    ultimo = conn.execute("SELECT MAX(data) FROM cotacoes WHERE fonte = ?", (FONTE,)).fetchone()[0]
    inicio = max(desde, date.fromisoformat(ultimo) + timedelta(days=1)) if ultimo else desde
    return min([inicio, _inicio_incremental(conn, manuais, desde)] if manuais else [inicio])


def coletar(conn: sqlite3.Connection, desde: date, http: ClienteHTTP | None = None,
            automaticos: bool = True) -> int:
    """Coleta cotações de todas as ações/units da B3 (universo automático) e
    das exceções manuais do ativos.csv (ex.: BOVA11). Papéis novos são
    cadastrados na tabela `ativos` com origem 'auto'."""
    http = http or ClienteHTTP()
    tickers = [r[0] for r in conn.execute(
        "SELECT ticker FROM ativos WHERE ativo = 1 AND origem = 'manual' ORDER BY ticker")]
    excluidos = frozenset(r[0] for r in conn.execute("SELECT ticker FROM ativos WHERE ativo = 0"))
    if not tickers and not automaticos:
        return 0
    inicio = _inicio(conn, tickers, desde) if automaticos else _inicio_incremental(conn, tickers, desde)
    fila = planejar(inicio, hoje_brt())
    logger.info("B3: %d arquivo(s) a partir de %s", len(fila), inicio)

    novos = 0
    while fila:
        arq = fila.pop(0)
        try:
            caminho = http.baixar_arquivo(f"{URL_BASE}/{arq.nome}", settings.RAW_DIR / "b3" / arq.nome)
        except NaoEncontrado:
            menores = _subdividir(arq)
            if menores:
                logger.info("%s ainda não existe; usando arquivos menores", arq.nome)
            else:
                logger.debug("%s não existe (feriado ou ainda não publicado)", arq.nome)
            fila = menores + fila
            continue
        detectados: dict[str, str] = {}
        registros = ler_registros(caminho, set(tickers), inicio, automaticos, excluidos, detectados)
        registrar_automaticos(conn, detectados)  # antes de salvar: cotacoes tem FK para ativos
        novos += salvar(conn, "cotacoes", CHAVES, registros, fonte=FONTE).novos
        logger.info("%s: %d linhas lidas", arq.nome, len(registros))

    sem_dados = [r[0] for r in conn.execute(
        f"SELECT ticker FROM ativos WHERE ativo = 1 AND origem = 'manual' AND ticker NOT IN "
        f"(SELECT DISTINCT ticker FROM cotacoes WHERE fonte = ?)", (FONTE,)
    )]
    if sem_dados:
        raise ColetaParcial(novos, f"tickers sem nenhuma cotação na B3: {', '.join(sem_dados)}")
    return novos
