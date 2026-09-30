from datetime import date

import pytest

from src.coleta import b3_cotahist
from src.coleta.b3_cotahist import Arquivo, ler_registros, planejar
from src.coleta.execucao import ColetaParcial
from src.db.ativos import sincronizar_ativos
from tests.coleta.conftest import AMOSTRAS, HTTPFalso, zip_com

HOJE = date(2026, 9, 29)  # terça-feira
AMOSTRA = (AMOSTRAS / "COTAHIST_D25092026.TXT").read_bytes().decode("latin-1")


def _linha(ticker):
    return next(l for l in AMOSTRA.splitlines(keepends=True) if l[12:24].strip() == ticker)


def _arquivo(*linhas):
    """ZIP de COTAHIST com header, as linhas dadas e trailer."""
    partes = AMOSTRA.splitlines(keepends=True)
    return zip_com("COTAHIST.TXT", (partes[0] + "".join(linhas) + partes[-1]).encode("latin-1"))


def _em(linha, dia: date):
    return linha[:2] + f"{dia:%Y%m%d}" + linha[10:]


def _nomes(arquivos):
    return [a.nome for a in arquivos]


def test_planejar_usa_ano_mes_e_dia():
    nomes = _nomes(planejar(date(2023, 11, 10), HOJE))
    assert nomes[:4] == ["COTAHIST_M112023.ZIP", "COTAHIST_M122023.ZIP", "COTAHIST_A2024.ZIP", "COTAHIST_A2025.ZIP"]
    assert "COTAHIST_M082026.ZIP" in nomes and "COTAHIST_M092026.ZIP" not in nomes
    diarios = [n for n in nomes if "_D" in n]
    assert diarios[0] == "COTAHIST_D01092026.ZIP" and diarios[-1] == "COTAHIST_D29092026.ZIP"
    assert "COTAHIST_D26092026.ZIP" not in nomes  # sábado


def test_planejar_ano_inteiro_quando_comeca_em_janeiro():
    assert _nomes(planejar(date(2021, 1, 4), date(2022, 1, 3)))[:1] == ["COTAHIST_A2021.ZIP"]


def test_planejar_nada_quando_em_dia():
    assert planejar(date(2026, 9, 30), HOJE) == []


def test_ler_registros_da_amostra_real(tmp_path):
    caminho = tmp_path / "d.zip"
    caminho.write_bytes(_arquivo(*AMOSTRA.splitlines(keepends=True)[1:-1]))
    regs = {r["ticker"]: r for r in ler_registros(caminho, {"PETR4", "BOVA11"}, date(2026, 1, 1), automaticos=False)}
    assert set(regs) == {"PETR4", "BOVA11"}  # VALE3 fora da lista; PETR4F é fracionário
    p = regs["PETR4"]
    assert (p["data"], p["abertura"], p["maxima"], p["minima"], p["fechamento"], p["volume"]) == \
        ("2026-09-25", 48.80, 48.87, 47.92, 47.99, 34440400)
    assert p["disponivel_em"] == "2026-09-25T22:00:00+00:00"  # 19h BRT
    assert regs["BOVA11"]["fechamento"] == 180.82


def test_ler_registros_respeita_fatcot_mercado_e_data(tmp_path):
    petr = _linha("PETR4")
    por_lote = petr[:210] + "0001000" + petr[217:]           # cotação por lote de mil
    fracionario = petr[:24] + "020" + petr[27:]
    antiga = _em(petr, date(2025, 12, 31))
    caminho = tmp_path / "d.zip"
    caminho.write_bytes(_arquivo(por_lote, fracionario, antiga))
    regs = ler_registros(caminho, {"PETR4"}, date(2026, 1, 1))
    assert len(regs) == 1 and regs[0]["fechamento"] == pytest.approx(0.04799)


@pytest.fixture
def conn_b3(conn, raw_tmp, monkeypatch):
    monkeypatch.setattr(b3_cotahist, "hoje_brt", lambda: HOJE)
    sincronizar_ativos(conn, [
        {"ticker": t, "nome": t, "setor": None, "cnpj": None, "ativo": 1}
        for t in ("PETR4", "VALE3", "BOVA11")
    ])
    return conn


