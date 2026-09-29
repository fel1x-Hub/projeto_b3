"""Demonstrações financeiras estruturadas da CVM: DFP (anual) e ITR (trimestral).

Arquivos: DOC/{DFP,ITR}/DADOS/{dfp,itr}_cia_aberta_{ano}.zip (ano de referência),
cada um com um índice (data de entrega por documento e versão), um CSV por
demonstrativo e a composição do capital (número de ações).

- Guarda só o exercício "ÚLTIMO" (o "PENÚLTIMO" é a coluna comparativa).
- Versões: o índice lista todas, mas os arquivos de contas só trazem os
  valores da ÚLTIMA versão de cada documento. Então, no histórico, cada
  documento só fica disponível a partir da entrega da última versão
  (conservador). Daqui em diante, como a coleta roda sempre, a v1 é guardada
  quando sai e a v2 entra depois sem apagar a v1: o ponto-no-tempo se acumula.
- `valor` em reais: VL_CONTA x 1000 quando ESCALA_MOEDA = MIL.
- `disponivel_em` = DT_RECEB (entrega) às 23:59:59 BRT (só há a data).
- DMPL e DRA ficam de fora (formato em colunas / não usados nos indicadores).

Uma versão entregue nunca muda (correção = versão nova); por isso um documento
já presente no banco é pulado inteiro, e documentos novos são inseridos em lote.
A CVM repete algumas linhas idênticas; as repetições são descartadas.
"""

import logging
import sqlite3
from datetime import date, time

from src.coleta import cvm_comum
from src.coleta.cliente_http import ClienteHTTP, NaoEncontrado
from src.db.tempo import agora_utc_iso, hoje_brt, iso_brt

logger = logging.getLogger(__name__)

FONTE = "cvm_dfp_itr"
DEMONSTRATIVOS = ("BPA", "BPP", "DRE", "DFC_MD", "DFC_MI", "DVA")
ESCALAS = {"MIL": 1000.0, "UNIDADE": 1.0}
COLUNAS_CAPITAL = {
    "QT_ACAO_ORDIN_CAP_INTEGR": "Ações ordinárias (capital integralizado)",
    "QT_ACAO_PREF_CAP_INTEGR": "Ações preferenciais (capital integralizado)",
    "QT_ACAO_TOTAL_CAP_INTEGR": "Total de ações (capital integralizado)",
    "QT_ACAO_ORDIN_TESOURO": "Ações ordinárias em tesouraria",
    "QT_ACAO_PREF_TESOURO": "Ações preferenciais em tesouraria",
    "QT_ACAO_TOTAL_TESOURO": "Total de ações em tesouraria",
}
COLUNAS = ("codigo_cvm", "tipo_doc", "data_referencia", "versao", "demonstrativo", "consolidado",
           "data_ini", "data_fim", "cd_conta", "ds_conta", "valor", "disponivel_em", "coletado_em")

Documento = tuple[str, str, str, int]  # (codigo_cvm, tipo_doc, data_referencia, versao)


def _indice(linhas: list[dict], tipo_doc: str, empresas: set[str]) -> tuple[dict[Documento, str], dict[str, str]]:
    """({documento: disponivel_em}, {cnpj: codigo_cvm}) das empresas acompanhadas,
    só com a versão mais recente de cada documento (a única com valores nos arquivos)."""
    ultima: dict[tuple, tuple[int, str]] = {}
    cnpj_para_codigo = {}
    for r in linhas:
        codigo = cvm_comum.normalizar_codigo_cvm(r["CD_CVM"])
        if codigo not in empresas or not r["DT_RECEB"]:
            continue
        chave, versao = (codigo, tipo_doc, r["DT_REFER"]), int(r["VERSAO"])
        if chave not in ultima or versao > ultima[chave][0]:
            ultima[chave] = (versao, iso_brt(date.fromisoformat(r["DT_RECEB"]), time(23, 59, 59)))
        cnpj_para_codigo[r["CNPJ_CIA"]] = codigo
    disponivel = {(*chave, versao): disp for chave, (versao, disp) in ultima.items()}
    return disponivel, cnpj_para_codigo


def _linhas_demonstrativo(linhas, tipo_doc, demonstrativo, consolidado, docs_novos) -> list[dict]:
    registros = []
    for r in linhas:
        if not r["ORDEM_EXERC"].startswith("Ú"):  # ÚLTIMO; PENÚLTIMO é comparativo
            continue
        doc = (cvm_comum.normalizar_codigo_cvm(r["CD_CVM"]), tipo_doc, r["DT_REFER"], int(r["VERSAO"]))
        if doc not in docs_novos:
            continue
        valor = float(r["VL_CONTA"]) * ESCALAS[r["ESCALA_MOEDA"]] if r["VL_CONTA"] else None
        registros.append({
            "codigo_cvm": doc[0], "tipo_doc": tipo_doc, "data_referencia": doc[2], "versao": doc[3],
            "demonstrativo": demonstrativo, "consolidado": consolidado,
            "data_ini": r.get("DT_INI_EXERC") or None, "data_fim": r["DT_FIM_EXERC"] or None,
            "cd_conta": r["CD_CONTA"], "ds_conta": r["DS_CONTA"], "valor": valor,
            "disponivel_em": docs_novos[doc],
        })
    return registros


