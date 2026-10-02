from pathlib import Path

import pytest

from src.carteira.importar import importar, interpretar, ler_tabela, numero

EXEMPLO = Path(__file__).parent.parent / "dados" / "extrato_b3_exemplo.csv"  # anonimizado, formato da B3


def test_numeros_no_formato_brasileiro():
    assert numero("R$ 1.040,00") == 1040.0 and numero("30,5") == 30.5 and numero("30.5") == 30.5
    assert numero("") is None and numero(12) == 12.0


def test_extrato_da_b3_importa_e_aponta_o_que_nao_entendeu(conn):
    r = importar(conn, EXEMPLO.read_bytes(), EXEMPLO.name)
    assert r.formato == "b3_negociacao" and r.importadas == 4
    assert [m for _, m in r.nao_reconhecidas] == ["tipo não é compra nem venda: 'Transferência'",
                                                   "ticker não reconhecido: 'PETRC300'"]
    linhas = conn.execute("SELECT ticker, tipo, data, quantidade, preco FROM carteira_operacoes ORDER BY id").fetchall()
    assert [tuple(l) for l in linhas][:2] == [("PETR4", "compra", "2026-01-05", 100, 30.5),
                                              ("PETR4", "compra", "2026-01-05", 7, 30.5)]   # fracionário vira PETR4
    assert linhas[2]["preco"] == 1040.0


def test_reimportar_nao_duplica(conn):
    importar(conn, EXEMPLO.read_bytes(), EXEMPLO.name)
    r = importar(conn, EXEMPLO.read_bytes(), EXEMPLO.name)
    assert r.importadas == 0 and r.ja_existiam == 4


def test_planilha_simples_com_fills_identicos_e_produto_com_nome():
    csv = ("ativo,operacao,data,qtd,preco,corretagem\n"
           "VALE3 - VALE S.A.,C,2026-01-05,10,60.0,2.5\n"
           "VALE3,C,2026-01-05,10,60.0,0\n"
           "VALE3,C,2026-01-05,10,60.0,0\n").encode()
    ops, ruins, formato = interpretar(ler_tabela(csv, "x.csv"))
    assert formato == "planilha" and ruins == [] and len(ops) == 3
    assert ops[0]["custos"] == 2.5
    assert len({o["referencia"] for o in ops}) == 3             # dois fills idênticos continuam distintos


def test_sem_coluna_obrigatoria_explica():
    with pytest.raises(ValueError, match="colunas não encontradas: preco"):
        interpretar(ler_tabela(b"ticker;tipo;data;quantidade\nPETR4;C;05/01/2026;1\n", "x.csv"))
