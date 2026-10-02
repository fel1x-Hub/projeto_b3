"""Publica o "modelo de leitura" do SQLite de trabalho no Postgres da nuvem (etapa 8).

Uso:
    python scripts/publicar_nuvem.py                 # usa DATABASE_URL do ambiente/.env
    python scripts/publicar_nuvem.py --completo      # recopia tudo (1ª vez ou reparo)

Roda no fim do pipeline noturno e de cada ciclo intradiário (GitHub Actions).
Só copia o que as telas leem (~200 MB, cabe no Neon grátis):
- tabelas pequenas: trocadas inteiras (TRUNCATE + COPY), dentro de uma transação;
- tabelas grandes (cotações, ranking, fatores): só a janela recente é regravada.
As tabelas carteira_* (dados pessoais) existem só na nuvem e NUNCA são tocadas aqui.
"""

import argparse
import logging
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from src.db import schema_nuvem  # noqa: E402
from src.db.conexao import conectar  # noqa: E402
from src.db.tempo import agora_utc_iso  # noqa: E402
from src.logging_config import configurar_logging  # noqa: E402

logger = logging.getLogger("publicar_nuvem")

JANELA_DIAS = 15            # tabelas grandes: regrava a partir de (último dia publicado - 15)
SINAIS_DATAS = 10           # sinais/universo: só os últimos pregões (tela da ação usa o último)


@dataclass
class Tabela:
    nome: str
    colunas: str
    origem: str                  # SELECT no SQLite (mesma ordem de colunas)
    janela: str | None = None    # coluna de data para cópia incremental; None = troca inteira
    retencao_dias: int | None = None


def tabelas(hoje: date) -> list[Tabela]:
    ate_noticias = (hoje - timedelta(days=120)).isoformat()
    ate_fatos = (hoje - timedelta(days=3 * 365)).isoformat()
    ultimas = f"(SELECT DISTINCT data FROM universo ORDER BY data DESC LIMIT {SINAIS_DATAS})"
    return [
        Tabela("ativos", "ticker, nome, setor, cnpj, codigo_cvm, ativo",
               "SELECT ticker, nome, setor, cnpj, codigo_cvm, ativo FROM ativos"),
        Tabela("macro", "serie, data, valor, disponivel_em", "SELECT serie, data, valor, disponivel_em FROM macro"),
        Tabela("proventos", "ticker, tipo, data_ex, valor, fator, fonte",
               "SELECT ticker, tipo, data_ex, valor, fator, fonte FROM proventos"),
        Tabela("universo", "data, ticker", f"SELECT data, ticker FROM universo WHERE data IN {ultimas}"),
        Tabela("sinais", "ticker, data, nome, valor",
               f"SELECT ticker, data, nome, valor FROM sinais WHERE data IN {ultimas}"),
        Tabela("cotacao_atual", "ticker, preco, fechamento_anterior, variacao_dia, horario_cotacao, fonte, coletado_em",
               "SELECT ticker, preco, fechamento_anterior, variacao_dia, horario_cotacao, fonte, coletado_em FROM cotacao_atual"),
        Tabela("noticias", "id, titulo, url, fonte, disponivel_em",
               f"SELECT id, titulo, url, fonte, disponivel_em FROM noticias WHERE disponivel_em >= '{ate_noticias}'"),
        Tabela("noticias_ativos", "noticia_id, ticker",
               "SELECT na.noticia_id, na.ticker FROM noticias_ativos na JOIN noticias n ON n.id = na.noticia_id "
               f"WHERE n.disponivel_em >= '{ate_noticias}'"),
        Tabela("sentimento_noticias", "noticia_id, modelo, score",
               "SELECT s.noticia_id, s.modelo, s.score FROM sentimento_noticias s JOIN noticias n ON n.id = s.noticia_id "
               f"WHERE n.disponivel_em >= '{ate_noticias}'"),
        Tabela("documentos", "id, tipo, ticker, assunto, url, disponivel_em",
               "SELECT id, tipo, ticker, assunto, url, disponivel_em FROM documentos "
               f"WHERE tipo = 'fato_relevante' AND disponivel_em >= '{ate_fatos}'"),
        Tabela("eventos_documentos", "documento_id, modelo, versao_prompt, tipo_evento, direcao, resumo",
               "SELECT e.documento_id, e.modelo, e.versao_prompt, e.tipo_evento, e.direcao, e.resumo "
               "FROM eventos_documentos e JOIN documentos d ON d.id = e.documento_id "
               f"WHERE d.tipo = 'fato_relevante' AND d.disponivel_em >= '{ate_fatos}'"),
        Tabela("execucoes_coleta", "id, fonte, inicio, fim, status, registros_novos, erro",
               "SELECT id, fonte, inicio, fim, status, registros_novos, erro FROM execucoes_coleta "
               "WHERE id > (SELECT MAX(id) - 500 FROM execucoes_coleta)"),
        Tabela("relatorios", "data, markdown, gerado_em", "SELECT data, markdown, gerado_em FROM relatorios"),
        Tabela("cotacoes", "ticker, data, abertura, maxima, minima, fechamento, volume",
               "SELECT ticker, data, abertura, maxima, minima, fechamento, volume FROM cotacoes", janela="data"),
        Tabela("ranking", "data, ticker, score, posicao, versao_modelo, disponivel_em, calculado_em",
               "SELECT data, ticker, score, posicao, versao_modelo, disponivel_em, calculado_em FROM ranking "
               "WHERE versao_modelo IN ('lgbm-v1', 'wf-lgbm-v1', 'lgbm-v1-provisorio')", janela="data"),
        Tabela("ranking_fatores", "data, ticker, versao_modelo, sinal, percentil, contribuicao",
               "SELECT data, ticker, versao_modelo, sinal, percentil, contribuicao FROM ranking_fatores",
               janela="data", retencao_dias=90),
    ]


