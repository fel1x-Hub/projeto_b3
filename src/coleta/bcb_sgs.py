"""Séries macro do Banco Central (SGS), com data de divulgação do IPCA pelo IBGE.

API: https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados
     ?formato=json&dataInicial=DD/MM/AAAA&dataFinal=DD/MM/AAAA
- Consultas limitadas a 10 anos por requisição (usamos janelas de 5).
- Período sem dados responde 404 ("Value(s) not found") -> lista vazia.

`disponivel_em`:
- Séries diárias: fim do próprio dia (23:59:59 BRT), conservador.
  A Selic meta (432) vem preenchida com datas FUTURAS até a próxima reunião do
  Copom; essas linhas são descartadas (ainda não aconteceram).
- IPCA (mensal): data de divulgação do IBGE às 09:00 BRT, obtida em
  servicodados.ibge.gov.br/api/v3/agregados/1737/periodos (campo `modificacao`).
  Sem essa data, usa o dia 15 do mês seguinte (toda divulgação histórica foi
  antes disso) e registra aviso.
"""

import logging
import sqlite3
import time as _time
from datetime import date, datetime, time, timedelta

from src.coleta.cliente_http import ClienteHTTP, NaoEncontrado
from src.coleta.execucao import ColetaParcial
from src.coleta.persistencia import salvar
from src.db.tempo import hoje_brt, iso_brt

logger = logging.getLogger(__name__)

FONTE = "bcb_sgs"
URL_SGS = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"
URL_IBGE_IPCA = "https://servicodados.ibge.gov.br/api/v3/agregados/1737/periodos"
CHAVES = ["serie", "data", "fonte"]
JANELA = timedelta(days=5 * 365)

# nome interno -> (código SGS, periodicidade)
SERIES = {
    "selic_meta": (432, "diaria"),   # % a.a., meta definida pelo Copom
    "cdi": (12, "diaria"),           # % a.d.
    "ptax_venda": (1, "diaria"),     # R$/US$
    "ipca": (433, "mensal"),         # variação % no mês
}


def _data_br(texto: str) -> date:
    return datetime.strptime(texto, "%d/%m/%Y").date()


class RespostaInvalida(Exception):
    """O SGS às vezes responde HTTP 200 com página HTML ou objeto de erro."""


def _consultar(http, codigo: int, params: dict, tentativas: int, dormir) -> list[dict]:
    for tentativa in range(tentativas):
        try:
            dados = http.get_json(URL_SGS.format(codigo=codigo), params=params)
        except NaoEncontrado:
            return []  # período sem dados
        except ValueError as e:  # HTML no lugar de JSON (JSONDecodeError herda de ValueError)
            dados = f"não é JSON: {e}"
        if isinstance(dados, list):
            return dados
        if tentativa < tentativas - 1:
            espera = 2.0 * 2 ** tentativa
            logger.warning("SGS %d respondeu fora do formato (%.80s); nova tentativa em %.0fs", codigo, dados, espera)
            dormir(espera)
    raise RespostaInvalida(f"SGS {codigo} não devolveu lista após {tentativas} tentativas: {str(dados)[:200]}")


def buscar_sgs(http, codigo: int, inicio: date, fim: date, tentativas: int = 4, dormir=_time.sleep) -> list[tuple[date, float]]:
    pontos = []
    ini = inicio
    while ini <= fim:
        fim_janela = min(fim, ini + JANELA)
        params = {"formato": "json", "dataInicial": f"{ini:%d/%m/%Y}", "dataFinal": f"{fim_janela:%d/%m/%Y}"}
        dados = _consultar(http, codigo, params, tentativas, dormir)
        pontos += [(_data_br(d["data"]), float(d["valor"])) for d in dados if d.get("valor") not in (None, "")]
        ini = fim_janela + timedelta(days=1)
    return pontos


def datas_divulgacao_ipca(http) -> dict[str, date]:
    """{'2026-03': data de divulgação}. Vazio se o IBGE estiver fora do ar."""
    try:
        periodos = http.get_json(URL_IBGE_IPCA)
    except Exception as e:  # noqa: BLE001 - há fallback conservador
        logger.warning("IBGE indisponível (%s); usando dia 15 do mês seguinte para o IPCA", e)
        return {}
    return {f"{p['id'][:4]}-{p['id'][4:6]}": _data_br(p["modificacao"]) for p in periodos}


def _divulgacao_ipca(referencia: date, datas: dict[str, date]) -> datetime | str:
    proximo_mes = (referencia.replace(day=28) + timedelta(days=4)).replace(day=1)
    divulgacao = datas.get(f"{referencia:%Y-%m}")
    if divulgacao is None or divulgacao < proximo_mes:
        logger.warning("IPCA %s sem data de divulgação válida; usando dia 15 do mês seguinte", f"{referencia:%Y-%m}")
        divulgacao = proximo_mes.replace(day=15)
    return iso_brt(divulgacao, time(9, 0))


def _coletar_serie(conn, http, serie: str, codigo: int, periodicidade: str,
                   desde: date, hoje: date, datas_ipca: dict, dormir) -> int:
    ultimo = conn.execute(
        "SELECT MAX(data) FROM macro WHERE serie = ? AND fonte = ?", (serie, FONTE)
    ).fetchone()[0]
    inicio = max(desde, date.fromisoformat(ultimo) + timedelta(days=1)) if ultimo else desde
    if inicio > hoje:
        return 0

    pontos = [(d, v) for d, v in buscar_sgs(http, codigo, inicio, hoje, dormir=dormir) if d <= hoje]
    if periodicidade == "mensal" and pontos and not datas_ipca:
        datas_ipca.update(datas_divulgacao_ipca(http))

    registros = []
    for dia, valor in pontos:
        if periodicidade == "mensal":
            disponivel = _divulgacao_ipca(dia, datas_ipca)
        else:
            disponivel = iso_brt(dia, time(23, 59, 59))
        registros.append({"serie": serie, "data": dia.isoformat(), "valor": valor,
                          "fonte": FONTE, "disponivel_em": disponivel})
    novos = salvar(conn, "macro", CHAVES, registros, fonte=FONTE).novos
    logger.info("SGS %s (%d): %d novos", serie, codigo, novos)
    return novos


def coletar(conn: sqlite3.Connection, desde: date, http: ClienteHTTP | None = None, dormir=_time.sleep) -> int:
    http = http or ClienteHTTP()
    hoje = hoje_brt()
    datas_ipca: dict[str, date] = {}
    novos, falhas = 0, []

    for serie, (codigo, periodicidade) in SERIES.items():
        try:  # cada série é independente: uma falha não impede as outras
            novos += _coletar_serie(conn, http, serie, codigo, periodicidade, desde, hoje, datas_ipca, dormir)
        except Exception as e:  # noqa: BLE001
            logger.warning("SGS %s falhou: %s", serie, e)
            falhas.append(serie)

    if falhas and len(falhas) == len(SERIES):
        raise RuntimeError(f"todas as séries do SGS falharam ({', '.join(falhas)})")
    if falhas:
        raise ColetaParcial(novos, f"séries não coletadas: {', '.join(falhas)}")
    return novos
