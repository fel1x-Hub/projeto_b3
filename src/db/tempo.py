"""Padronização de timestamps.

Todo timestamp gravado no banco usa o MESMO formato texto: ISO-8601 em UTC,
precisão de segundos, sufixo "+00:00" (ex: 2026-09-29T21:00:00+00:00).
Com formato único, comparar texto equivale a comparar instantes, então
filtros como `disponivel_em <= ?` funcionam direto no SQL (regra anti
look-ahead). O schema rejeita valores fora desse formato.
"""

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

FORMATO_TS = "%Y-%m-%dT%H:%M:%S+00:00"
FUSO_B3 = ZoneInfo("America/Sao_Paulo")  # no Windows, vem do pacote tzdata


def para_iso_utc(dt: datetime) -> str:
    """Converte um datetime COM fuso para o formato padrão em UTC.

    Datetime sem fuso (naive) gera ValueError: não dá para saber se é horário
    de Brasília ou UTC, e adivinhar errado desloca `disponivel_em` em 3 horas.
    """
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"datetime sem fuso horário: {dt!r}")
    return dt.astimezone(timezone.utc).strftime(FORMATO_TS)


def agora_utc_iso() -> str:
    return para_iso_utc(datetime.now(timezone.utc))


def iso_brt(dia: date, hora: time) -> str:
    """Timestamp padrão para `dia` às `hora` no horário de Brasília.

    Usado para montar `disponivel_em` a partir de regras como "fim do pregão"
    ou "fim do dia de entrega" quando a fonte só informa a data.
    """
    return para_iso_utc(datetime.combine(dia, hora, tzinfo=FUSO_B3))


def hoje_brt() -> date:
    return datetime.now(FUSO_B3).date()
