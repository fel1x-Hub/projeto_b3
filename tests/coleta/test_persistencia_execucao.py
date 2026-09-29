import json
from datetime import date

from src.coleta.execucao import ColetaParcial, executar
from src.coleta.persistencia import salvar
from tests.conftest import TS

CHAVES = ["serie", "data", "fonte"]


def _macro(valor, data="2026-01-02"):
    return {"serie": "ipca", "data": data, "valor": valor, "fonte": "bcb",
            "disponivel_em": TS, "coletado_em": TS}


def test_insere_ignora_iguais_e_registra_revisao(conn):
    r = salvar(conn, "macro", CHAVES, [_macro(0.5), _macro(0.3, "2026-02-01")], fonte="bcb")
    assert (r.novos, r.revisados) == (2, 0)

    r = salvar(conn, "macro", CHAVES, [_macro(0.5), _macro(0.3, "2026-02-01")], fonte="bcb")
    assert (r.novos, r.revisados) == (0, 0)

    # fonte corrigiu o valor de janeiro
    r = salvar(conn, "macro", CHAVES, [_macro(0.52)], fonte="bcb")
    assert (r.novos, r.revisados) == (0, 1)
    assert conn.execute("SELECT valor FROM macro WHERE data = '2026-01-02'").fetchone()[0] == 0.52
    rev = conn.execute("SELECT * FROM revisoes").fetchone()
    assert rev["campo"] == "valor" and rev["valor_antigo"] == "0.5" and rev["valor_novo"] == "0.52"
    assert json.loads(rev["chave_registro"]) == {"serie": "ipca", "data": "2026-01-02", "fonte": "bcb"}


def test_coletado_em_nao_gera_revisao(conn):
    salvar(conn, "macro", CHAVES, [_macro(0.5)])
    r = salvar(conn, "macro", CHAVES, [{**_macro(0.5), "coletado_em": "2026-05-05T00:00:00+00:00"}])
    assert r.revisados == 0
    assert conn.execute("SELECT COUNT(*) FROM revisoes").fetchone()[0] == 0


def test_chave_com_null(conn):
    linha = {"codigo_cvm": "9512", "tipo_doc": "DFP", "data_referencia": "2025-12-31", "versao": 1,
             "demonstrativo": "BPA", "consolidado": 1, "data_ini": None, "data_fim": "2025-12-31",
             "cd_conta": "1", "ds_conta": "Ativo Total", "valor": 10.0, "disponivel_em": TS}
    chaves = ["codigo_cvm", "tipo_doc", "data_referencia", "versao", "demonstrativo",
              "consolidado", "cd_conta", "data_ini", "data_fim"]
    assert salvar(conn, "demonstracoes", chaves, [linha]).novos == 1
    assert salvar(conn, "demonstracoes", chaves, [linha]).novos == 0


def _registros(conn):
    return [dict(r) for r in conn.execute("SELECT fonte, status, registros_novos, erro FROM execucoes_coleta")]


def test_execucao_sucesso_falha_e_parcial_isoladas(conn):
    def ok(conn, desde):
        return 3

    def quebra(conn, desde):
        raise RuntimeError("fonte fora do ar")

    def parcial(conn, desde):
        raise ColetaParcial(2, "1 ticker falhou")

    resultados = [executar(conn, nome, f, date(2026, 1, 1))
                  for nome, f in [("a", ok), ("b", quebra), ("c", parcial), ("d", ok)]]
    assert [r.status for r in resultados] == ["sucesso", "falha", "parcial", "sucesso"]
    regs = _registros(conn)
    assert regs[1]["erro"] == "RuntimeError: fonte fora do ar"
    assert [r["registros_novos"] for r in regs] == [3, 0, 2, 3]


def test_falha_desfaz_transacao_pendente(conn):
    def grava_e_quebra(conn, desde):
        conn.execute("INSERT INTO macro (serie, data, valor, fonte, disponivel_em, coletado_em) "
                     "VALUES ('x', '2026-01-01', 1, 'f', ?, ?)", (TS, TS))
        raise RuntimeError("meio do caminho")

    executar(conn, "x", grava_e_quebra, date(2026, 1, 1))
    assert conn.execute("SELECT COUNT(*) FROM macro").fetchone()[0] == 0