def _http_semana():
    petr, vale, bova = _linha("PETR4"), _linha("VALE3"), _linha("BOVA11")
    dia24 = date(2026, 9, 24)
    return HTTPFalso({
        "COTAHIST_D24092026": _arquivo(_em(petr, dia24), _em(vale, dia24), _em(bova, dia24)),
        "COTAHIST_D25092026": _arquivo(petr, vale, bova),
        # 28 e 29 ainda não publicados -> 404
    })


def test_coleta_e_incremental(conn_b3):
    http = _http_semana()
    assert b3_cotahist.coletar(conn_b3, date(2026, 9, 24), http=http) == 6
    # segunda execução: só tenta os dias que faltam (28 e 29) e não traz nada
    http2 = _http_semana()
    assert b3_cotahist.coletar(conn_b3, date(2026, 9, 24), http=http2) == 0
    assert [u.rsplit("/", 1)[-1] for u in http2.chamadas] == ["COTAHIST_D28092026.ZIP", "COTAHIST_D29092026.ZIP"]


def test_mes_inexistente_desce_para_diarios(conn_b3):
    petr, vale, bova = _linha("PETR4"), _linha("VALE3"), _linha("BOVA11")
    dia = date(2026, 8, 31)
    http = HTTPFalso({"COTAHIST_D31082026": _arquivo(_em(petr, dia), _em(vale, dia), _em(bova, dia))})
    b3_cotahist.coletar(conn_b3, date(2026, 8, 31), http=http)
    nomes = [u.rsplit("/", 1)[-1] for u in http.chamadas]
    assert nomes[0] == "COTAHIST_M082026.ZIP" and "COTAHIST_D31082026.ZIP" in nomes
    assert conn_b3.execute("SELECT COUNT(*) FROM cotacoes WHERE data = '2026-08-31'").fetchone()[0] == 3


def test_ticker_sem_cotacao_e_coleta_parcial(conn_b3):
    sincronizar_ativos(conn_b3, [
        {"ticker": t, "nome": t, "setor": None, "cnpj": None, "ativo": 1}
        for t in ("PETR4", "VALE3", "BOVA11", "XPTO3")
    ])
    with pytest.raises(ColetaParcial, match="XPTO3") as e:
        b3_cotahist.coletar(conn_b3, date(2026, 9, 24), http=_http_semana())
    assert e.value.novos == 6


def test_universo_automatico_detecta_acoes_e_respeita_excecoes(conn_vazia, raw_tmp, monkeypatch):
    from src.db.migracoes import migrar
    migrar(conn_vazia)
    monkeypatch.setattr(b3_cotahist, "hoje_brt", lambda: date(2026, 9, 25))
    sincronizar_ativos(conn_vazia, [
        {"ticker": "BOVA11", "nome": "ETF", "setor": None, "cnpj": None, "ativo": 1, "tipo": "benchmark"},
        {"ticker": "VALE3", "nome": "Vale", "setor": None, "cnpj": None, "ativo": 0},  # excluída à mão
    ])
    http = HTTPFalso({"COTAHIST_D25092026": _arquivo(*AMOSTRA.splitlines(keepends=True)[1:-1])})
    assert b3_cotahist.coletar(conn_vazia, date(2026, 9, 25), http=http) == 2
    ativos = {r["ticker"]: (r["origem"], r["nome"]) for r in conn_vazia.execute("SELECT * FROM ativos")}
    assert ativos["PETR4"] == ("auto", "PETROBRAS")          # ação detectada e cadastrada sozinha
    cotados = {r[0] for r in conn_vazia.execute("SELECT ticker FROM cotacoes")}
    assert cotados == {"PETR4", "BOVA11"}                     # ETF só por ser exceção manual; VALE3 excluída


def test_eh_acao_filtra_especie_e_bdi():
    petr, bova = _linha("PETR4"), _linha("BOVA11")
    assert b3_cotahist.eh_acao(petr)
    assert not b3_cotahist.eh_acao(bova)                                  # ETF (BDI 14)
    bdr = petr[:39] + "DRN       " + petr[49:]
    assert not b3_cotahist.eh_acao(bdr)                                    # BDR
    unit = petr[:39] + "UNT     N2" + petr[49:]
    assert b3_cotahist.eh_acao(unit)


def test_arquivo_anual_tem_nome_certo():
    assert Arquivo("A", date(2025, 1, 1), date(2025, 12, 31)).nome == "COTAHIST_A2025.ZIP"
