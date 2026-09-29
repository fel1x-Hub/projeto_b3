"""Mede a qualidade do modelo de sentimento contra os rótulos de
rotulos/sentimento.csv e grava o resultado em docs/sentimento_avaliacao.md.

Uso:
    python scripts/avaliar_sentimento.py

Antes de medir, classifica as notícias que ainda não têm score (o modelo é
baixado na primeira execução, ~400 MB).
"""

import argparse
import csv
import logging
import sqlite3
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from src.db.conexao import conectar  # noqa: E402
from src.db.migracoes import migrar  # noqa: E402
from src.logging_config import configurar_logging  # noqa: E402
from src.sinais import avaliacao, sentimento  # noqa: E402

logger = logging.getLogger("avaliar_sentimento")
ROTULOS = settings.BASE_DIR / "rotulos" / "sentimento.csv"
SAIDA = settings.BASE_DIR / "docs" / "sentimento_avaliacao.md"
F1_MINIMO = 0.6  # abaixo disso, testar classificação por LLM (ver docs/sinais.md)


def _tabela_metricas(nome: str, m: dict) -> list[str]:
    linhas = [f"### {nome}", "",
              f"Acurácia **{m['acuracia']:.1%}** · F1 macro **{m['f1_macro']:.3f}** · n = {m['n']}", "",
              "| Classe | Precisão | Revocação | F1 | Suporte |", "|---|---|---|---|---|"]
    for c, v in m["por_classe"].items():
        linhas.append(f"| {c} | {v['precisao']:.2f} | {v['revocacao']:.2f} | {v['f1']:.2f} | {v['suporte']} |")
    return linhas + [""]


def relatorio(conn: sqlite3.Connection, caminho_rotulos: Path, modelo: str = sentimento.MODELO) -> tuple[str, dict]:
    with open(caminho_rotulos, encoding="utf-8", newline="") as f:
        rotulos = {int(r["noticia_id"]): r for r in csv.DictReader(f)}
    previstos = dict(conn.execute(
        "SELECT noticia_id, rotulo FROM sentimento_noticias WHERE modelo = ?", (modelo,)).fetchall())
    ids = [i for i in rotulos if i in previstos]
    faltando = len(rotulos) - len(ids)
    reais = [rotulos[i]["rotulo"] for i in ids]
    prev = [previstos[i] for i in ids]
    m = avaliacao.metricas(reais, prev)
    base = avaliacao.metricas(reais, ["neutro"] * len(reais))
    quem = sorted({r["rotulado_por"] for r in rotulos.values()})

    md = [f"# Avaliação do sentimento ({date.today():%d/%m/%Y})", "",
          f"- **Modelo:** `{modelo}`, classificando o título.",
          f"- **Referência:** `rotulos/sentimento.csv`, com {len(ids)} notícias rotuladas por: {', '.join(quem)}."
          f" O critério está em `rotulos/README.md`.",
          f"- **Notícias sem classificação do modelo:** {faltando}.", ""]
    md += _tabela_metricas("Modelo", m)
    md += _tabela_metricas("Linha de base (sempre 'neutro')", base)
    md += ["### Matriz de confusão (linhas = referência, colunas = modelo)", "",
           "| | " + " | ".join(avaliacao.CLASSES) + " |", "|---|---|---|---|"]
    for r in avaliacao.CLASSES:
        md.append(f"| **{r}** | " + " | ".join(str(m["matriz"][r][p]) for p in avaliacao.CLASSES) + " |")
    veredito = ("adequada" if m["f1_macro"] >= F1_MINIMO else
                f"insuficiente (F1 macro < {F1_MINIMO}): testar classificação por LLM")
    md += ["", f"**Veredito:** qualidade {veredito}.", "",
           "### Divergências", "", "| id | título | referência | modelo |", "|---|---|---|---|"]
    for i in ids:
        if rotulos[i]["rotulo"] != previstos[i]:
            titulo = rotulos[i]["titulo"].replace("|", "/")
            md.append(f"| {i} | {titulo} | {rotulos[i]['rotulo']} | {previstos[i]} |")
    return "\n".join(md) + "\n", m


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    configurar_logging()
    conn = conectar(args.db)
    try:
        migrar(conn)
        sentimento.classificar_pendentes(conn)
        texto, m = relatorio(conn, ROTULOS)
    finally:
        conn.close()
    SAIDA.write_text(texto, encoding="utf-8")
    print(texto)
    logger.info("Relatório salvo em %s", SAIDA)
    return 0


if __name__ == "__main__":
    sys.exit(main())
