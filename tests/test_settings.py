import logging

import pytest

from config import settings
from config.settings import carregar_ativos
from src.logging_config import configurar_logging

CABECALHO = "ticker,nome,setor,cnpj,ativo\n"


def _csv(tmp_path, conteudo):
    p = tmp_path / "ativos.csv"
    p.write_text(conteudo, encoding="utf-8")
    return p


def test_csv_do_projeto_e_valido():
    ativos = carregar_ativos()
    tickers = [a["ticker"] for a in ativos]
    assert {"PETR4", "VALE3", "ITUB4", "BBAS3", "WEGE3", "B3SA3", "BPAC11"} <= set(tickers)
    assert len(tickers) == len(set(tickers))


def test_normaliza_campos(tmp_path):
    p = _csv(tmp_path, CABECALHO + " petr4 ,Petrobras,,,\n\n")
    assert carregar_ativos(p) == [
        {"ticker": "PETR4", "nome": "Petrobras", "setor": None, "cnpj": None, "ativo": 1}
    ]


@pytest.mark.parametrize(
    "conteudo, trecho",
    [
        ("ticker,nome,setor\nPETR4,Petrobras,x\n", "colunas obrigatórias ausentes"),
        (CABECALHO + "PETR4,Petrobras,,,1\nPETR4,Petro,,,1\n", "ticker repetido"),
        (CABECALHO + "PETRO,Petrobras,,,1\n", "ticker inválido"),
        (CABECALHO + "PETR4,Petrobras,,,sim\n", "deve ser 0 ou 1"),
        (CABECALHO + "PETR4,,,,1\n", "nome vazio"),
    ],
)
def test_csv_invalido_gera_erro_claro(tmp_path, conteudo, trecho):
    with pytest.raises(ValueError, match=trecho):
        carregar_ativos(_csv(tmp_path, conteudo))


def test_caminhos_resolvidos_na_raiz_do_projeto():
    assert settings.DB_PATH.is_absolute()
    assert settings.LOG_DIR.is_absolute()


def test_configurar_logging_e_idempotente(tmp_path):
    raiz = logging.getLogger()
    antes = list(raiz.handlers)
    try:
        configurar_logging("DEBUG", tmp_path)
        configurar_logging("DEBUG", tmp_path)
        nossos = [h for h in raiz.handlers if h not in antes]
        assert len(nossos) == 2
        logging.getLogger("teste").info("ola")
        for h in nossos:
            h.flush()
        assert "ola" in (tmp_path / "app.log").read_text(encoding="utf-8")
    finally:
        for h in [h for h in raiz.handlers if h not in antes]:
            raiz.removeHandler(h)
            h.close()
