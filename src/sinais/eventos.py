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
Cobertura de todas as empresas: `processar_titulos` classifica os títulos dos
fatos relevantes em lotes (~40 por requisição); `processar` lê o texto
completo, priorizando as empresas mais líquidas, e tem preferência no sinal.
Um dia só recebe sinal se todos os fatos relevantes da sua janela já foram
tratados (senão um pendente viraria um falso "sem evento"); releases são
complemento e não bloqueiam.
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


class EventoTitulo(BaseModel):
    """Classificação feita só pelo título (assunto) do documento, em lote."""
    id: int
    tipo_evento: Literal[
        "resultado_periodo", "dividendos_jcp", "recompra_acoes", "emissao_divida", "emissao_acoes",
        "fusao_aquisicao", "venda_ativos", "mudanca_gestao", "guidance_projecao", "producao_operacional",
        "regulatorio_juridico", "contrato_relevante", "reestruturacao", "outro"]
    direcao: Literal["positiva", "neutra", "negativa"]
    relevancia: int = Field(ge=1, le=5)


class LoteTitulos(BaseModel):
    eventos: list[EventoTitulo]


class LLM(Protocol):
    modelo: str

    def classificar(self, prompt: str, schema: type[BaseModel] = Evento) -> str: ...


class CotaEsgotada(Exception):
    """Limite do plano gratuito atingido: parar e continuar na próxima execução."""


class ServicoIndisponivel(Exception):
    """Gemini sobrecarregado (5xx) mesmo após novas tentativas: parar e continuar
    depois. Nunca vira erro permanente do documento (é problema do servidor)."""


PARAR = (CotaEsgotada, ServicoIndisponivel)


class ClienteGemini:
    def __init__(self, modelo: str | None = None, api_key: str | None = None,
                 pausa: float | None = None, tentativas: int = 6, dormir=time.sleep):
        from google import genai
        from google.genai import types

        chave = api_key or os.getenv("GEMINI_API_KEY")
        if not chave:
            raise RuntimeError("GEMINI_API_KEY ausente no .env")
        self.modelo = modelo or os.getenv("GEMINI_MODELO") or MODELO_PADRAO
        self._cliente = genai.Client(api_key=chave)
        self._types = types
        self._configs: dict[type, object] = {}
        # plano grátis: ~10 requisições/min no flash-lite (429 observado com 15/min)
        pausa = pausa if pausa is not None else float(os.getenv("GEMINI_PAUSA", "6.5"))
        self._pausa, self._tentativas, self._dormir = pausa, tentativas, dormir
        self._ultima = 0.0

    def _config(self, schema: type[BaseModel] | None):
        """schema=None: texto livre (ex.: relatório); senão, JSON validado pelo schema."""
        if schema not in self._configs:
            sem_ferramentas = self._types.AutomaticFunctionCallingConfig(disable=True)
            self._configs[schema] = (
                self._types.GenerateContentConfig(automatic_function_calling=sem_ferramentas) if schema is None
                else self._types.GenerateContentConfig(
                    response_mime_type="application/json", response_json_schema=schema.model_json_schema(),
                    automatic_function_calling=sem_ferramentas))
        return self._configs[schema]

    def classificar(self, prompt: str, schema: type[BaseModel] | None = Evento) -> str:
        from google.genai import errors

        for tentativa in range(self._tentativas):
            espera = self._pausa - (time.monotonic() - self._ultima)
            if espera > 0:
                self._dormir(espera)  # respeita o ritmo máximo do plano
            self._ultima = time.monotonic()
            try:
                return self._cliente.models.generate_content(
                    model=self.modelo, contents=prompt, config=self._config(schema)).text
            except errors.APIError as e:
                if e.code not in (429, 500, 503) or tentativa == self._tentativas - 1:
                    if e.code == 429:
                        raise CotaEsgotada(str(e)[:200]) from e
                    if e.code in (500, 503):
                        raise ServicoIndisponivel(str(e)[:200]) from e
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


