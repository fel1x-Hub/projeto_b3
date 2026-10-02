"""Chat de IA e explicação "por quê" (regras 2, 12 e 16).

O backend monta o contexto (ranking, carteira, sinais dos papéis citados,
notícias, fatos, macro, relatório do dia) com os números JÁ FORMATADOS, e o LLM
só redige. A resposta passa pela mesma checagem do relatório: número que não
está no contexto (nem na pergunta) gera uma nova tentativa e, se persistir,
volta marcado em `numeros_nao_verificados` para a tela avisar.
"""

import json
import logging
import re
import sqlite3
from datetime import datetime

from config import settings
from src.api import consultas
from src.carteira import servico
from src.relatorio.checagem import numeros_sem_origem
from src.relatorio.insumos import num, pct

logger = logging.getLogger(__name__)

AVISO = "Não é recomendação de investimento: material de apoio, a decisão e a execução são suas."
MAX_ATIVOS = 5
MAX_RELATORIO = 6000

INSTRUCOES_CHAT = """Você é o assistente de um sistema pessoal de análise de ações da B3. Responda em português do Brasil,
de forma direta e curta (no máximo uns 3 parágrafos ou uma lista curta), em Markdown.

REGRAS OBRIGATÓRIAS:
- Use SOMENTE o CONTEXTO abaixo. Todo número da resposta deve estar no CONTEXTO, copiado exatamente
  (mesmo formato). Não calcule, não some, não arredonde, não converta.
- Se a pergunta pedir algo que não está no contexto, diga que o sistema não tem esse dado.
- Não use conhecimento externo sobre empresas, preços ou notícias.
- Não dê ordens ("compre", "venda"). Descreva o que o ranking e os sinais mostram e a regra do sistema
  (top 30 = indicação de compra; carteira abaixo da posição 60 = considerar vender), lembrando que a regra
  empatou com Ibovespa/CDI no backtest.
- O ranking marcado como provisório é intradiário e pode mudar até o fechamento.
"""

INSTRUCOES_PORQUE = """Explique em 2 a 4 frases, em português do Brasil, por que a ação abaixo está nessa posição do
ranking do sistema, usando SOMENTE os fatores do JSON (que já dizem se favorecem ou pesam contra).
Copie números exatamente como estão. Não use conhecimento externo, não calcule, não dê ordem de compra ou venda.

JSON:
"""


def _cliente_padrao():
    from src.sinais.eventos import ClienteGemini
    return ClienteGemini(tentativas=2)  # chat não pode esperar minutos: falha rápido com 503


# ---------------------------------------------------------------- contexto

def tickers_citados(conn: sqlite3.Connection, texto: str) -> list[str]:
    """Tickers no texto (PETR4, petr4) ou radical (PETR) de papel conhecido."""
    conhecidos = {r[0] for r in conn.execute("SELECT ticker FROM ativos")}
    achados = []
    for palavra in re.findall(r"\b[A-Za-z][A-Za-z0-9]{3}\d{0,2}\b", texto):
        p = palavra.upper()
        candidatos = [p] if p in conhecidos else sorted(t for t in conhecidos if t[:4] == p and len(p) == 4)
        for t in candidatos[:2]:
            if t not in achados:
                achados.append(t)
    return achados[:MAX_ATIVOS]


def _ativo(conn, ticker: str, vigor: dict | None, px: dict, rank: dict) -> dict:
    p = px.get(ticker, {})
    sinais = consultas.sinais_atuais(conn, ticker)
    posicao = rank.get(ticker, (None, None))
    return {
        "ticker": ticker, "nome": consultas.nomes(conn).get(ticker),
        "posicao_ranking": posicao[0], "de": len(rank) or None, "score": num(posicao[1], 3),
        "preco": num(p.get("preco")), "variacao_dia": pct(p.get("variacao_dia")),
        "fatores_que_mais_pesaram": [f["texto"] for f in consultas.fatores(conn, vigor, [ticker]).get(ticker, [])],
        "sinais_em": sinais["data"],
        "sinais": {s["nome"]: f"{num(s['valor'], 3)} ({s['nivel']}"
                   + (f", percentil {round(s['percentil'] * 100)})" if s["percentil"] is not None else ")")
                   for s in sinais["sinais"]},
        "noticias_recentes": [{"titulo": n["titulo"], "data": n["disponivel_em"][:10],
                               "sentimento": num(n["sentimento"])} for n in consultas.noticias(conn, ticker, 5)],
        "fatos_relevantes": [{k: f[k] for k in ("data", "assunto", "evento", "direcao", "resumo")}
                             for f in consultas.fatos_relevantes(conn, ticker, n=3)],
    }


