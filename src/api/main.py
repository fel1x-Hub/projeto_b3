"""API FastAPI (etapa 7): única fonte de dados do app desktop e do site (regra 10).

Rodar:  uvicorn src.api.main:app --reload     (Swagger em http://127.0.0.1:8000/docs)
Token:  API_TOKEN no .env; as interfaces mandam "Authorization: Bearer <token>".
Desenho e convenções: docs/api.md.
"""

import math
import os
import secrets
import sqlite3
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Security, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator

from src.api import assistente, autenticacao, consultas, notificacoes
from src.carteira import importar as importador
from src.carteira import servico
from src.db import schema_nuvem
from src.db.migracoes import migrar
from src.db.nuvem import ConexaoPG, conectar_api
from src.db.tempo import agora_utc_iso
from src.logging_config import configurar_logging

VERSAO_API = "1.2"
_bearer = HTTPBearer(auto_error=False)


@asynccontextmanager
async def _ciclo_de_vida(app: FastAPI):
    configurar_logging()
    if not os.getenv("API_TOKEN"):
        raise RuntimeError("API_TOKEN ausente no .env: a API não sobe aberta (veja .env.example)")
    conn = conectar_api(app.state.db_path)
    try:
        if isinstance(conn, ConexaoPG):
            schema_nuvem.garantir(conn)     # Postgres na nuvem (DATABASE_URL)
        else:
            migrar(conn)                     # SQLite local
    finally:
        conn.close()
    yield


app = FastAPI(title="Projeto B3", version=VERSAO_API, lifespan=_ciclo_de_vida,
              description="Ranking, sinais, carteira e chat. Material de apoio, não recomendação de investimento.")
