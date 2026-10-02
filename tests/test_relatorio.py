import pytest

from src.relatorio.checagem import normalizar, numeros, numeros_sem_origem
from src.relatorio.redigir import escrever
from src.sinais import descricoes

INSUMOS = {"data": "2026-09-29", "mercado": {"BOVA11 no dia": "+1,03%"},
           "topo": [{"ticker": "PETR4", "posicao": 1, "score": "0,587",
                     "fatores": ["lucro/preço muito alto (percentil 92 do universo): favorece"],
                     "noticias": [{"titulo": "Petrobras paga R$ 31,8 bilhões", "sentimento": "0,85"}]}],
           "contexto_validacao": "+12,4% ao ano, contra Ibovespa +12,8%"}


def test_extrai_numeros_no_formato_brasileiro_e_ignora_tickers():
    assert numeros("PETR4 subiu +1,03% no 3T25 e a Selic está em 13,75; 185.713 pontos") == {"1,03%", "13,75", "185713"}
    assert normalizar("−0,5") == "-0,5"


def test_texto_fiel_aos_insumos_passa():
    texto = "Em 29/09/2026 o BOVA11 subiu +1,03%. PETR4 lidera (posição 1, score 0,587), com percentil 92. R$ 31,8 bi."
    assert numeros_sem_origem(texto, INSUMOS) == []


def test_numero_inventado_e_data_errada_sao_pegos():
    texto = "O BOVA11 subiu 1,5% e o lucro cresceu 40% em 28/09/2026."
    assert set(numeros_sem_origem(texto, INSUMOS)) == {"1,5%", "40%", "28/09/2026"}


class LLMTexto:
    modelo = "falso"

    def __init__(self, respostas):
        self.respostas, self.pedidos = list(respostas), []

    def classificar(self, prompt, schema=None):
        self.pedidos.append(prompt)
        return self.respostas.pop(0)


def test_refaz_quando_ha_numero_sem_origem():
    llm = LLMTexto(["BOVA11 subiu 2%.", "## Resumo do dia\nBOVA11 subiu +1,03%."])
    texto, problemas = escrever(llm, INSUMOS)
    assert problemas == [] and len(llm.pedidos) == 2
    assert "NÃO estão no JSON: 2%" in llm.pedidos[1]
    assert texto.startswith("# Relatório diário — 29/09/2026") and "Não é recomendação" in texto


def test_rejeita_se_persistir():
    llm = LLMTexto(["subiu 2%.", "subiu 3%."])
    _, problemas = escrever(llm, INSUMOS)
    assert problemas == ["3%"]


def test_explicacao_de_fator():
    assert descricoes.explicar("fund_lp", 0.92, 0.01) == "lucro/preço muito alto (percentil 92 do universo): favorece"
    assert descricoes.explicar("vol_63d", 0.1, -0.02) == "volatilidade de 3 meses muito baixa (percentil 10 do universo): pesa contra"
    assert descricoes.explicar("fund_margem_ebitda", 0.5, 0.01).startswith("margem EBITDA mediana")
    assert descricoes.explicar("fund_roe", None, 0.01) == "ROE sem dado: favorece"


def _base_montar(conn):
    from datetime import date
    ts = "2026-09-24T22:00:00+00:00"
    with conn:
        conn.execute("UPDATE ativos SET codigo_cvm = '9512' WHERE ticker = 'PETR4'")
        conn.execute("INSERT INTO ranking VALUES ('2026-09-24', 'PETR4', 0.6, 1, 'lgbm-v2', ?, ?)", (ts, ts))
        # Fato entregue em 22/09 às 23:59:59 BRT = 23/09 02:59:59 UTC.
        conn.execute("INSERT INTO documentos (id, tipo, ticker, fonte, id_externo, url, disponivel_em, coletado_em) "
                     "VALUES (1, 'Fato Relevante', 'PETR4', 'cvm_ipe', 'x', 'http://x', "
                     "'2026-09-23T02:59:59+00:00', ?)", (ts,))
        conn.execute("INSERT INTO eventos_documentos VALUES (1, 'm', 1, 'dividendos', 'positiva', 3, 'Paga dividendos', ?)",
                     (ts,))
        conn.execute("INSERT INTO paper_config VALUES ('inicio', '2026-09-29')")
    return date(2026, 9, 24)


def test_montar_nao_mostra_o_futuro_e_usa_data_de_brasilia(conn):
    from src.relatorio.insumos import montar
    entrada = montar(conn, _base_montar(conn))
    assert entrada["paper_trading"] == "ainda não havia começado nesta data"
    assert entrada["topo"][0]["fatos_relevantes"][0]["data"] == "2026-09-22"


def test_montar_paper_iniciado_sem_pregao_completo(conn):
    from datetime import date
    from src.relatorio.insumos import montar
    _base_montar(conn)
    with conn:
        conn.execute("UPDATE paper_config SET valor = '2026-09-24'")
    assert montar(conn, date(2026, 9, 24))["paper_trading"] == {
        "inicio": "2026-09-24", "retorno_acumulado": "sem pregão completo ainda"}


def _universo(conn, datas):
    ts = "2026-09-30T22:00:00+00:00"
    with conn:
        conn.executemany("INSERT INTO universo VALUES (?, 'PETR4', 1e6, 'liquidez', ?)", [(d, ts) for d in datas])


def test_ranking_preenche_pregoes_perdidos(conn):
    from datetime import date
    from src.ranking import gerar
    _universo(conn, ["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01"])
    assert gerar.datas_pendentes(conn) == [date(2026, 10, 1)]          # sem ranking ainda: só o último
    with conn:
        conn.execute("INSERT INTO ranking VALUES ('2026-09-29', 'PETR4', 0.5, 1, 'lgbm-v2', ?, ?)",
                     ("2026-09-29T22:00:00+00:00", "2026-09-29T22:00:00+00:00"))
    assert gerar.datas_pendentes(conn) == [date(2026, 9, 30), date(2026, 10, 1)]   # PC desligado em 30/09
    assert gerar.datas_pendentes(conn, limite=1) == [date(2026, 10, 1)]


def test_relatorio_preenche_dias_sem_relatorio(conn, tmp_path):
    from datetime import date
    from scripts.gerar_relatorio import pendentes
    _universo(conn, ["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01"])
    (tmp_path / "rejeitados").mkdir()
    (tmp_path / "2026-09-28.md").write_text("x")
    (tmp_path / "rejeitados" / "2026-10-01.md").write_text("x")
    assert pendentes(conn, tmp_path, janela=3) == [date(2026, 9, 29), date(2026, 9, 30)]