def contexto(conn: sqlite3.Connection, pergunta: str) -> dict:
    vigor = consultas.ranking_em_vigor(conn)
    px = consultas.precos(conn)
    rank = consultas.posicoes_ranking(conn, vigor)
    nm = consultas.nomes(conn)
    cart = servico.montar(conn)
    ibov = consultas.ibovespa(conn)
    mac = consultas.macro(conn)
    citados = tickers_citados(conn, pergunta)
    relatorio = ""
    arquivos = sorted((settings.BASE_DIR / "relatorios").glob("*.md"))
    if arquivos:
        relatorio = arquivos[-1].read_text(encoding="utf-8")[:MAX_RELATORIO]
    return {
        "agora": datetime.now(consultas.FUSO_B3).strftime("%Y-%m-%d %H:%M"),
        "mercado_aberto": consultas.mercado_aberto(),
        "ranking": {"data": vigor and vigor["data"], "provisorio": bool(vigor and vigor["provisorio"]),
                    "acoes_no_universo": len(rank)},
        "ibovespa": ibov and {"nome": ibov["nome"], "valor": num(ibov["valor"]), "variacao_dia": pct(ibov["variacao_dia"])},
        "macro": {k: {"valor": num(v["valor"], 4 if k == "ptax_venda" else 2), "referencia": v["referencia"]}
                  for k, v in mac.items()},
        "top_30": [{"posicao": pos, "ticker": t, "nome": nm.get(t), "score": num(score, 3)}
                   for t, (pos, score) in sorted(rank.items(), key=lambda x: x[1][0])[:consultas.TOP_COMPRA]],
        "carteira": {
            "posicoes": [{"ticker": p["ticker"], "quantidade": num(p["quantidade"], 0), "preco_medio": num(p["preco_medio"]),
                          "preco": num(p["preco"]), "ganho_pct": pct(p["ganho_pct"]), "variacao_dia": pct(p["variacao_dia"]),
                          "posicao_ranking": p["posicao_ranking"], "leitura": p["leitura"]} for p in cart["posicoes"]],
            "totais": {"valor": num(cart["totais"]["valor"]), "ganho_pct": pct(cart["totais"]["ganho_pct"]),
                       "ganho_dia": num(cart["totais"]["ganho_dia"]),
                       "ibovespa_desde_inicio": pct(cart["totais"]["ibovespa_desde_inicio"])},
        },
        "ativos_citados": [_ativo(conn, t, vigor, px, rank) for t in citados],
        "relatorio_do_dia": relatorio,
    }


# ---------------------------------------------------------------- respostas

def _redigir(llm, prompt: str, referencia: dict, tentativas: int = 2) -> tuple[str, list[str]]:
    problemas: list[str] = []
    texto = ""
    for _ in range(tentativas):
        pedido = prompt if not problemas else (
            prompt + "\n\nATENÇÃO: a resposta anterior citou números que NÃO estão no contexto: "
            + ", ".join(problemas) + ". Responda de novo sem eles.")
        texto = llm.classificar(pedido, schema=None).strip()
        problemas = numeros_sem_origem(texto, referencia)
        if not problemas:
            break
    return texto, problemas


def responder(conn: sqlite3.Connection, mensagens: list[dict], llm=None) -> dict:
    """mensagens: [{"papel": "usuario"|"assistente", "texto": ...}], a última é a pergunta."""
    llm = llm or _cliente_padrao()
    pergunta = mensagens[-1]["texto"]
    ctx = contexto(conn, " ".join(m["texto"] for m in mensagens if m["papel"] == "usuario")[-2000:])
    historico = "\n".join(f"{'Usuário' if m['papel'] == 'usuario' else 'Assistente'}: {m['texto']}"
                          for m in mensagens[-9:-1])
    prompt = (INSTRUCOES_CHAT + "\nCONTEXTO:\n" + json.dumps(ctx, ensure_ascii=False, indent=1)
              + (f"\n\nCONVERSA ATÉ AGORA:\n{historico}" if historico else "") + f"\n\nPERGUNTA: {pergunta}")
    referencia = {"contexto": ctx, "conversa": [m["texto"] for m in mensagens]}
    texto, problemas = _redigir(llm, prompt, referencia)
    return {"resposta": texto, "numeros_nao_verificados": problemas, "ativos_citados": [a["ticker"] for a in ctx["ativos_citados"]],
            "aviso": AVISO}


_cache_porque: dict[tuple, dict] = {}


def porque(conn: sqlite3.Connection, ticker: str, llm=None) -> dict:
    vigor = consultas.ranking_em_vigor(conn)
    chave = (ticker, vigor and vigor["data"], vigor and vigor["versao"], vigor and vigor["atualizado_em"])
    if chave in _cache_porque:
        return _cache_porque[chave]
    rank = consultas.posicoes_ranking(conn, vigor)
    if ticker not in rank:
        raise KeyError(ticker)
    pos, score = rank[ticker]
    dados = {"ticker": ticker, "posicao": pos, "de": len(rank), "score": num(score, 3),
             "ranking_provisorio": vigor["provisorio"],
             "fatores": [f["texto"] for f in consultas.fatores(conn, vigor, [ticker], n=6).get(ticker, [])]}
    texto, problemas = _redigir(llm or _cliente_padrao(), INSTRUCOES_PORQUE + json.dumps(dados, ensure_ascii=False), dados)
    saida = {"texto": texto, "numeros_nao_verificados": problemas, "dados": dados, "aviso": AVISO}
    if not problemas:
        _cache_porque[chave] = saida
    return saida
