from datetime import date

import pytest

from src.coleta import cvm_cadastro
from src.coleta.execucao import ColetaParcial
from src.db.ativos import sincronizar_ativos
from src.db.tempo import hoje_brt
from tests.coleta.conftest import HTTPFalso, zip_com

ANO = hoje_brt().year
CAB_FCA = ("CNPJ_Companhia;Data_Referencia;Versao;ID_Documento;Nome_Empresarial;Valor_Mobiliario;"
           "Sigla_Classe_Acao_Preferencial;Classe_Acao_Preferencial;Codigo_Negociacao;Composicao_BDR_Unit;"
           "Mercado;Sigla_Entidade_Administradora;Entidade_Administradora;Data_Inicio_Negociacao;"
           "Data_Fim_Negociacao;Segmento;Data_Inicio_Listagem;Data_Fim_Listagem\n")


def _fca(*linhas):
    corpo = CAB_FCA + "".join(
        f"{cnpj};{ref};1;1;EMPRESA;Ações;;;{tk};;Bolsa;B3;B3 S.A.;2000-01-01;{fim};;;\n"
        for cnpj, tk, ref, fim in linhas
    )
    return zip_com(f"fca_cia_aberta_valor_mobiliario_{ANO}.csv", corpo.encode("latin-1"))


CAD = ("CNPJ_CIA;DENOM_SOCIAL;SIT;CD_CVM\n"
       "33.000.167/0001-01;PETRÓLEO BRASILEIRO;ATIVO;9512\n"
       "33.000.167/0001-01;PETRÓLEO BRASILEIRO (antigo);CANCELADA;99999\n"
       "30.306.294/0001-45;BCO BTG PACTUAL;ATIVO;22616\n").encode("latin-1")


def _http(fca):
    return HTTPFalso({f"fca_cia_aberta_{ANO}.zip": fca, "cad_cia_aberta.csv": CAD})


@pytest.fixture
def conn_ativos(conn_vazia, raw_tmp):
    from src.db.migracoes import migrar
    migrar(conn_vazia)
    sincronizar_ativos(conn_vazia, [
        {"ticker": "PETR4", "nome": "Petrobras", "setor": None, "cnpj": None, "ativo": 1},
        {"ticker": "BPAC11", "nome": "BTG", "setor": None, "cnpj": None, "ativo": 1},
        {"ticker": "BOVA11", "nome": "ETF", "setor": None, "cnpj": None, "ativo": 1, "tipo": "benchmark"},
    ])
    return conn_vazia


def _cadastro(conn):
    return {r["ticker"]: (r["cnpj"], r["codigo_cvm"]) for r in conn.execute("SELECT * FROM ativos")}


def test_preenche_cnpj_e_codigo_inclusive_unit_pelo_radical(conn_ativos):
    fca = _fca(("33.000.167/0001-01", "PETR4", f"{ANO}-01-01", ""),
               ("30.306.294/0001-45", "BPAC3", f"{ANO}-01-01", ""),
               ("30.306.294/0001-45", "BPAC5", f"{ANO}-01-01", ""))
    assert cvm_cadastro.coletar(conn_ativos, date(2021, 1, 1), http=_http(fca)) == 2
    cad = _cadastro(conn_ativos)
    assert cad["PETR4"] == ("33.000.167/0001-01", "9512")  # registro ATIVO prevalece
    assert cad["BPAC11"] == ("30.306.294/0001-45", "22616")
    assert cad["BOVA11"] == (None, None)                   # benchmark fica de fora
    # segunda execução: nada muda
    assert cvm_cadastro.coletar(conn_ativos, date(2021, 1, 1), http=_http(fca)) == 0


def test_ticker_inexistente_gera_coleta_parcial(conn_ativos):
    fca = _fca(("33.000.167/0001-01", "PETR4", f"{ANO}-01-01", ""))  # BTG não aparece em nenhum FCA
    with pytest.raises(ColetaParcial, match="BPAC11") as e:
        cvm_cadastro.coletar(conn_ativos, date(2021, 1, 1), http=_http(fca))
    assert e.value.novos == 1


def test_ticker_com_negociacao_encerrada_ainda_e_mapeado(conn_ativos):
    # empresas que mudaram de código ou saíram da bolsa precisam de fundamentos no histórico
    fca = _fca(("33.000.167/0001-01", "PETR4", f"{ANO}-01-01", ""),
               ("30.306.294/0001-45", "BPAC3", f"{ANO}-01-01", "2020-01-01"))
    cvm_cadastro.coletar(conn_ativos, date(2021, 1, 1), http=_http(fca))
    assert _cadastro(conn_ativos)["BPAC11"] == ("30.306.294/0001-45", "22616")


def test_sem_fca_disponivel_e_falha(conn_ativos):
    with pytest.raises(RuntimeError, match="FCA"):
        cvm_cadastro.coletar(conn_ativos, date(2021, 1, 1), http=HTTPFalso({"cad_cia_aberta.csv": CAD}))


def test_usa_cnpj_do_csv_quando_fca_nao_resolve(conn_ativos):
    # BTG informa a unit como '000000' no FCA real
    with conn_ativos:
        conn_ativos.execute("UPDATE ativos SET cnpj = '30.306.294/0001-45' WHERE ticker = 'BPAC11'")
    fca = _fca(("33.000.167/0001-01", "PETR4", f"{ANO}-01-01", ""),
               ("30.306.294/0001-45", "000000", f"{ANO}-01-01", ""))
    cvm_cadastro.coletar(conn_ativos, date(2021, 1, 1), http=_http(fca))
    assert _cadastro(conn_ativos)["BPAC11"] == ("30.306.294/0001-45", "22616")


def test_cnpj_manual_resolve_fca_com_lixo(conn_ativos, tmp_path, monkeypatch):
    # CSN real: FCA traz '4030' no lugar do ticker
    arq = tmp_path / "cnpj.csv"
    arq.write_text("ticker,cnpj,referencia\nBPAC11,30.306.294/0001-45,teste\n", encoding="utf-8")
    monkeypatch.setattr(cvm_cadastro, "CNPJ_MANUAL", arq)
    fca = _fca(("33.000.167/0001-01", "PETR4", f"{ANO}-01-01", ""),
               ("30.306.294/0001-45", "4030", f"{ANO}-01-01", ""))
    cvm_cadastro.coletar(conn_ativos, date(2021, 1, 1), http=_http(fca))
    assert _cadastro(conn_ativos)["BPAC11"] == ("30.306.294/0001-45", "22616")


def test_cnpj_manual_exige_referencia(tmp_path):
    arq = tmp_path / "cnpj.csv"
    arq.write_text("ticker,cnpj,referencia\nCSNA3,33.042.730/0001-04,\n", encoding="utf-8")
    with pytest.raises(ValueError, match="sem referência"):
        cvm_cadastro.carregar_cnpj_manual(arq)


def test_cnpj_manual_do_projeto_e_valido():
    assert cvm_cadastro.carregar_cnpj_manual()["CSNA3"] == "33.042.730/0001-04"
