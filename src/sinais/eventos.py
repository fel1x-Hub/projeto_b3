"""Eventos extraídos de documentos da CVM por LLM (Gemini, plano gratuito).

Documentos: todos os fatos relevantes + releases de resultado em português
(tipo `dados_economico_financeiros` cujo assunto indica release). Dos releases
só as primeiras páginas (destaques) são lidas; os números vêm das demonstrações,
calculados em código.

O LLM só CLASSIFICA e RESUME (tipo, direção, relevância, resumo). A resposta é
validada pelo schema `Evento` (pydantic); respostas fora do schema ou falhas vão
para `llm_erros`. Toda resposta válida fica em `llm_cache` (chave = sha256 do
modelo + versão do prompt + texto), então nada é reprocessado.

Risco residual de look-ahead: o modelo conhece fatos posteriores à data do
documento. O prompt manda julgar só pelo texto e pelo que se sabia na data,
mas isso não é garantido: tratar este sinal com cautela no backtest.

Sinais por ativo e pregão D (eventos com disponivel_em <= corte(D)); cada
evento vale s = direção (+1/0/-1) x relevância (1-5):
    evt_saldo   soma de s x 0,5^(idade/10), idade em pregões, até 63 pregões
    evt_n_21d   quantidade de eventos nos últimos 21 pregões
Um dia só recebe sinal se todos os documentos da sua janela já foram
processados (senão um documento pendente viraria um falso "sem evento").
"""

import hashlib
import io
import json
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from typing import Literal, Protocol

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, ValidationError

from src.db.tempo import para_iso_utc
from src.sinais import base

logger = logging.getLogger(__name__)

VERSAO = 1           # fórmula dos sinais
VERSAO_PROMPT = 1    # mudar o prompt ou o schema => nova versão (reprocessa)
MODELO_PADRAO = "gemini-3.5-flash-lite"
NOMES = ["evt_saldo", "evt_n_21d"]
VERSOES = {nome: VERSAO for nome in NOMES}
MEIA_VIDA, JANELA_SALDO, JANELA_CONTAGEM = 10, 63, 21
PAGINAS_RELEASE = 4
LIMITE_CARACTERES = 40_000
DIRECAO = {"positiva": 1, "neutra": 0, "negativa": -1}

RELEASE = re.compile(r"release|resultado|earnings", re.I)
INGLES = re.compile(r"ingl[eê]s|english|\bEN\b|\bresults\b", re.I)


class Evento(BaseModel):
    tipo_evento: Literal[
        "resultado_periodo", "dividendos_jcp", "recompra_acoes", "emissao_divida", "emissao_acoes",
        "fusao_aquisicao", "venda_ativos", "mudanca_gestao", "guidance_projecao", "producao_operacional",
        "regulatorio_juridico", "contrato_relevante", "reestruturacao", "outro"]
    direcao: Literal["positiva", "neutra", "negativa"] = Field(
        description="Efeito esperado para o acionista, julgado apenas pelo texto")
    relevancia: int = Field(ge=1, le=5, description="1 = rotina administrativa, 5 = altera a tese da empresa")
    resumo: str = Field(max_length=500, description="Resumo em até 2 frases, em português")


class LLM(Protocol):
    modelo: str

    def classificar(self, prompt: str) -> str: ...


class CotaEsgotada(Exception):
    """Limite do plano gratuito atingido: parar e continuar na próxima execução."""


class ClienteGemini:
    def __init__(self, modelo: str | None = None, api_key: str | None = None,
                 pausa: float | None = None, tentativas: int = 4, dormir=time.sleep):
        from google import genai
        from google.genai import types

        chave = api_key or os.getenv("GEMINI_API_KEY")
        if not chave:
            raise RuntimeError("GEMINI_API_KEY ausente no .env")
        self.modelo = modelo or os.getenv("GEMINI_MODELO") or MODELO_PADRAO
        self._cliente = genai.Client(api_key=chave)
        self._config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=Evento.model_json_schema(),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        # plano grátis: ~10 requisições/min no flash-lite (429 observado com 15/min)
        pausa = pausa if pausa is not None else float(os.getenv("GEMINI_PAUSA", "6.5"))
        self._pausa, self._tentativas, self._dormir = pausa, tentativas, dormir
        self._ultima = 0.0

    def classificar(self, prompt: str) -> str:
        from google.genai import errors

        for tentativa in range(self._tentativas):
            espera = self._pausa - (time.monotonic() - self._ultima)
            if espera > 0:
                self._dormir(espera)  # respeita o ritmo máximo do plano
            self._ultima = time.monotonic()
            try:
                return self._cliente.models.generate_content(
                    model=self.modelo, contents=prompt, config=self._config).text
            except errors.APIError as e:
                if e.code not in (429, 500, 503) or tentativa == self._tentativas - 1:
                    if e.code == 429:
                        raise CotaEsgotada(str(e)[:200]) from e
                    raise
                atraso = 30.0 * 2 ** tentativa if e.code == 429 else 5.0 * 2 ** tentativa
                logger.warning("Gemini %s; nova tentativa em %.0fs", e.code, atraso)
                self._dormir(atraso)
        raise AssertionError("inalcançável")


