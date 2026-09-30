import io
import zipfile
from datetime import date

import pytest

from src.coleta import cvm_dfp_itr
from src.db.tempo import hoje_brt
from tests.coleta.conftest import HTTPFalso

ANO = hoje_brt().year
CNPJ = "33.000.167/0001-01"

INDICE = ("CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;CATEG_DOC;ID_DOC;DT_RECEB;LINK_DOC\n"
          f"{CNPJ};{ANO}-03-31;1;PETROBRAS;009512;ITR;1;{ANO}-05-12;l\n"
          f"{CNPJ};{ANO}-03-31;2;PETROBRAS;009512;ITR;2;{ANO}-06-20;l\n"
          f"99.999.999/0001-99;{ANO}-03-31;1;OUTRA;001234;ITR;3;{ANO}-05-10;l\n")
CAB_DRE = ("CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;GRUPO_DFP;MOEDA;ESCALA_MOEDA;ORDEM_EXERC;"
           "DT_INI_EXERC;DT_FIM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;ST_CONTA_FIXA\n")
DRE = CAB_DRE + "".join([
    # como na CVM real: o índice lista v1 e v2, mas só a v2 (última) tem valores
    f"{CNPJ};{ANO}-03-31;2;P;009512;DRE;REAL;MIL;ÚLTIMO;{ANO}-01-01;{ANO}-03-31;3.11;Lucro Líquido;32761000.0;S\n",
    f"{CNPJ};{ANO}-03-31;2;P;009512;DRE;REAL;MIL;ÚLTIMO;{ANO}-01-01;{ANO}-03-31;3.11;Lucro Líquido;32761000.0;S\n",  # repetida
    f"{CNPJ};{ANO}-03-31;2;P;009512;DRE;REAL;MIL;PENÚLTIMO;{ANO-1}-01-01;{ANO-1}-03-31;3.11;Lucro Líquido;35331000.0;S\n",
    f"99.999.999/0001-99;{ANO}-03-31;1;O;001234;DRE;REAL;UNIDADE;ÚLTIMO;{ANO}-01-01;{ANO}-03-31;3.11;Lucro;5.0;S\n",
    f"{CNPJ};{ANO}-03-31;2;P;009512;DRE;REAL;MIL;ÚLTIMO;{ANO}-01-01;{ANO}-03-31;3.11.01.01;Detalhe;1.0;N\n",  # 4º nível: descartado
])
BPA = ("CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;GRUPO_DFP;MOEDA;ESCALA_MOEDA;ORDEM_EXERC;"
       "DT_FIM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;ST_CONTA_FIXA\n"
       f"{CNPJ};{ANO}-03-31;2;P;009512;BPA;REAL;UNIDADE;ÚLTIMO;{ANO}-03-31;1;Ativo Total;1000.5;S\n")
CAPITAL = ("CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;QT_ACAO_ORDIN_CAP_INTEGR;QT_ACAO_PREF_CAP_INTEGR;"
           "QT_ACAO_TOTAL_CAP_INTEGR;QT_ACAO_ORDIN_TESOURO;QT_ACAO_PREF_TESOURO;QT_ACAO_TOTAL_TESOURO\n"
           f"{CNPJ};{ANO}-03-31;2;P;7442231910;5602042788;13044274698;0;0;0\n")


def _zip_itr():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for nome, conteudo in {
            f"itr_cia_aberta_{ANO}.csv": INDICE,
            f"itr_cia_aberta_DRE_con_{ANO}.csv": DRE,
            f"itr_cia_aberta_BPA_con_{ANO}.csv": BPA,
            f"itr_cia_aberta_composicao_capital_{ANO}.csv": CAPITAL,
            f"itr_cia_aberta_DFC_MI_con_{ANO}.csv": DRE,  # fluxo de caixa: não é mais guardado
        }.items():
            z.writestr(nome, conteudo.encode("latin-1"))
    return buf.getvalue()


@pytest.fixture
def conn_cvm(conn, raw_tmp):
    with conn:
        conn.execute("UPDATE ativos SET codigo_cvm = '9512' WHERE ticker = 'PETR4'")
    return conn


def _http():
    return HTTPFalso({f"itr_cia_aberta_{ANO}.zip": _zip_itr()})


def test_coleta_demonstracoes(conn_cvm):
    novos = cvm_dfp_itr.coletar(conn_cvm, date(ANO, 1, 1), http=_http())
    assert novos == 1 + 1 + 6  # DRE + BPA + 6 colunas de capital (repetida descartada)

    lucro = [dict(r) for r in conn_cvm.execute(
        "SELECT * FROM demonstracoes WHERE demonstrativo = 'DRE' AND cd_conta = '3.11'")]
    assert len(lucro) == 1                                            # só a empresa acompanhada; só ÚLTIMO
    assert lucro[0]["versao"] == 2                                    # a versão com valores nos arquivos
    assert lucro[0]["valor"] == 32_761_000_000.0                      # escala MIL -> reais
    assert lucro[0]["disponivel_em"] == f"{ANO}-06-21T02:59:59+00:00" # entrega da v2, fim do dia BRT
    assert (lucro[0]["data_ini"], lucro[0]["consolidado"]) == (f"{ANO}-01-01", 1)

    ativo = conn_cvm.execute("SELECT valor, data_ini FROM demonstracoes WHERE demonstrativo = 'BPA'").fetchone()
    assert tuple(ativo) == (1000.5, None)                             # balanço não tem data_ini
    capital = conn_cvm.execute("SELECT valor FROM demonstracoes WHERE cd_conta = 'QT_ACAO_TOTAL_CAP_INTEGR'").fetchone()
    assert capital[0] == 13_044_274_698                               # capital mapeado por CNPJ


def test_versao_antiga_ja_guardada_e_preservada(conn_cvm):
    # a v1 foi coletada quando saiu; depois a CVM passa a publicar só a v2
    with conn_cvm:
        conn_cvm.execute(
            "INSERT INTO demonstracoes (codigo_cvm, tipo_doc, data_referencia, versao, demonstrativo, consolidado, "
            "data_ini, data_fim, cd_conta, ds_conta, valor, disponivel_em, coletado_em) VALUES "
            f"('9512', 'ITR', '{ANO}-03-31', 1, 'DRE', 1, '{ANO}-01-01', '{ANO}-03-31', '3.11', 'Lucro', 3.0e10, "
            f"'{ANO}-05-13T02:59:59+00:00', '{ANO}-05-13T02:59:59+00:00')")
    cvm_dfp_itr.coletar(conn_cvm, date(ANO, 1, 1), http=_http())
    versoes = [r[0] for r in conn_cvm.execute(
        "SELECT versao FROM demonstracoes WHERE cd_conta = '3.11' ORDER BY versao")]
    assert versoes == [1, 2]


def test_documento_ja_presente_e_pulado(conn_cvm):
    cvm_dfp_itr.coletar(conn_cvm, date(ANO, 1, 1), http=_http())
    assert cvm_dfp_itr.coletar(conn_cvm, date(ANO, 1, 1), http=_http()) == 0


def test_baixa_desde_o_ano_anterior(conn_cvm):
    http = _http()
    cvm_dfp_itr.coletar(conn_cvm, date(ANO, 6, 1), http=http)
    nomes = [u.rsplit("/", 1)[-1] for u in http.chamadas]
    assert f"dfp_cia_aberta_{ANO - 1}.zip" in nomes and f"itr_cia_aberta_{ANO - 1}.zip" in nomes
