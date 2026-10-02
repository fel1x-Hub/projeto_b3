"""Alertas do dia para a carteira e o top 30 (etapa 7.3 e regra 16)."""

import sqlite3
from datetime import datetime, timedelta, timezone

from src.api import consultas

VARIACAO_FORTE = 0.05      # |variação no dia| que vira alerta para papel da carteira
DIAS_FATOS = 3             # fatos relevantes recentes
DADO_VELHO = timedelta(minutes=45)


def gerar(conn: sqlite3.Connection, carteira: dict, agora: datetime | None = None) -> list[dict]:
    agora = agora or datetime.now(timezone.utc)
    alertas: list[dict] = []
    vigor = carteira["ranking"]
    tenho = {p["ticker"]: p for p in carteira["posicoes"]}

    # 1) papel da carteira que saiu do top 30 / caiu abaixo de 60, comparado ao ranking oficial anterior
    if vigor:
        anterior = conn.execute("SELECT MAX(data) FROM ranking WHERE versao_modelo = ? AND data < ?",
                                (consultas.OFICIAL, vigor["data"])).fetchone()[0]
        antes = consultas.posicoes_ranking(conn, {"data": anterior, "versao": consultas.OFICIAL}) if anterior else {}
        for t, p in tenho.items():
            agora_pos, antes_pos = p["posicao_ranking"], antes.get(t, (None,))[0]
            if agora_pos is None or antes_pos is None:
                continue
            if antes_pos <= consultas.TOP_COMPRA < agora_pos:
                alertas.append({"tipo": "ranking", "nivel": "atencao", "ticker": t,
                                "texto": f"{t} saiu do top {consultas.TOP_COMPRA} (posição {antes_pos} → {agora_pos})"})
            if antes_pos <= consultas.LIMITE_OBSERVAR < agora_pos:
                alertas.append({"tipo": "ranking", "nivel": "alerta", "ticker": t,
                                "texto": f"{t} caiu abaixo da posição {consultas.LIMITE_OBSERVAR}: leitura "
                                         f"'considerar vender' ({antes_pos} → {agora_pos})"})
            if agora_pos <= consultas.TOP_COMPRA < antes_pos:
                alertas.append({"tipo": "ranking", "nivel": "info", "ticker": t,
                                "texto": f"{t} entrou no top {consultas.TOP_COMPRA} (posição {antes_pos} → {agora_pos})"})

    # 2) variação forte no dia em papel da carteira
    for t, p in tenho.items():
        if p["variacao_dia"] is not None and abs(p["variacao_dia"]) >= VARIACAO_FORTE:
            alertas.append({"tipo": "preco", "nivel": "atencao", "ticker": t,
                            "texto": f"{t} {p['variacao_dia'] * 100:+.1f}% no dia".replace(".", ",")})

    # 3) fatos relevantes recentes da carteira ou do top 30
    interesse = set(tenho)
    if vigor:
        interesse |= {t for t, (pos, _) in consultas.posicoes_ranking(conn, vigor).items()
                      if pos <= consultas.TOP_COMPRA}
    desde = (agora - timedelta(days=DIAS_FATOS)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    for f in consultas.fatos_relevantes(conn, desde=desde, n=200):
        if f["ticker"] in interesse:
            alertas.append({"tipo": "fato_relevante", "nivel": "info", "ticker": f["ticker"],
                            "texto": f"Fato relevante de {f['ticker']} em {f['data']}: "
                                     f"{f['resumo'] or f['assunto'] or 'sem resumo'}",
                            "url": f["url"], "direcao": f["direcao"]})

    # 4) fonte de dados com falha ou cotação parada durante o pregão (regra 15)
    for s in consultas.status_fontes(conn):
        if s["status"] == "falha":
            alertas.append({"tipo": "dados", "nivel": "atencao", "ticker": None,
                            "texto": f"Coleta '{s['fonte']}' falhou na última execução ({s['inicio']}): "
                                     "a tela mostra o último dado válido"})
    if consultas.mercado_aberto(agora):
        r = conn.execute("SELECT MAX(coletado_em) FROM cotacao_atual").fetchone()[0]
        if r is None or agora - datetime.fromisoformat(r) > DADO_VELHO:
            alertas.append({"tipo": "dados", "nivel": "atencao", "ticker": None,
                            "texto": f"Cotação do momento sem atualização desde {r or 'nunca'} (agendador parado?)"})
    return alertas
