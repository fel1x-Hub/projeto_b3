"""Documentos periódicos e eventuais (IPE) da CVM: fatos relevantes,
comunicados ao mercado, avisos aos acionistas e releases de resultados.

Arquivo: DOC/IPE/DADOS/ipe_cia_aberta_{ano}.zip (um por ano de entrega).
Guarda metadados e o link de download; o PDF só é baixado na etapa 3, quando
o LLM precisar ler o documento.

`disponivel_em` = Data_Entrega às 23:59:59 BRT: o arquivo só informa o dia da
entrega, não a hora; supor o fim do dia é o conservador.
Cada reapresentação (Versao) é um documento próprio (`id_externo` =
protocolo + versão), com a sua própria data de entrega.
"""

import logging
import sqlite3
from datetime import date, time

from src.coleta import cvm_comum
from src.coleta.cliente_http import ClienteHTTP, NaoEncontrado
from src.coleta.persistencia import salvar
from src.db.tempo import hoje_brt, iso_brt

logger = logging.getLogger(__name__)

FONTE = "cvm_ipe"
CHAVES = ["fonte", "id_externo"]
CATEGORIAS = {
    "Fato Relevante": "fato_relevante",
    "Comunicado ao Mercado": "comunicado",
    "Aviso aos Acionistas": "aviso_acionistas",
    "Dados Econômico-Financeiros": "dados_economico_financeiros",  # releases de resultado
}


def _data_ou_none(texto: str) -> date | None:
    try:
        return date.fromisoformat((texto or "").strip())
    except ValueError:
        return None


def converter(linhas: list[dict], empresas: dict[str, list[str]], desde: date) -> list[dict]:
    registros = []
    for r in linhas:
        tipo = CATEGORIAS.get(r["Categoria"])
        if tipo is None or not r["Codigo_CVM"]:
            continue
        tickers = empresas.get(cvm_comum.normalizar_codigo_cvm(r["Codigo_CVM"]))
        entrega = _data_ou_none(r["Data_Entrega"])
        if not tickers or entrega is None or entrega < desde:
            continue
        referencia = _data_ou_none(r["Data_Referencia"])
        registros.append({
            "tipo": tipo,
            "ticker": tickers[0],  # empresa com vários tickers acompanhados: o primeiro em ordem alfabética
            "data_referencia": referencia.isoformat() if referencia else None,
            "fonte": FONTE,
            "id_externo": f"{r['Protocolo_Entrega']}-v{r['Versao']}",
            "url": r["Link_Download"] or None,
            "assunto": (r["Assunto"] or "").strip() or None,
            "disponivel_em": iso_brt(entrega, time(23, 59, 59)),
        })
    return registros


def coletar(conn: sqlite3.Connection, desde: date, http: ClienteHTTP | None = None) -> int:
    http = http or ClienteHTTP()
    empresas = cvm_comum.empresas_acompanhadas(conn)
    if not empresas:
        logger.warning("Nenhum ativo com código CVM; rode o cadastro CVM antes")
        return 0

    novos = 0
    for ano in range(desde.year, hoje_brt().year + 1):
        try:
            arquivo = cvm_comum.baixar(http, f"DOC/IPE/DADOS/ipe_cia_aberta_{ano}.zip", ano=ano)
        except NaoEncontrado:
            logger.warning("IPE %d ainda não publicado", ano)
            continue
        registros = converter(cvm_comum.ler_csv(arquivo, f"ipe_cia_aberta_{ano}.csv"), empresas, desde)
        novos += salvar(conn, "documentos", CHAVES, registros, fonte=FONTE).novos
    return novos