def _linhas_capital(linhas, tipo_doc, cnpj_para_codigo, docs_novos) -> list[dict]:
    registros = []
    for r in linhas:
        codigo = cnpj_para_codigo.get(r["CNPJ_CIA"])
        doc = (codigo, tipo_doc, r["DT_REFER"], int(r["VERSAO"]))
        if codigo is None or doc not in docs_novos:
            continue
        for coluna, descricao in COLUNAS_CAPITAL.items():
            if r.get(coluna) in (None, ""):
                continue
            registros.append({
                "codigo_cvm": codigo, "tipo_doc": tipo_doc, "data_referencia": doc[2], "versao": doc[3],
                "demonstrativo": "CAPITAL", "consolidado": 0, "data_ini": None, "data_fim": doc[2],
                "cd_conta": coluna, "ds_conta": descricao, "valor": float(r[coluna]),
                "disponivel_em": docs_novos[doc],
            })
    return registros


def _documentos_existentes(conn: sqlite3.Connection, tipo_doc: str) -> set[Documento]:
    return {tuple(r) for r in conn.execute(
        "SELECT DISTINCT codigo_cvm, tipo_doc, data_referencia, versao FROM demonstracoes WHERE tipo_doc = ?",
        (tipo_doc,),
    )}


def _inserir(conn: sqlite3.Connection, registros: list[dict]) -> int:
    agora = agora_utc_iso()
    antes = conn.total_changes
    with conn:
        conn.executemany(
            f"INSERT OR IGNORE INTO demonstracoes ({', '.join(COLUNAS)}) VALUES ({', '.join('?' * len(COLUNAS))})",
            [tuple({**r, "coletado_em": agora}[c] for c in COLUNAS) for r in registros],
        )
    inseridos = conn.total_changes - antes
    if inseridos < len(registros):
        logger.info("%d linha(s) repetida(s) no arquivo da CVM descartada(s)", len(registros) - inseridos)
    return inseridos


def coletar_arquivo(conn: sqlite3.Connection, caminho, tipo_doc: str, ano: int, empresas: set[str]) -> int:
    prefixo = f"{tipo_doc.lower()}_cia_aberta"
    disponivel, cnpj_para_codigo = _indice(cvm_comum.ler_csv(caminho, f"{prefixo}_{ano}.csv"), tipo_doc, empresas)
    existentes = _documentos_existentes(conn, tipo_doc)
    docs_novos = {d: v for d, v in disponivel.items() if d not in existentes}
    if not docs_novos:
        return 0

    registros = []
    for demonstrativo in DEMONSTRATIVOS:
        for sufixo, consolidado in (("con", 1), ("ind", 0)):
            linhas = cvm_comum.ler_csv(caminho, f"{prefixo}_{demonstrativo}_{sufixo}_{ano}.csv")
            registros += _linhas_demonstrativo(linhas, tipo_doc, demonstrativo, consolidado, docs_novos)
    registros += _linhas_capital(
        cvm_comum.ler_csv(caminho, f"{prefixo}_composicao_capital_{ano}.csv"), tipo_doc, cnpj_para_codigo, docs_novos
    )
    novos = _inserir(conn, registros)
    logger.info("%s %d: %d documento(s) novo(s), %d linhas", tipo_doc, ano, len(docs_novos), novos)
    return novos


def coletar(conn: sqlite3.Connection, desde: date, http: ClienteHTTP | None = None) -> int:
    """Baixa desde o ano anterior a `desde` (base de comparação para crescimento)."""
    http = http or ClienteHTTP()
    empresas = set(cvm_comum.empresas_acompanhadas(conn))
    if not empresas:
        logger.warning("Nenhum ativo com código CVM; rode o cadastro CVM antes")
        return 0

    novos = 0
    for ano in range(desde.year - 1, hoje_brt().year + 1):
        for tipo_doc in ("DFP", "ITR"):
            caminho_url = f"DOC/{tipo_doc}/DADOS/{tipo_doc.lower()}_cia_aberta_{ano}.zip"
            try:
                arquivo = cvm_comum.baixar(http, caminho_url, ano=ano)
            except NaoEncontrado:
                logger.info("%s %d ainda não publicado", tipo_doc, ano)
                continue
            novos += coletar_arquivo(conn, arquivo, tipo_doc, ano, empresas)
    return novos
