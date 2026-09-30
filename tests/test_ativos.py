from src.db.ativos import registrar_automaticos, sincronizar_ativos
from src.db.migracoes import migrar


def _ativo(ticker, nome=None, **extra):
    return {"ticker": ticker, "nome": nome or ticker, "setor": None, "cnpj": None, "ativo": 1, **extra}


def _linhas(conn):
    return {r["ticker"]: dict(r) for r in conn.execute("SELECT * FROM ativos")}


def test_insere_e_e_idempotente(conn_vazia):
    migrar(conn_vazia)
    lista = [_ativo("PETR4"), _ativo("VALE3")]
    assert sincronizar_ativos(conn_vazia, lista) == {"inseridos": 2, "atualizados": 0, "liberados": 0}
    assert sincronizar_ativos(conn_vazia, lista) == {"inseridos": 0, "atualizados": 0, "liberados": 0}
    assert {l["origem"] for l in _linhas(conn_vazia).values()} == {"manual"}


def test_ticker_que_sai_do_csv_volta_ao_automatico_sem_apagar(conn_vazia):
    migrar(conn_vazia)
    sincronizar_ativos(conn_vazia, [_ativo("PETR4"), _ativo("VALE3", ativo=0)])  # VALE3 excluída à mão
    assert _linhas(conn_vazia)["VALE3"]["ativo"] == 0
    resultado = sincronizar_ativos(conn_vazia, [_ativo("PETR4")])
    assert resultado["liberados"] == 1
    vale = _linhas(conn_vazia)["VALE3"]
    assert (vale["origem"], vale["ativo"]) == ("auto", 1)   # deixa de ser exceção

    # voltando para o CSV, vira exceção manual de novo
    resultado = sincronizar_ativos(conn_vazia, [_ativo("PETR4"), _ativo("VALE3")])
    assert resultado["atualizados"] == 1
    assert _linhas(conn_vazia)["VALE3"]["origem"] == "manual"


def test_atualiza_nome_e_preserva_cnpj_ja_preenchido(conn_vazia):
    migrar(conn_vazia)
    sincronizar_ativos(conn_vazia, [_ativo("PETR4", cnpj="33.000.167/0001-01")])
    resultado = sincronizar_ativos(conn_vazia, [_ativo("PETR4", nome="Petróleo Brasileiro")])
    assert resultado["atualizados"] == 1
    linha = _linhas(conn_vazia)["PETR4"]
    assert linha["nome"] == "Petróleo Brasileiro"
    assert linha["cnpj"] == "33.000.167/0001-01"


def test_registrar_automaticos_nao_mexe_em_excecoes(conn_vazia):
    migrar(conn_vazia)
    sincronizar_ativos(conn_vazia, [_ativo("PETR4", nome="Petrobras", ativo=0)])
    assert registrar_automaticos(conn_vazia, {"PETR4": "PETROBRAS", "WEGE3": "WEG"}) == 1
    assert registrar_automaticos(conn_vazia, {"WEGE3": "WEG"}) == 0
    linhas = _linhas(conn_vazia)
    assert (linhas["PETR4"]["nome"], linhas["PETR4"]["ativo"], linhas["PETR4"]["origem"]) == ("Petrobras", 0, "manual")
    assert (linhas["WEGE3"]["origem"], linhas["WEGE3"]["tipo"]) == ("auto", "acao")
