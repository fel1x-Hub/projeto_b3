from datetime import date

import pytest

from src.coleta import eventos_manuais


def _csv(tmp_path, linhas):
    p = tmp_path / "ev.csv"
    p.write_text("ticker,data_ex,tipo,valor,fator,referencia\n" + linhas, encoding="utf-8")
    return p


def test_grava_evento_com_referencia(conn, tmp_path):
    p = _csv(tmp_path, 'PETR4,2021-10-04,dividendo,5.2041,,"Fato relevante X"\n'
                       'XPTO3,2021-10-04,dividendo,1.0,,"ticker não acompanhado"\n')
    assert eventos_manuais.coletar(conn, date(2021, 1, 1), caminho=p) == 1
    linha = conn.execute("SELECT valor, fonte, disponivel_em FROM proventos").fetchone()
    assert tuple(linha) == (5.2041, "manual", "2021-10-04T03:00:00+00:00")
    assert eventos_manuais.coletar(conn, date(2021, 1, 1), caminho=p) == 0


def test_evento_sem_referencia_e_rejeitado(tmp_path):
    with pytest.raises(ValueError, match="referência"):
        eventos_manuais.carregar(_csv(tmp_path, "PETR4,2021-10-04,dividendo,1.0,,\n"))


def test_arquivo_do_projeto_e_valido():
    assert any(e["ticker"] == "ITUB4" for e in eventos_manuais.carregar())
