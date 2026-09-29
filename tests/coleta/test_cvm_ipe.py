from datetime import date

import pytest

from src.coleta import cvm_ipe
from src.db.tempo import hoje_brt
from tests.coleta.conftest import HTTPFalso, zip_com

ANO = hoje_brt().year
CAB = ("CNPJ_Companhia;Nome_Companhia;Codigo_CVM;Data_Referencia;Categoria;Tipo;Especie;Assunto;"
       "Data_Entrega;Tipo_Apresentacao;Protocolo_Entrega;Versao;Link_Download\n")


def _linha(codigo, categoria, entrega, protocolo, versao=1, assunto="Assunto", ref=None, seq=1):
    return (f"33.000.167/0001-01;PETROBRAS;{codigo};{entrega if ref is None else ref};{categoria};;;{assunto};"
            f"{entrega};AP - Apresentação;{protocolo};{versao};"
            f"https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx?numSequencia={seq}&numVersao={versao}\n")


def _zip(*linhas):
    return zip_com(f"ipe_cia_aberta_{ANO}.csv", (CAB + "".join(linhas)).encode("latin-1"))


@pytest.fixture
def conn_cvm(conn, raw_tmp):
    with conn:
        conn.execute("UPDATE ativos SET codigo_cvm = '9512' WHERE ticker = 'PETR4'")
    return conn


ARQUIVO = _zip(
    _linha("9512", "Fato Relevante", f"{ANO}-01-28", "P1", assunto="Petrobras aumenta Reservas Provadas"),
    _linha("9512", "Fato Relevante", f"{ANO}-01-30", "P1", versao=2),          # reapresentação
    _linha("9512", "Assembleia", f"{ANO}-01-28", "P2"),                         # categoria ignorada
    _linha("4170", "Fato Relevante", f"{ANO}-01-28", "P3"),                     # empresa não acompanhada
    _linha("009512", "Comunicado ao Mercado", f"{ANO}-02-10", "P4", ref=""),    # código com zeros, sem referência
)


def test_coleta_documentos(conn_cvm):
    http = HTTPFalso({f"ipe_cia_aberta_{ANO}.zip": ARQUIVO})
    assert cvm_ipe.coletar(conn_cvm, date(ANO, 1, 1), http=http) == 3
    docs = {r["id_externo"]: dict(r) for r in conn_cvm.execute("SELECT * FROM documentos")}
    assert set(docs) == {"P1-1-v1", "P1-1-v2", "P4-1-v1"}
    fr = docs["P1-1-v1"]
    assert (fr["tipo"], fr["ticker"], fr["assunto"]) == ("fato_relevante", "PETR4", "Petrobras aumenta Reservas Provadas")
    assert fr["disponivel_em"] == f"{ANO}-01-29T02:59:59+00:00"  # fim do dia da entrega (BRT)
    assert docs["P4-1-v1"]["tipo"] == "comunicado" and docs["P4-1-v1"]["data_referencia"] is None
    # segunda execução não duplica
    assert cvm_ipe.coletar(conn_cvm, date(ANO, 1, 1), http=HTTPFalso({f"ipe_cia_aberta_{ANO}.zip": ARQUIVO})) == 0


def test_respeita_desde(conn_cvm):
    http = HTTPFalso({f"ipe_cia_aberta_{ANO}.zip": ARQUIVO})
    assert cvm_ipe.coletar(conn_cvm, date(ANO, 2, 1), http=http) == 1


def test_sem_codigo_cvm_nao_coleta(conn, raw_tmp):
    assert cvm_ipe.coletar(conn, date(ANO, 1, 1), http=HTTPFalso({})) == 0


def test_mesmo_protocolo_com_varios_documentos(conn_cvm):
    # ex. real: release em português e em inglês entregues no mesmo protocolo
    arquivo = _zip(
        _linha("9512", "Dados Econômico-Financeiros", f"{ANO}-02-10", "P5", assunto="Release 4T25", seq=10),
        _linha("9512", "Dados Econômico-Financeiros", f"{ANO}-02-10", "P5", assunto="Release 4T25 (inglês)", seq=11),
        _linha("9512", "Dados Econômico-Financeiros", f"{ANO}-02-10", "P5", assunto="Release 4T25 (inglês)", seq=11),  # linha repetida
    )
    for _ in range(2):
        cvm_ipe.coletar(conn_cvm, date(ANO, 1, 1), http=HTTPFalso({f"ipe_cia_aberta_{ANO}.zip": arquivo}))
    assuntos = sorted(r[0] for r in conn_cvm.execute("SELECT assunto FROM documentos"))
    assert assuntos == ["Release 4T25", "Release 4T25 (inglês)"]
    assert conn_cvm.execute("SELECT COUNT(*) FROM revisoes").fetchone()[0] == 0
