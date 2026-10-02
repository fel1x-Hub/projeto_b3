"""Gera o relatório diário (Markdown) de um ou mais pregões.

Uso:
    python scripts/gerar_relatorio.py                 # pregões recentes ainda sem relatório (o último, normalmente)
    python scripts/gerar_relatorio.py --data 2026-09-25
    python scripts/gerar_relatorio.py --ultimos 5

Todos os números vêm dos insumos calculados em código; o Gemini só redige.
Relatório com número sem origem é refeito uma vez e, se persistir, vai para
relatorios/rejeitados/ (não é publicado).
"""

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from src.db.conexao import conectar  # noqa: E402
from src.db.migracoes import migrar  # noqa: E402
from src.db.tempo import agora_utc_iso  # noqa: E402
from src.logging_config import configurar_logging  # noqa: E402
from src.ranking import gerar  # noqa: E402
from src.relatorio import insumos, redigir  # noqa: E402
from src.sinais.eventos import ClienteGemini  # noqa: E402

logger = logging.getLogger("gerar_relatorio")
PASTA = settings.BASE_DIR / "relatorios"


def garantir_ranking(conn, dia: date) -> None:
    """Gera ranking e fatores oficiais do dia, se ainda não existirem."""
    tem_fatores = conn.execute("SELECT 1 FROM ranking_fatores WHERE data = ? AND versao_modelo = ? LIMIT 1",
                               (dia.isoformat(), gerar.VERSAO_MODELO)).fetchone()
    if tem_fatores:
        return
    resultado = gerar.ranking_da_data(conn, dia, salvar_em=settings.BASE_DIR / "data" / "modelos")
    gerar.gravar(conn, resultado.ranking, gerar.VERSAO_MODELO)
    gerar.gravar_fatores(conn, resultado.fatores, gerar.VERSAO_MODELO)


def gravar_no_banco(conn, data: str, texto: str) -> None:
    """A API lê os relatórios do banco (igual na nuvem, onde não há pasta)."""
    with conn:
        conn.execute("INSERT INTO relatorios (data, markdown, gerado_em) VALUES (?, ?, ?) "
                     "ON CONFLICT (data) DO UPDATE SET markdown = excluded.markdown, gerado_em = excluded.gerado_em",
                     (data, texto, agora_utc_iso()))


def importar_arquivos(conn, pasta: Path = PASTA) -> int:
    """Relatórios gerados antes da tabela existir (ou à mão) entram no banco."""
    existentes = {r[0] for r in conn.execute("SELECT data FROM relatorios")}
    novos = 0
    for arquivo in sorted(pasta.glob("*.md")):
        if arquivo.stem not in existentes:
            gravar_no_banco(conn, arquivo.stem, arquivo.read_text(encoding="utf-8"))
            novos += 1
    return novos


def pendentes(conn, pasta: Path = PASTA, janela: int = 5) -> list[date]:
    """Pregões entre os últimos `janela` sem relatório publicado nem rejeitado (PC desligado num dia)."""
    recentes = [date.fromisoformat(r[0]) for r in conn.execute(
        "SELECT DISTINCT data FROM universo ORDER BY data DESC LIMIT ?", (janela,))][::-1]
    return [d for d in recentes if not (pasta / f"{d.isoformat()}.md").exists()
            and not (pasta / "rejeitados" / f"{d.isoformat()}.md").exists()]


def gerar_um(conn, llm, dia: date) -> bool:
    garantir_ranking(conn, dia)
    entrada = insumos.montar(conn, dia)
    texto, problemas = redigir.escrever(llm, entrada)
    destino = PASTA / f"{dia.isoformat()}.md"
    if problemas:
        rejeitado = PASTA / "rejeitados" / f"{dia.isoformat()}.md"
        rejeitado.parent.mkdir(parents=True, exist_ok=True)
        rejeitado.write_text(f"<!-- números sem origem: {', '.join(problemas)} -->\n" + texto, encoding="utf-8")
        logger.error("Relatório de %s rejeitado: números sem origem %s", dia, problemas)
        return False
    PASTA.mkdir(parents=True, exist_ok=True)
    destino.write_text(texto, encoding="utf-8")
    gravar_no_banco(conn, dia.isoformat(), texto)
    (PASTA / "insumos").mkdir(exist_ok=True)
    (PASTA / "insumos" / f"{dia.isoformat()}.json").write_text(
        json.dumps(entrada, ensure_ascii=False, indent=1), encoding="utf-8")  # para auditoria
    logger.info("Relatório salvo: %s", destino)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=date.fromisoformat, default=None)
    parser.add_argument("--ultimos", type=int, default=None, help="refaz os últimos N pregões")
    args = parser.parse_args(argv)
    configurar_logging()
    conn = conectar()
    try:
        migrar(conn)
        importar_arquivos(conn)
        if args.data:
            dias = [args.data]
        elif args.ultimos:
            dias = [date.fromisoformat(r[0]) for r in conn.execute(
                "SELECT DISTINCT data FROM universo ORDER BY data DESC LIMIT ?", (args.ultimos,))][::-1]
        else:
            dias = pendentes(conn)
        if not dias:
            print("Relatórios já estão em dia.")
            return 0
        llm = ClienteGemini()
        resultados = {d: gerar_um(conn, llm, d) for d in dias}
    finally:
        conn.close()
    for d, ok in resultados.items():
        print(f"  {d}: {'ok -> relatorios/' + d.isoformat() + '.md' if ok else 'REJEITADO (ver relatorios/rejeitados/)'}")
    return 0 if all(resultados.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
