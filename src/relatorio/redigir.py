"""Redação do relatório diário pelo LLM (Gemini), a partir dos insumos
calculados em código. O LLM NÃO recalcula números: só copia os dos insumos.
A checagem automática rejeita o texto se aparecer número sem origem; nesse
caso o relatório é refeito uma vez com a lista dos números problemáticos.
"""

import json
import logging

from src.relatorio.checagem import numeros_sem_origem

logger = logging.getLogger(__name__)

AVISO = ("*Material de apoio à decisão gerado automaticamente. Não é recomendação de investimento. "
         "O sistema nunca envia ordens; decisões e execução são do usuário.*")

INSTRUCOES = """Você escreve o relatório diário de um sistema pessoal de análise de ações da B3.
Escreva em português do Brasil, em Markdown, de forma clara e direta, SEM inventar nada.

REGRAS OBRIGATÓRIAS:
- Use SOMENTE os dados do JSON abaixo. Todo número que aparecer no texto deve estar no JSON,
  copiado EXATAMENTE como está escrito (mesmo formato, mesmas casas decimais).
- Não calcule, não arredonde, não converta e não some nada. Se não houver o número, não cite número.
- Não use conhecimento externo sobre as empresas ou o mercado.
- Não diga "compre" ou "venda": descreva o que os sinais mostram.

ESTRUTURA (títulos em ##):
## Resumo do dia e contexto macro
## Topo do ranking (o que os sinais favorecem)   -> para cada ação: posição e os fatores que mais pesaram
## Fundo do ranking (o que os sinais penalizam)
## Notícias e fatos relevantes
## Mudanças no top 30
## Riscos e pontos de atenção                     -> inclua o contexto_validacao do JSON
## Paper trading

JSON:
"""


def escrever(llm, insumos: dict, tentativas: int = 2) -> tuple[str, list[str]]:
    """(texto em Markdown com aviso, números sem origem). Lista vazia = aprovado."""
    prompt = INSTRUCOES + json.dumps(insumos, ensure_ascii=False, indent=1)
    problemas: list[str] = []
    texto = ""
    for tentativa in range(tentativas):
        pedido = prompt if not problemas else (
            prompt + "\n\nATENÇÃO: a versão anterior citou números que NÃO estão no JSON: "
            + ", ".join(problemas) + ". Reescreva sem eles, usando só números do JSON.")
        texto = llm.classificar(pedido, schema=None).strip()
        problemas = numeros_sem_origem(texto, insumos)
        if not problemas:
            break
        logger.warning("Relatório com números sem origem (tentativa %d): %s", tentativa + 1, problemas)
    titulo = f"# Relatório diário — {insumos['data'][8:10]}/{insumos['data'][5:7]}/{insumos['data'][:4]}\n\n"
    return titulo + texto + "\n\n" + AVISO + "\n", problemas
