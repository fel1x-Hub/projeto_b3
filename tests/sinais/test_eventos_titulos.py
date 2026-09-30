import json
import re
from datetime import date

import pandas as pd
import pytest

from src.sinais import eventos
from tests.sinais.conftest import dias_uteis, inserir_cotacoes
from tests.sinais.test_eventos import LLMFalso, VALIDO, inserir_documento


class LLMTitulos:
    """Responde lotes de títulos: 'recompra' -> positiva, 'multa' -> negativa, resto neutra.
    Ids listados em `pular` são omitidos da resposta."""
    modelo = "falso-1"

    def __init__(self, pular=()):
        self.pular, self.chamadas = set(pular), 0

    def classificar(self, prompt, schema=None):
        self.chamadas += 1
        itens = []
        for doc_id, titulo in re.findall(r"^(\d+) \| [\d-]+ \| \w+ \| (.*)$", prompt, flags=re.M):
            if int(doc_id) in self.pular:
                continue
            direcao = "positiva" if "recompra" in titulo else "negativa" if "multa" in titulo else "neutra"
            itens.append({"id": int(doc_id), "tipo_evento": "outro", "direcao": direcao, "relevancia": 3})
        return json.dumps({"eventos": itens})


@pytest.fixture
def conn_fatos(conn, monkeypatch):
    monkeypatch.setattr(eventos, "extrair_texto", lambda conteudo, max_paginas=None: conteudo.decode())
    monkeypatch.setenv("GEMINI_MODELO", "falso-1")
    ids = {
        "recompra": inserir_documento(conn, "A", "fato_relevante", "Programa de recompra", date(2024, 3, 5)),
        "multa": inserir_documento(conn, "B", "fato_relevante", "Aplicação de multa", date(2024, 3, 6)),
        "vazio": inserir_documento(conn, "C", "fato_relevante", "", date(2024, 3, 7)),
        "release": inserir_documento(conn, "D", "dados_economico_financeiros", "Release de Resultados", date(2024, 3, 7)),
    }
    return conn, ids


def _eventos(conn, modelo):
    return {r[0]: r[1] for r in conn.execute(
        "SELECT documento_id, direcao FROM eventos_documentos WHERE modelo = ?", (modelo,))}


def test_titulos_em_lote(conn_fatos):
    conn, ids = conn_fatos
    llm = LLMTitulos(pular={ids["multa"]})
    r = eventos.processar_titulos(conn, llm, tamanho_lote=10)
    assert (r["classificados"], r["erros"], r["lotes"], llm.chamadas) == (1, 2, 1, 1)  # multa pulada + sem título
    assert _eventos(conn, "falso-1:titulos") == {ids["recompra"]: "positiva"}
    erros = {r[0]: r[1] for r in conn.execute("SELECT documento_id, erro FROM llm_erros")}
    assert erros[ids["multa"]] == "titulo: id ausente na resposta"
    assert erros[ids["vazio"]] == "titulo: documento sem assunto"
    assert ids["release"] not in erros                     # releases não entram na classificação por título
    # segunda execução: nada pendente
    assert eventos.processar_titulos(conn, LLMTitulos())["lotes"] == 0


def test_documento_ja_lido_no_texto_completo_nao_vai_para_titulos(conn_fatos):
    conn, ids = conn_fatos
    http_texto = {"rad/A": b"texto A", "rad/B": b"texto B", "rad/D": b"texto D"}
    from tests.coleta.conftest import HTTPFalso
    eventos.processar(conn, LLMFalso(), HTTPFalso(http_texto))
    llm = LLMTitulos()
    eventos.processar_titulos(conn, llm)
    assert _eventos(conn, "falso-1:titulos") == {}          # só o sem-título, que vira erro


def test_sinal_prefere_texto_completo_e_release_nao_bloqueia(conn_fatos):
    conn, ids = conn_fatos
    dias = dias_uteis(date(2024, 3, 1), 30)
    inserir_cotacoes(conn, "PETR4", dias, [30.0] * 30)
    eventos.processar_titulos(conn, LLMTitulos())            # recompra +3, multa -3 (por título)
    s = eventos.calcular(conn)
    assert not s.empty                                       # release pendente não bloqueia
    v = s[(s["nome"] == "evt_saldo") & (s["data"] == pd.Timestamp(date(2024, 3, 6)))]["valor"].iloc[0]
    assert v == pytest.approx(3.0)

    # agora o texto completo da recompra diz outra coisa: ele tem preferência
    with conn:
        conn.execute("INSERT INTO eventos_documentos VALUES (?, 'falso-1', 1, 'recompra_acoes', 'positiva', 5, 'x', "
                     "'2026-01-01T00:00:00+00:00')", (ids["recompra"],))
    s = eventos.calcular(conn)
    v = s[(s["nome"] == "evt_saldo") & (s["data"] == pd.Timestamp(date(2024, 3, 6)))]["valor"].iloc[0]
    assert v == pytest.approx(5.0)


def test_prioridade_por_liquidez(conn):
    from src.db.ativos import registrar_automaticos
    registrar_automaticos(conn, {"VALE3": "VALE"})
    with conn:
        conn.executemany("INSERT INTO universo VALUES ('2024-03-01', ?, ?, 'liquidez', '2024-03-01T22:00:00+00:00')",
                         [("PETR4", 1e6), ("VALE3", 5e8)])
    inserir_documento(conn, "P", "fato_relevante", "p", date(2024, 1, 1), ticker="PETR4")
    inserir_documento(conn, "V", "fato_relevante", "v", date(2024, 2, 1), ticker="VALE3")
    ordem = eventos._por_prioridade(conn, eventos.documentos_elegiveis(conn))
    assert list(ordem["ticker"]) == ["VALE3", "PETR4"]      # mais líquida primeiro, mesmo sendo mais recente


def test_servico_indisponivel_para_sem_erro_permanente(conn_fatos):
    conn, ids = conn_fatos

    class Sobrecarregado(LLMTitulos):
        def classificar(self, prompt, schema=None):
            raise eventos.ServicoIndisponivel("503 UNAVAILABLE")

    r = eventos.processar_titulos(conn, Sobrecarregado())
    assert r["classificados"] == 0 and r["lotes"] == 0
    erros = [e for (e,) in conn.execute("SELECT erro FROM llm_erros")]
    assert erros == ["titulo: documento sem assunto"]        # 503 não vira erro do documento
    assert eventos.processar_titulos(conn, LLMTitulos())["classificados"] == 2  # na próxima, processa
