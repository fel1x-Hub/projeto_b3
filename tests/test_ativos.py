from src.db.ativos import sincronizar_ativos
from src.db.migracoes import migrar


def _ativo(ticker, nome=None, **extra):
    return {"ticker": ticker, "nome": nome or ticker, "setor": None, "cnpj": None, "ativo": 1, **extra}


def _linhas(conn):
    return {r["ticker"]: dict(r) for r in conn.execute("SELECT * FROM ativos")}


def test_insere_e_e_idempotente(conn_vazia):
    migrar(conn_vazia)
    lista = [_ativo("PETR4"), _ativo("VALE3")]
    assert sincronizar_ativos(conn_vazia, lista) == {"inseridos": 2, "atualizados": 0, "desativados": 0}
    assert sincronizar_ativos(conn_vazia, lista) == {"inseridos": 0, "atualizados": 0, "desativados": 0}
    assert len(_linhas(conn_vazia)) == 2


def test_ticker_removido_da_lista_e_desativado_sem_apagar(conn_vazia):
    migrar(conn_vazia)
    sincronizar_ativos(conn_vazia, [_ativo("PETR4"), _ativo("VALE3")])
    resultado = sincronizar_ativos(conn_vazia, [_ativo("PETR4")])
    assert resultado["desativados"] == 1
    linhas = _linhas(conn_vazia)
    assert linhas["VALE3"]["ativo"] == 0 and linhas["PETR4"]["ativo"] == 1

    # voltando para a lista, é reativado
    resultado = sincronizar_ativos(conn_vazia, [_ativo("PETR4"), _ativo("VALE3")])
    assert resultado["atualizados"] == 1
    assert _linhas(conn_vazia)["VALE3"]["ativo"] == 1


def test_atualiza_nome_e_preserva_cnpj_ja_preenchido(conn_vazia):
    migrar(conn_vazia)
    sincronizar_ativos(conn_vazia, [_ativo("PETR4", cnpj="33.000.167/0001-01")])
    resultado = sincronizar_ativos(conn_vazia, [_ativo("PETR4", nome="Petróleo Brasileiro")])
    assert resultado["atualizados"] == 1
    linha = _linhas(conn_vazia)["PETR4"]
    assert linha["nome"] == "Petróleo Brasileiro"
    assert linha["cnpj"] == "33.000.167/0001-01"