def extrair_texto(conteudo: bytes, max_paginas: int | None = None) -> str:
    from pypdf import PdfReader

    if not conteudo.startswith(b"%PDF"):
        raise ValueError(f"documento não é PDF (começa com {conteudo[:8]!r})")
    paginas = PdfReader(io.BytesIO(conteudo)).pages
    if max_paginas:
        paginas = paginas[:max_paginas]
    return "\n".join(p.extract_text() or "" for p in paginas).strip()


def montar_prompt(ticker: str, data: str, assunto: str | None, texto: str) -> str:
    return (
        f"Você analisa documentos oficiais de companhias abertas brasileiras para um investidor.\n"
        f"Documento entregue à CVM em {data} pela empresa do ticker {ticker}. Assunto: {assunto or '-'}.\n"
        "Classifique o principal evento descrito. Regras:\n"
        "- Julgue APENAS pelo texto e pelo que se sabia na data do documento; não use conhecimento "
        "sobre o que aconteceu depois.\n"
        "- Não calcule números; apenas classifique e resuma.\n"
        "- direção = efeito esperado para o acionista; relevância 1 (rotina) a 5 (altera a tese).\n\n"
        f"TEXTO:\n{texto[:LIMITE_CARACTERES]}"
    )


def chave_cache(modelo: str, texto_prompt: str) -> str:
    return hashlib.sha256(f"{modelo}|{VERSAO_PROMPT}|{texto_prompt}".encode()).hexdigest()


def documentos_elegiveis(conn: sqlite3.Connection) -> pd.DataFrame:
    docs = pd.read_sql_query(
        "SELECT d.id, d.ticker, d.tipo, d.assunto, d.url, d.disponivel_em FROM documentos d "
        "JOIN ativos a ON a.ticker = d.ticker WHERE a.ativo = 1 "
        "AND d.tipo IN ('fato_relevante', 'dados_economico_financeiros')", conn)
    assunto = docs["assunto"].fillna("")
    release = (docs["tipo"] == "dados_economico_financeiros") & assunto.str.contains(RELEASE) & ~assunto.str.contains(INGLES)
    return docs[(docs["tipo"] == "fato_relevante") | release].reset_index(drop=True)


def _situacao(conn: sqlite3.Connection, modelo: str) -> tuple[set[int], set[int]]:
    feitos = {r[0] for r in conn.execute(
        "SELECT documento_id FROM eventos_documentos WHERE modelo = ? AND versao_prompt = ?", (modelo, VERSAO_PROMPT))}
    com_erro = {r[0] for r in conn.execute(
        "SELECT documento_id FROM llm_erros WHERE modelo = ? AND versao_prompt = ?", (modelo, VERSAO_PROMPT))}
    return feitos, com_erro


def _registrar_erro(conn, doc_id, modelo, erro, bruta=None):
    with conn:
        conn.execute("INSERT INTO llm_erros (documento_id, modelo, versao_prompt, erro, resposta_bruta, ocorrido_em) "
                     "VALUES (?, ?, ?, ?, ?, ?)",
                     (doc_id, modelo, VERSAO_PROMPT, erro[:500], bruta, para_iso_utc(datetime.now(timezone.utc))))


def processar(conn: sqlite3.Connection, llm: LLM, http, limite: int | None = None) -> dict[str, int]:
    """Extrai eventos dos documentos elegíveis ainda não processados.
    Para ao atingir `limite` ou a cota do plano gratuito (retomável)."""
    docs = documentos_elegiveis(conn)
    feitos, com_erro = _situacao(conn, llm.modelo)
    pendentes = docs[~docs["id"].isin(feitos | com_erro)].sort_values("disponivel_em")
    if limite is not None:
        pendentes = pendentes.head(limite)
    contagem = {"processados": 0, "cache": 0, "erros": 0, "pendentes_restantes": 0}

    for doc in pendentes.itertuples(index=False):
        data = doc.disponivel_em[:10]
        try:
            paginas = PAGINAS_RELEASE if doc.tipo == "dados_economico_financeiros" else None
            texto = extrair_texto(http.get_texto(doc.url), paginas)
            if not texto:
                raise ValueError("PDF sem texto extraível (provavelmente imagem)")
        except Exception as e:  # noqa: BLE001 - um documento ruim não para o lote
            _registrar_erro(conn, doc.id, llm.modelo, f"texto: {type(e).__name__}: {e}")
            contagem["erros"] += 1
            continue

        prompt = montar_prompt(doc.ticker, data, doc.assunto, texto)
        chave = chave_cache(llm.modelo, prompt)
        linha = conn.execute("SELECT resposta FROM llm_cache WHERE chave = ?", (chave,)).fetchone()
        if linha:
            bruta = linha[0]
            contagem["cache"] += 1
        else:
            try:
                bruta = llm.classificar(prompt)
            except CotaEsgotada as e:
                logger.warning("Cota do Gemini esgotada; continue depois: %s", e)
                break
            except Exception as e:  # noqa: BLE001
                _registrar_erro(conn, doc.id, llm.modelo, f"llm: {type(e).__name__}: {e}")
                contagem["erros"] += 1
                continue
        try:
            evento = Evento.model_validate_json(bruta)
        except ValidationError as e:
            _registrar_erro(conn, doc.id, llm.modelo, f"schema: {e.errors()[0]['msg']}", bruta)
            contagem["erros"] += 1
            continue

        agora = para_iso_utc(datetime.now(timezone.utc))
        with conn:
            conn.execute("INSERT OR IGNORE INTO llm_cache (chave, modelo, versao_prompt, resposta, criado_em) "
                         "VALUES (?, ?, ?, ?, ?)", (chave, llm.modelo, VERSAO_PROMPT, json.dumps(evento.model_dump()), agora))
            conn.execute("INSERT INTO eventos_documentos (documento_id, modelo, versao_prompt, tipo_evento, direcao, "
                         "relevancia, resumo, calculado_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (doc.id, llm.modelo, VERSAO_PROMPT, evento.tipo_evento, evento.direcao,
                          evento.relevancia, evento.resumo, agora))
        contagem["processados"] += 1

    feitos, com_erro = _situacao(conn, llm.modelo)
    contagem["pendentes_restantes"] = int((~docs["id"].isin(feitos | com_erro)).sum())
    return contagem