app.state.db_path = None   # None = DATABASE_URL (Postgres) ou o SQLite padrão; testes trocam
# CORS (etapa 8.6): só o site. API_ORIGENS = lista exata; API_ORIGENS_REGEX = padrão (ex.: os
# endereços do projeto no Vercel, que mudam a cada deploy de prévia). O token continua obrigatório.
app.add_middleware(CORSMiddleware,
                   allow_origins=[o for o in os.getenv("API_ORIGENS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o],
                   allow_origin_regex=os.getenv("API_ORIGENS_REGEX") or None,
                   allow_methods=["*"], allow_headers=["*"])


class Limitador:
    """Limite de requisições por IP em janela de 60 s (etapa 8.6: evita abuso; em memória, 1 instância)."""

    def __init__(self, limites: dict[str, int]):
        self.limites, self._vistos, self._trava = limites, {}, threading.Lock()

    def permitir(self, ip: str, grupo: str, agora: float | None = None) -> bool:
        agora = time.monotonic() if agora is None else agora
        with self._trava:
            fila = self._vistos.setdefault((ip, grupo), deque())
            while fila and agora - fila[0] > 60:
                fila.popleft()
            if len(fila) >= self.limites[grupo]:
                return False
            fila.append(agora)
            return True


limitador = Limitador({"geral": int(os.getenv("API_LIMITE_MIN", "180")), "llm": int(os.getenv("API_LIMITE_LLM_MIN", "10")),
                       "login": int(os.getenv("API_LIMITE_LOGIN_MIN", "5"))})   # dificulta adivinhar a senha


@app.middleware("http")
async def _limitar(request: Request, chamar):
    caminho = request.url.path
    if caminho in ("/saude", "/health"):
        return await chamar(request)
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "?")
    grupo = ("login" if caminho == "/login" else
             "llm" if caminho == "/chat" or caminho.endswith("/porque") else "geral")
    if not limitador.permitir(ip, grupo):
        return JSONResponse({"detail": "muitas requisições; tente de novo em instantes"}, status_code=429)
    return await chamar(request)


def quem(cred: HTTPAuthorizationCredentials | None = Security(_bearer)) -> str | None:
    """Usuário da requisição: sessão de login válida, ou o API_TOKEN (scripts); None = visitante."""
    if cred is None:
        return None
    esperado = os.getenv("API_TOKEN", "")
    if esperado and secrets.compare_digest(cred.credentials, esperado):
        return "api_token"
    return autenticacao.validar_sessao(cred.credentials)


def autenticar(usuario: str | None = Depends(quem)) -> str:
    """Carteira, chat e 'por quê' exigem login (dados pessoais e cota do Gemini)."""
    if usuario is None:
        raise HTTPException(401, "entre com usuário e senha para usar esta parte")
    return usuario


def banco():
    conn = conectar_api(app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()


def limpar(obj):
    """NaN/infinito (pandas) viram null: JSON não tem NaN."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: limpar(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [limpar(v) for v in obj]
    return obj


def envelope(dados, atualizado_em: str | None, provisorio: bool = False) -> dict:
    """Formato comum (regra 15): quando o dado ficou pronto, se é provisório e se o mercado está aberto."""
    return {"atualizado_em": atualizado_em, "provisorio": provisorio,
            "mercado_aberto": consultas.mercado_aberto(), "dados": limpar(dados)}


def _ticker(conn: sqlite3.Connection, ticker: str) -> str:
    t = ticker.upper()
    if not conn.execute("SELECT 1 FROM ativos WHERE ticker = ?", (t,)).fetchone():
        raise HTTPException(404, f"ticker desconhecido: {t}")
    return t


protegido = [Depends(autenticar)]


# ---------------------------------------------------------------- básicos

@app.get("/saude", tags=["sistema"])
@app.get("/health", tags=["sistema"], include_in_schema=False)   # nome que os serviços de hospedagem esperam
def saude():
    return {"ok": True, "versao": VERSAO_API}


class Login(BaseModel):
    usuario: str = Field(min_length=1, max_length=100)
    senha: str = Field(min_length=1, max_length=200)


@app.post("/login", tags=["sistema"])
def login(dados: Login, conn=Depends(banco)):
    nome = autenticacao.autenticar_usuario(conn, dados.usuario, dados.senha)
    if nome is None:
        raise HTTPException(401, "usuário ou senha incorretos")
    return {"sessao": autenticacao.emitir_sessao(nome), "usuario": nome, "validade_dias": autenticacao.VALIDADE_DIAS}


@app.get("/eu", tags=["sistema"])
def eu(usuario: str | None = Depends(quem)):
    return {"usuario": usuario, "logado": usuario is not None}


@app.get("/status", tags=["sistema"])
def status(conn=Depends(banco)):
    oficial = consultas.ranking_em_vigor(conn, "oficial")
    vigor = consultas.ranking_em_vigor(conn)
    cot = conn.execute("SELECT MAX(coletado_em), MAX(horario_cotacao) FROM cotacao_atual").fetchone()
    ultimo = conn.execute("SELECT MAX(data) FROM relatorios").fetchone()[0]
    return envelope({"cotacao_momento": {"coletado_em": cot[0], "horario_cotacao": cot[1]},
                     "ranking_oficial": oficial, "ranking_em_vigor": vigor,
                     "ultimo_relatorio": ultimo,
                     "fontes": consultas.status_fontes(conn)},
                    agora_utc_iso(), bool(vigor and vigor["provisorio"]))


@app.get("/mercado", tags=["mercado"])
def mercado(conn=Depends(banco)):
    vigor = consultas.ranking_em_vigor(conn)
    tabela = consultas.tabela_ranking(conn, vigor)
    ibov = consultas.ibovespa(conn)
    horarios = [x for x in (ibov and ibov["horario"], vigor and vigor["atualizado_em"]) if x]
    return envelope({"ibovespa": ibov, "macro": consultas.macro(conn), "ranking": vigor,
                     "topo": tabela[:5], "fundo": tabela[-5:][::-1]},
                    max(horarios) if horarios else None,
                    bool((ibov and ibov["provisorio"]) or (vigor and vigor["provisorio"])))


@app.get("/ranking", tags=["mercado"])
def ranking(data: date | None = None, versao: Literal["vigor", "oficial"] = "vigor", conn=Depends(banco),
            usuario: str | None = Depends(quem)):
    if data:
        vigor = {"data": data.isoformat(), "versao": consultas.OFICIAL, "provisorio": False,
                 "atualizado_em": conn.execute("SELECT MAX(disponivel_em) FROM ranking WHERE data = ? AND versao_modelo = ?",
                                               (data.isoformat(), consultas.OFICIAL)).fetchone()[0]}
        if vigor["atualizado_em"] is None:
            raise HTTPException(404, f"sem ranking oficial em {data}")
    else:
        vigor = consultas.ranking_em_vigor(conn, None if versao == "vigor" else "oficial")
        if vigor is None:
            raise HTTPException(404, "nenhum ranking gerado ainda")
    tenho = {p["ticker"] for p in servico.montar(conn)["posicoes"]} if usuario else set()   # carteira é pessoal
    return envelope({"ranking": vigor, "linhas": consultas.tabela_ranking(conn, vigor, tenho)},
                    vigor["atualizado_em"], vigor["provisorio"])


# ---------------------------------------------------------------- ativo

@app.get("/ativo/{ticker}", tags=["ativo"])
def ativo(ticker: str, dias: int = Query(365, ge=5, le=365 * 5), conn=Depends(banco)):
    t = _ticker(conn, ticker)
    cad = conn.execute("SELECT nome, setor, cnpj FROM ativos WHERE ticker = ?", (t,)).fetchone()
    vigor = consultas.ranking_em_vigor(conn)
    rank = consultas.posicoes_ranking(conn, vigor)
    preco = consultas.precos(conn).get(t)
    hist = consultas.historico_precos(conn, t, dias)
    nota = consultas.pontuacoes(conn, vigor).get(t)
    sinais = consultas.sinais_atuais(conn, t)
    recentes = consultas.historico_precos(conn, t, 200)["fechamento"].dropna().to_numpy()
    dados = {
        "ticker": t, "nome": cad[0], "setor": cad[1], "cnpj": cad[2],
        "cotacao": preco,
        "ranking": {"posicao": rank.get(t, (None, None))[0], "score": rank.get(t, (None, None))[1],
                    "total": len(rank), "em_vigor": vigor},
        "fatores": consultas.fatores(conn, vigor, [t], n=8).get(t, []),
        "sinais": sinais,
        "pontuacao": nota,
        "previsoes": consultas.previsoes(nota and nota["compra"], consultas.tabela_calibracao(conn)),
        "padrao": {"tendencia": consultas.tendencia(sinais["sinais"]),
                   "grafico": consultas.padrao_grafico(conn, t, recentes)},
        "precos": hist.to_dict("records"),
        "historico_score": consultas.historico_score(conn, t, dias),
        "noticias": consultas.noticias(conn, t),
        "fatos_relevantes": consultas.fatos_relevantes(conn, t),
    }
    horarios = [x for x in (preco and preco["horario"], vigor and vigor["atualizado_em"]) if x]
    return envelope(dados, max(horarios) if horarios else None,
                    bool((preco and preco["provisorio"]) or (vigor and vigor["provisorio"])))


@app.get("/ativo/{ticker}/porque", tags=["ativo"], dependencies=protegido)
def ativo_porque(ticker: str, conn=Depends(banco)):
    t = _ticker(conn, ticker)
    vigor = consultas.ranking_em_vigor(conn)
    try:
        dados = assistente.porque(conn, t)
    except KeyError:
        raise HTTPException(404, f"{t} não está no ranking em vigor (fora do universo do modelo)")
    except Exception as e:  # noqa: BLE001 - cota/serviço do LLM
        raise HTTPException(503, f"explicação indisponível agora (LLM): {str(e)[:150]}")
    return envelope(dados, vigor and vigor["atualizado_em"], bool(vigor and vigor["provisorio"]))


# ---------------------------------------------------------------- relatório

@app.get("/relatorios", tags=["relatório"])
def relatorios(conn=Depends(banco)):
    datas = [r[0] for r in conn.execute("SELECT data FROM relatorios ORDER BY data DESC")]
    return envelope(datas, None)


@app.get("/relatorio/{data}", tags=["relatório"])
def relatorio(data: str, conn=Depends(banco)):
    datas = [r[0] for r in conn.execute("SELECT data FROM relatorios ORDER BY data")]
    if data == "ultimo":
        if not datas:
            raise HTTPException(404, "nenhum relatório gerado ainda")
        data = datas[-1]
    try:
        date.fromisoformat(data)
    except ValueError:
        raise HTTPException(422, "data no formato AAAA-MM-DD ou 'ultimo'")
    r = conn.execute("SELECT markdown, gerado_em FROM relatorios WHERE data = ?", (data,)).fetchone()
    if r is None:
        raise HTTPException(404, f"sem relatório de {data}")
    i = datas.index(data)
    return envelope({"data": data, "markdown": r[0],
                     "anterior": datas[i - 1] if i > 0 else None,
                     "proximo": datas[i + 1] if i + 1 < len(datas) else None}, r[1])


# ---------------------------------------------------------------- carteira

class Operacao(BaseModel):
    ticker: str = Field(examples=["PETR4"])
    tipo: Literal["compra", "venda"]
    data: date
    quantidade: float = Field(gt=0)
    preco: float = Field(gt=0)
    custos: float = Field(0, ge=0)

    @field_validator("ticker")
    @classmethod
    def _maiusculo(cls, v: str) -> str:
        v = v.strip().upper()
        m = importador.TICKER.match(v)
        if not m:
            raise ValueError("ticker inválido (ex.: PETR4, BOVA11)")
        return m.group(1)

    @field_validator("data")
    @classmethod
    def _nao_futura(cls, v: date) -> date:
        if v > date.today():
            raise ValueError("data no futuro")
        return v


def _carteira_envelope(conn, dados):
    horarios = [p["preco_horario"] for p in dados.get("posicoes", []) if p.get("preco_horario")]
    return envelope(dados, max(horarios) if horarios else None,
                    any(p.get("provisorio") for p in dados.get("posicoes", [])))


@app.get("/carteira", tags=["carteira"], dependencies=protegido)
def carteira(conn=Depends(banco)):
    return _carteira_envelope(conn, servico.montar(conn))


@app.get("/carteira/indicacoes", tags=["carteira"], dependencies=protegido)
def carteira_indicacoes(conn=Depends(banco)):
    cart = servico.montar(conn)
    dados = servico.indicacoes(conn, cart)
    dados["aviso"] = assistente.AVISO
    vigor = cart["ranking"]
    return envelope(dados, vigor and vigor["atualizado_em"], bool(vigor and vigor["provisorio"]))


@app.get("/carteira/evolucao", tags=["carteira"], dependencies=protegido)
def carteira_evolucao(dias: int = Query(365, ge=5, le=365 * 5), conn=Depends(banco)):
    serie = servico.evolucao(conn, dias)
    return envelope(serie, serie[-1]["data"] + "T21:00:00+00:00" if serie else None)


@app.get("/carteira/operacoes", tags=["carteira"], dependencies=protegido)
def carteira_operacoes(conn=Depends(banco)):
    return envelope(servico.operacoes(conn).to_dict("records"), None)


@app.post("/carteira/operacao", tags=["carteira"], dependencies=protegido, status_code=201)
def carteira_operacao(op: Operacao, conn=Depends(banco)):
    with conn:
        cur = conn.execute(
            "INSERT INTO carteira_operacoes (ticker, tipo, data, quantidade, preco, custos, origem, criado_em) "
            "VALUES (?, ?, ?, ?, ?, ?, 'manual', ?) RETURNING id",    # RETURNING: SQLite e Postgres
            (op.ticker, op.tipo, op.data.isoformat(), op.quantidade, op.preco, op.custos, agora_utc_iso()))
        novo_id = cur.fetchone()[0]
    return {"id": novo_id}


@app.delete("/carteira/operacao/{id_}", tags=["carteira"], dependencies=protegido)
def carteira_apagar(id_: int, conn=Depends(banco)):
    with conn:
        n = conn.execute("DELETE FROM carteira_operacoes WHERE id = ?", (id_,)).rowcount
    if not n:
        raise HTTPException(404, f"operação {id_} não existe")
    return {"apagadas": n}


@app.post("/carteira/importar", tags=["carteira"], dependencies=protegido)
async def carteira_importar(arquivo: UploadFile = File(...), conn=Depends(banco)):
    conteudo = await arquivo.read()
    if len(conteudo) > 5_000_000:
        raise HTTPException(413, "arquivo maior que 5 MB")
    try:
        r = importador.importar(conn, conteudo, arquivo.filename or "")
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"formato": r.formato, "importadas": r.importadas, "ja_existiam": r.ja_existiam,
            "nao_reconhecidas": [{"linha": l, "motivo": m} for l, m in r.nao_reconhecidas]}


@app.post("/carteira/sincronizar", tags=["carteira"], dependencies=protegido)
def carteira_sincronizar(conn=Depends(banco)):
    from src.coleta import pluggy
    if pluggy.credenciais() is None:
        raise HTTPException(409, "Meu Pluggy não configurado: PLUGGY_CLIENT_ID, PLUGGY_CLIENT_SECRET e "
                                 "PLUGGY_ITEM_IDS no .env (passo a passo em src/coleta/pluggy.py)")
    try:
        n = pluggy.coletar(conn)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"falha ao sincronizar com a Pluggy: {str(e)[:200]}")
    return {"posicoes": n}


@app.get("/notificacoes", tags=["carteira"], dependencies=protegido)
def notificacoes_(conn=Depends(banco)):
    cart = servico.montar(conn)
    return envelope(notificacoes.gerar(conn, cart), agora_utc_iso())


# ---------------------------------------------------------------- chat

class Mensagem(BaseModel):
    papel: Literal["usuario", "assistente"]
    texto: str = Field(min_length=1, max_length=4000)


class Conversa(BaseModel):
    mensagens: list[Mensagem] = Field(min_length=1, max_length=30)


@app.post("/chat", tags=["chat"], dependencies=protegido)
def chat(conversa: Conversa, conn=Depends(banco)):
    if conversa.mensagens[-1].papel != "usuario":
        raise HTTPException(422, "a última mensagem deve ser do usuário")
    try:
        dados = assistente.responder(conn, [m.model_dump() for m in conversa.mensagens])
    except Exception as e:  # noqa: BLE001 - cota/serviço do LLM
        raise HTTPException(503, f"chat indisponível agora (LLM): {str(e)[:150]}")
    return envelope(dados, agora_utc_iso())


SUGESTOES = ["Como está minha carteira hoje?", "Por que a primeira do ranking está no topo?",
             "Quais papéis da minha carteira caíram no ranking?", "O que mudou no top 30 hoje?",
             "Resuma o relatório do dia."]


@app.get("/chat/sugestoes", tags=["chat"])
def chat_sugestoes():
    return envelope(SUGESTOES, None)
