from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest

from src.coleta import intradiario
from src.ranking import gerar, provisorio
from tests.test_ranking import N_ACOES, conn_mercado  # noqa: F401 (fixture)


def _df_yahoo(precos: dict[str, list[tuple[str, float]]]) -> pd.DataFrame:
    """Imita yf.download(group_by='ticker'): colunas (símbolo, campo)."""
    partes = {}
    for simbolo, pontos in precos.items():
        idx = pd.DatetimeIndex([pd.Timestamp(t, tz="UTC") for t, _ in pontos])
        partes[simbolo] = pd.DataFrame({"Close": [p for _, p in pontos]}, index=idx)
    return pd.concat(partes, axis=1)


def test_pregao_em_andamento():
    assert intradiario.pregao_em_andamento(datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc))      # 12h BRT
    assert not intradiario.pregao_em_andamento(datetime(2026, 9, 30, 23, 0, tzinfo=timezone.utc))  # 20h BRT
    assert not intradiario.pregao_em_andamento(datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc))  # sábado


def test_coleta_cotacao_do_momento(conn_mercado):
    conn, dias = conn_mercado
    ultimo = conn.execute("SELECT fechamento FROM cotacoes WHERE ticker = 'AC003' ORDER BY data DESC LIMIT 1").fetchone()[0]

    def baixar(simbolos):
        dados = {s: [("2026-09-29 20:00", 1.0), ("2026-09-30 15:40", ultimo * 1.02)] for s in simbolos if s != "AC013.SA"}
        dados["^BVSP"] = [("2026-09-29 20:00", 180000.0), ("2026-09-30 15:40", 181800.0)]
        return _df_yahoo(dados)

    n = intradiario.coletar(conn, baixar)
    assert n == N_ACOES + 1      # 40 sintéticas - 1 sem dado + PETR4 (exceção manual da fixture) + IBOV
    linha = conn.execute("SELECT * FROM cotacao_atual WHERE ticker = 'AC003'").fetchone()
    assert linha["variacao_dia"] == pytest.approx(0.02)                     # contra o fechamento oficial da B3
    assert linha["horario_cotacao"] == "2026-09-30T15:40:00+00:00"
    ibov = conn.execute("SELECT variacao_dia FROM cotacao_atual WHERE ticker = 'IBOV'").fetchone()[0]
    assert ibov == pytest.approx(0.01)                                      # índice: anterior da própria fonte


def test_lote_com_erro_nao_para_os_outros(conn_mercado):
    conn, _ = conn_mercado
    def baixar(simbolos):
        raise ConnectionError("Yahoo fora")
    assert intradiario.coletar(conn, baixar) == 0


def test_ranking_provisorio(conn_mercado, tmp_path):
    conn, dias = conn_mercado
    oficial = gerar.ranking_da_data(conn, dias[-1], ["x"], salvar_em=tmp_path)
    with conn:  # cotação do momento = fechamento anterior + 1% para todos
        conn.execute("INSERT INTO cotacao_atual SELECT ticker, fechamento * 1.01, fechamento, 0.01, "
                     "'2026-09-30T15:40:00+00:00', 'teste', '2026-09-30T15:41:00+00:00' FROM cotacoes "
                     "WHERE data = ?", (dias[-1].isoformat(),))
    carregado = provisorio.carregar_ultimo_modelo(tmp_path)
    hoje = date(2026, 9, 30)
    r = provisorio.gerar_provisorio(conn, hoje, ["x"], carregado)
    # 'x' não depende de preço: o provisório repete a ordem do último oficial
    assert list(r.ranking["ticker"]) == list(oficial.ranking["ticker"])
    linha = conn.execute("SELECT data, disponivel_em FROM ranking WHERE versao_modelo = ? LIMIT 1", (provisorio.VERSAO,)).fetchone()
    assert linha["data"] == "2026-09-30" and not linha["disponivel_em"].endswith("22:00:00+00:00")  # não é o corte das 19h