def _por_prioridade(conn: sqlite3.Connection, docs: pd.DataFrame) -> pd.DataFrame:
    """Ordena documentos pelas empresas mais líquidas hoje (tabela universo),
    depois pelo mais antigo: com a cota grátis limitada, o texto completo é
    lido primeiro onde mais importa."""
    liquidez = dict(conn.execute(
        "SELECT ticker, volume_medio FROM universo WHERE data = (SELECT MAX(data) FROM universo)").fetchall())
    return (docs.assign(_prioridade=docs["ticker"].map(liquidez).fillna(0.0))
            .sort_values(["_prioridade", "disponivel_em"], ascending=[False, True])
            .drop(columns="_prioridade"))


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
    pendentes = _por_prioridade(conn, docs[~docs["id"].isin(feitos | com_erro)])
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
            except PARAR as e:
                logger.warning("Gemini indisponível ou cota esgotada; continue depois: %s", e)
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


# ---------------------------------------------------------------- títulos em lote

SUFIXO_TITULOS = ":titulos"
TAMANHO_LOTE = 40


def montar_prompt_titulos(lote: pd.DataFrame) -> str:
    linhas = "\n".join(f"{r.id} | {r.disponivel_em[:10]} | {r.ticker} | {r.assunto}" for r in lote.itertuples())
    return (
        "Você analisa fatos relevantes de companhias abertas brasileiras para um investidor.\n"
        "Abaixo, um por linha: id | data de entrega à CVM | ticker | título do documento.\n"
        "Classifique CADA um só pelo título, devolvendo o mesmo id. Regras:\n"
        "- Julgue apenas pelo título e pelo que se sabia na data; não use conhecimento posterior.\n"
        "- direção = efeito esperado para o acionista; se o título não permitir julgar, use 'neutra'.\n"
        "- relevância 1 (rotina) a 5 (altera a tese); título vago = relevância baixa.\n\n"
        + linhas
    )


