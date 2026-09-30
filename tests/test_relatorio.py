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
    assert descricoes.explicar("vol_63d", 0.1, -0.02).endswith("pesa contra")
