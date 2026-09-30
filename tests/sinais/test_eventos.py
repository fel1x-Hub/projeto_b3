import json
from datetime import date, time

import pandas as pd
import pytest

from src.db.tempo import iso_brt
from src.sinais import base, eventos
from tests.coleta.conftest import HTTPFalso
from tests.sinais.conftest import TS, dias_uteis, inserir_cotacoes

VALIDO = json.dumps({"tipo_evento": "dividendos_jcp", "direcao": "positiva", "relevancia": 4, "resumo": "JCP aprovado."})


class LLMFalso:
    modelo = "falso-1"

    def __init__(self, respostas=None, esgota_apos=None):
        self.respostas = respostas or {}
        self.chamadas = 0
        self.esgota_apos = esgota_apos

    def classificar(self, prompt, schema=None):
        self.chamadas += 1
        if self.esgota_apos is not None and self.chamadas > self.esgota_apos:
            raise eventos.CotaEsgotada("429")
        for trecho, resposta in self.respostas.items():
            if trecho in prompt:
                return resposta
        return VALIDO


def inserir_documento(conn, id_externo, tipo, assunto, entrega: date, ticker="PETR4"):
    with conn:
        return conn.execute(
            "INSERT INTO documentos (tipo, ticker, fonte, id_externo, url, assunto, disponivel_em, coletado_em) "
            "VALUES (?, ?, 'cvm_ipe', ?, ?, ?, ?, ?)",
            (tipo, ticker, id_externo, f"https://rad/{id_externo}", assunto,
             iso_brt(entrega, time(23, 59, 59)), TS)).lastrowid


@pytest.fixture
def conn_docs(conn, monkeypatch):
    monkeypatch.setattr(eventos, "extrair_texto", lambda conteudo, max_paginas=None: conteudo.decode())
    inserir_documento(conn, "FR1", "fato_relevante", "Pagamento de JCP", date(2024, 3, 5))
    inserir_documento(conn, "REL1", "dados_economico_financeiros", "Release de Resultados 4T23", date(2024, 3, 6))
    inserir_documento(conn, "REL-EN", "dados_economico_financeiros", "Earnings Release (inglês)", date(2024, 3, 6))
    inserir_documento(conn, "DEB", "dados_economico_financeiros", "Escritura de debêntures", date(2024, 3, 6))
    inserir_documento(conn, "COM", "comunicado", "Comunicado qualquer", date(2024, 3, 6))
    http = HTTPFalso({"rad/FR1": b"texto do fato JCP", "rad/REL1": b"release com resultado"})
    return conn, http


def test_seleciona_fatos_e_releases_em_portugues(conn_docs):
    conn, _ = conn_docs
    assert set(eventos.documentos_elegiveis(conn)["assunto"]) == {"Pagamento de JCP", "Release de Resultados 4T23"}


def test_processa_valida_e_usa_cache(conn_docs):
    conn, http = conn_docs
    llm = LLMFalso({"release com resultado": '{"tipo_evento": "inventado", "direcao": "positiva"}'})
    r = eventos.processar(conn, llm, http)
    assert (r["processados"], r["erros"], r["pendentes_restantes"]) == (1, 1, 0)
    ev = conn.execute("SELECT tipo_evento, direcao, relevancia FROM eventos_documentos").fetchone()
    assert tuple(ev) == ("dividendos_jcp", "positiva", 4)
    erro = conn.execute("SELECT erro, resposta_bruta FROM llm_erros").fetchone()
    assert erro["erro"].startswith("schema") and "inventado" in erro["resposta_bruta"]

    # reprocessar do zero: resposta válida vem do cache, sem chamar o LLM
    with conn:
        conn.execute("DELETE FROM eventos_documentos")
    llm2 = LLMFalso()
    r = eventos.processar(conn, llm2, http)
    assert (r["processados"], r["cache"], llm2.chamadas) == (1, 1, 0)