# ---------------------------------------------------------------- sinais

def sinais_ativo(pregoes: pd.Series, eventos: pd.DataFrame, pendentes: pd.Series, inicio: pd.Timestamp) -> pd.DataFrame:
    """`eventos`: disponivel_em (UTC) e s; `pendentes`: disponivel_em (UTC) de documentos não processados."""
    pregoes = pregoes.sort_values().reset_index(drop=True)
    cortes = pd.to_datetime(pregoes.dt.date.map(base.corte), utc=True)
    n = len(pregoes)
    idx = np.arange(n)
    saldo, contagem = np.zeros(n), np.zeros(n)
    for pos, s in zip(np.searchsorted(cortes.values, eventos["disponivel_em"].values), eventos["s"]):
        idade = idx - pos
        dentro = (idade >= 0) & (idade < JANELA_SALDO)
        saldo[dentro] += s * 0.5 ** (idade[dentro] / MEIA_VIDA)
        contagem[(idade >= 0) & (idade < JANELA_CONTAGEM)] += 1
    valido = (cortes >= inicio).to_numpy().copy()
    for pos in np.searchsorted(cortes.values, pendentes.values):
        idade = idx - pos
        valido &= ~((idade >= 0) & (idade < JANELA_SALDO))  # janela com documento pendente: sem sinal
    return pd.DataFrame({"data": pregoes, "evt_saldo": saldo, "evt_n_21d": contagem})[valido]


def calcular(conn: sqlite3.Connection, ate: str | None = None, modelo: str | None = None) -> pd.DataFrame:
    modelo = modelo or os.getenv("GEMINI_MODELO") or MODELO_PADRAO
    docs = documentos_elegiveis(conn)
    if ate is not None:
        docs = docs[docs["disponivel_em"] <= ate]
    vazio = pd.DataFrame({"ticker": pd.Series(dtype=object), "data": pd.Series(dtype="datetime64[us]"),
                          "nome": pd.Series(dtype=object), "valor": pd.Series(dtype=float)})
    if docs.empty:
        return vazio
    eventos = pd.read_sql_query("SELECT documento_id, direcao, relevancia FROM eventos_documentos "
                                "WHERE modelo = ? AND versao_prompt = ?", conn, params=(modelo, VERSAO_PROMPT))
    feitos, com_erro = _situacao(conn, modelo)
    docs = docs.merge(eventos, left_on="id", right_on="documento_id", how="left")
    docs["s"] = docs["direcao"].map(DIRECAO) * docs["relevancia"]
    docs["disponivel_em"] = pd.to_datetime(docs["disponivel_em"], utc=True)
    pendente = ~docs["id"].isin(feitos | com_erro)
    inicio = pd.to_datetime(pd.read_sql_query("SELECT MIN(disponivel_em) m FROM documentos", conn)["m"].iloc[0], utc=True)
    cotacoes = base.carregar_cotacoes(conn, ate)

    partes = []
    for ticker, cot in cotacoes[cotacoes["ticker"].isin(docs["ticker"].unique())].groupby("ticker"):
        d = docs[docs["ticker"] == ticker]
        pend = docs.loc[pendente & (docs["ticker"] == ticker), "disponivel_em"]
        largo = sinais_ativo(cot["data"], d[d["s"].notna()], pend, inicio)
        longo = largo.melt(id_vars="data", var_name="nome", value_name="valor")
        longo["ticker"] = ticker
        if not longo.empty:
            partes.append(longo)
    if not partes:
        return vazio
    resultado = pd.concat(partes, ignore_index=True)[["ticker", "data", "nome", "valor"]]
    return resultado.astype({"ticker": object, "nome": object})