def _copiar(cur, t: Tabela, linhas) -> int:
    n = 0
    with cur.copy(f"COPY {t.nome} ({t.colunas}) FROM STDIN") as cp:
        for linha in linhas:
            cp.write_row(tuple(linha))
            n += 1
    return n


def publicar_tabela(sqlite: sqlite3.Connection, pg, t: Tabela, completo: bool = False) -> int:
    with pg.transaction(), pg.cursor() as cur:
        if t.janela is None or completo:
            cur.execute(f"TRUNCATE {t.nome}")
            n = _copiar(cur, t, sqlite.execute(t.origem))
        else:
            ultimo = cur.execute(f"SELECT MAX({t.janela}) FROM {t.nome}").fetchone()[0]
            if ultimo is None:
                n = _copiar(cur, t, sqlite.execute(t.origem))
            else:
                corte = (date.fromisoformat(ultimo[:10]) - timedelta(days=JANELA_DIAS)).isoformat()
                cur.execute(f"DELETE FROM {t.nome} WHERE {t.janela} >= %s", (corte,))
                filtro = " AND " if " WHERE " in t.origem else " WHERE "
                n = _copiar(cur, t, sqlite.execute(t.origem + f"{filtro}{t.janela} >= ?", (corte,)))
        if t.retencao_dias:
            ultimo = cur.execute(f"SELECT MAX({t.janela}) FROM {t.nome}").fetchone()[0]
            if ultimo:
                limite = (date.fromisoformat(ultimo[:10]) - timedelta(days=t.retencao_dias)).isoformat()
                cur.execute(f"DELETE FROM {t.nome} WHERE {t.janela} < %s", (limite,))
        cur.execute("INSERT INTO publicacoes VALUES (%s, %s, %s) ON CONFLICT (tabela) DO UPDATE "
                    "SET publicado_em = excluded.publicado_em, linhas = excluded.linhas", (t.nome, agora_utc_iso(), n))
    return n


def publicar(sqlite: sqlite3.Connection, url: str, completo: bool = False, so: list[str] | None = None) -> dict:
    import psycopg

    from src.db.nuvem import ConexaoPG
    resultado = {}
    with psycopg.connect(url, autocommit=True) as pg:
        schema_nuvem.garantir(ConexaoPG(pg))
        for t in tabelas(date.today()):
            if so and t.nome not in so:
                continue
            inicio = time.monotonic()
            resultado[t.nome] = publicar_tabela(sqlite, pg, t, completo)
            logger.info("Nuvem: %-20s %8d linhas (%.1fs)", t.nome, resultado[t.nome], time.monotonic() - inicio)
    return resultado


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--completo", action="store_true", help="recopia tudo (1ª publicação ou reparo)")
    parser.add_argument("--so", nargs="*", help="publicar só estas tabelas (ex.: cotacao_atual ranking)")
    args = parser.parse_args(argv)
    configurar_logging()
    url = os.getenv("DATABASE_URL", "")
    if not url:
        logger.error("DATABASE_URL ausente: defina a URL do Postgres (Neon) no ambiente ou no .env")
        return 1
    sqlite = conectar(settings.DB_PATH)
    try:
        r = publicar(sqlite, url, args.completo, args.so)
    finally:
        sqlite.close()
    print(f"Publicado na nuvem: {sum(r.values())} linhas em {len(r)} tabelas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