def test_cota_esgotada_para_e_retoma(conn_docs):
    conn, http = conn_docs
    r = eventos.processar(conn, LLMFalso(esgota_apos=1), http)
    assert (r["processados"], r["pendentes_restantes"]) == (1, 1)
    r = eventos.processar(conn, LLMFalso(), http)
    assert (r["processados"], r["pendentes_restantes"]) == (1, 0)


def test_documento_nao_pdf_vira_erro_e_nao_repete(conn, monkeypatch):
    inserir_documento(conn, "FR1", "fato_relevante", "x", date(2024, 3, 5))
    http = HTTPFalso({"rad/FR1": b"<html>erro</html>"})
    r = eventos.processar(conn, LLMFalso(), http)
    assert r["erros"] == 1
    assert "não é PDF" in conn.execute("SELECT erro FROM llm_erros").fetchone()[0]
    assert eventos.processar(conn, LLMFalso(), http)["erros"] == 0  # não tenta de novo


def test_extrair_texto_rejeita_nao_pdf():
    with pytest.raises(ValueError, match="não é PDF"):
        eventos.extrair_texto(b"PK\x03\x04zip")


# ---------------------------------------------------------------- sinais

@pytest.fixture
def conn_sinais(conn_docs):
    conn, http = conn_docs
    dias = dias_uteis(date(2024, 3, 1), 40)
    inserir_cotacoes(conn, "PETR4", dias, [30.0] * len(dias))
    return conn, http, dias


def _v(s, nome, dia):
    linha = s[(s["nome"] == nome) & (s["data"] == pd.Timestamp(dia))]
    return linha["valor"].iloc[0] if not linha.empty else None


def test_sem_sinal_enquanto_documento_pendente(conn_sinais, monkeypatch):
    conn, http, dias = conn_sinais
    monkeypatch.setenv("GEMINI_MODELO", "falso-1")
    # nada processado: todo pregão cuja janela de 63 pregões contém um documento pendente fica sem sinal,
    # e antes do primeiro documento não há cobertura
    assert eventos.calcular(conn).empty


def test_saldo_com_decaimento(conn_sinais, monkeypatch):
    conn, http, dias = conn_sinais
    monkeypatch.setenv("GEMINI_MODELO", "falso-1")
    neg = json.dumps({"tipo_evento": "resultado_periodo", "direcao": "negativa", "relevancia": 2, "resumo": "fraco"})
    eventos.processar(conn, LLMFalso({"release com resultado": neg}), http)
    s = eventos.calcular(conn)
    # FR1 entregue 05/03 23:59 -> pregão 06/03 (+4); REL1 entregue 06/03 -> pregão 07/03 (-2)
    assert _v(s, "evt_saldo", date(2024, 3, 5)) is None           # antes da cobertura dos documentos
    assert _v(s, "evt_saldo", date(2024, 3, 6)) == pytest.approx(4.0)
    assert _v(s, "evt_saldo", date(2024, 3, 7)) == pytest.approx(4 * 0.5 ** 0.1 - 2)
    d10 = dias[dias.index(date(2024, 3, 6)) + 10]
    assert _v(s, "evt_saldo", d10) == pytest.approx(4 * 0.5 - 2 * 0.5 ** 0.9)  # meia-vida de 10 pregões
    assert _v(s, "evt_n_21d", date(2024, 3, 7)) == 2


def test_anti_look_ahead_eventos(conn_sinais, monkeypatch):
    conn, http, dias = conn_sinais
    monkeypatch.setenv("GEMINI_MODELO", "falso-1")
    eventos.processar(conn, LLMFalso(), http)
    completo = eventos.calcular(conn)
    for d in dias[2:12]:
        truncado = eventos.calcular(conn, ate=base.corte(d))
        a = completo[completo["data"] == pd.Timestamp(d)].sort_values("nome").reset_index(drop=True)
        b = truncado[truncado["data"] == pd.Timestamp(d)].sort_values("nome").reset_index(drop=True)
        pd.testing.assert_frame_equal(a, b)