def processar_titulos(conn: sqlite3.Connection, llm: LLM, limite_lotes: int | None = None,
                      tamanho_lote: int = TAMANHO_LOTE) -> dict[str, int]:
    """Classifica pelo TÍTULO, em lotes, os fatos relevantes que ainda não
    têm evento (nem por texto completo nem por título). Cobre todas as
    empresas com poucas requisições; o texto completo (`processar`) aprofunda
    depois, por ordem de liquidez, e tem preferência no sinal."""
    modelo_t = llm.modelo + SUFIXO_TITULOS
    docs = documentos_elegiveis(conn)
    fatos = docs[docs["tipo"] == "fato_relevante"]
    feitos_t, erros_t = _situacao(conn, modelo_t)
    feitos_c, _ = _situacao(conn, llm.modelo)
    pendentes = _por_prioridade(conn, fatos[~fatos["id"].isin(feitos_t | erros_t | feitos_c)])
    contagem = {"classificados": 0, "cache": 0, "erros": 0, "lotes": 0}

    sem_titulo = pendentes[pendentes["assunto"].fillna("").str.strip() == ""]
    for doc_id in sem_titulo["id"]:
        _registrar_erro(conn, int(doc_id), modelo_t, "titulo: documento sem assunto")
        contagem["erros"] += 1
    pendentes = pendentes.drop(sem_titulo.index)

    for inicio in range(0, len(pendentes), tamanho_lote):
        if limite_lotes is not None and contagem["lotes"] >= limite_lotes:
            break
        lote = pendentes.iloc[inicio:inicio + tamanho_lote]
        prompt = montar_prompt_titulos(lote)
        chave = chave_cache(modelo_t, prompt)
        linha = conn.execute("SELECT resposta FROM llm_cache WHERE chave = ?", (chave,)).fetchone()
        if linha:
            bruta = linha[0]
            contagem["cache"] += 1
        else:
            try:
                bruta = llm.classificar(prompt, schema=LoteTitulos)
            except PARAR as e:
                logger.warning("Gemini indisponível ou cota esgotada; continue depois: %s", e)
                break
            except Exception as e:  # noqa: BLE001
                logger.warning("Lote de títulos falhou: %s", e)
                contagem["erros"] += len(lote)
                for doc_id in lote["id"]:
                    _registrar_erro(conn, int(doc_id), modelo_t, f"llm: {type(e).__name__}: {e}")
                continue
        try:
            resposta = {e.id: e for e in LoteTitulos.model_validate_json(bruta).eventos}
        except ValidationError as e:
            for doc_id in lote["id"]:
                _registrar_erro(conn, int(doc_id), modelo_t, f"schema: {e.errors()[0]['msg']}", bruta)
            contagem["erros"] += len(lote)
            continue

        agora = para_iso_utc(datetime.now(timezone.utc))
        with conn:
            conn.execute("INSERT OR IGNORE INTO llm_cache (chave, modelo, versao_prompt, resposta, criado_em) "
                         "VALUES (?, ?, ?, ?, ?)", (chave, modelo_t, VERSAO_PROMPT, bruta, agora))
            for doc in lote.itertuples():
                ev = resposta.get(int(doc.id))
                if ev is None:  # o modelo pulou este id: fica para o texto completo
                    conn.execute("INSERT INTO llm_erros (documento_id, modelo, versao_prompt, erro, resposta_bruta, "
                                 "ocorrido_em) VALUES (?, ?, ?, ?, NULL, ?)",
                                 (int(doc.id), modelo_t, VERSAO_PROMPT, "titulo: id ausente na resposta", agora))
                    contagem["erros"] += 1
                    continue
                conn.execute("INSERT INTO eventos_documentos (documento_id, modelo, versao_prompt, tipo_evento, "
                             "direcao, relevancia, resumo, calculado_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                             (int(doc.id), modelo_t, VERSAO_PROMPT, ev.tipo_evento, ev.direcao, ev.relevancia,
                              (doc.assunto or "")[:500], agora))
                contagem["classificados"] += 1
        contagem["lotes"] += 1
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
    def _eventos(m):
        e = pd.read_sql_query("SELECT documento_id, direcao, relevancia FROM eventos_documentos "
                              "WHERE modelo = ? AND versao_prompt = ?", conn, params=(m, VERSAO_PROMPT))
        return e.assign(s=e["direcao"].map(DIRECAO) * e["relevancia"]).set_index("documento_id")["s"]

    completo, titulo = _eventos(modelo), _eventos(modelo + SUFIXO_TITULOS)
    docs = docs.copy()
    docs["s"] = docs["id"].map(completo).fillna(docs["id"].map(titulo))  # texto completo tem preferência
    docs["disponivel_em"] = pd.to_datetime(docs["disponivel_em"], utc=True)
    feitos_c, erros_c = _situacao(conn, modelo)
    feitos_t, erros_t = _situacao(conn, modelo + SUFIXO_TITULOS)
    # só fatos relevantes bloqueiam a janela; releases são complemento opcional
    tratados = feitos_c | erros_c | feitos_t | erros_t
    pendente = (docs["tipo"] == "fato_relevante") & ~docs["id"].isin(tratados)
    inicio = pd.to_datetime(pd.read_sql_query("SELECT MIN(disponivel_em) m FROM documentos", conn)["m"].iloc[0], utc=True)
    cotacoes = base.carregar_cotacoes(conn, ate)

    # o documento é da EMPRESA: vale para todos os tickers dela (ex.: PETR3 e PETR4)
    empresas = pd.read_sql_query("SELECT ticker, codigo_cvm FROM ativos WHERE codigo_cvm IS NOT NULL", conn)
    docs = docs.assign(pendente=pendente.to_numpy()).merge(
        empresas.rename(columns={"ticker": "_repr"}), left_on="ticker", right_on="_repr", how="left")
    docs = docs.merge(empresas.rename(columns={"ticker": "alvo"}), on="codigo_cvm", how="left")
    docs["alvo"] = docs["alvo"].fillna(docs["ticker"])

    partes = []
    for ticker, cot in cotacoes[cotacoes["ticker"].isin(docs["alvo"].unique())].groupby("ticker"):
        d = docs[docs["alvo"] == ticker]
        pend = d.loc[d["pendente"], "disponivel_em"]
        largo = sinais_ativo(cot["data"], d[d["s"].notna()], pend, inicio)
        longo = largo.melt(id_vars="data", var_name="nome", value_name="valor")
        longo["ticker"] = ticker
        if not longo.empty:
            partes.append(longo)
    if not partes:
        return vazio
    resultado = pd.concat(partes, ignore_index=True)[["ticker", "data", "nome", "valor"]]
    return resultado.astype({"ticker": object, "nome": object})
