from datetime import datetime, timedelta, timezone

import pytest

from src.db.tempo import agora_utc_iso, para_iso_utc

BRT = timezone(timedelta(hours=-3))


def test_converte_brasilia_para_utc():
    # fim do pregão às 18h em Brasília = 21h UTC
    assert para_iso_utc(datetime(2026, 1, 2, 18, 0, tzinfo=BRT)) == "2026-01-02T21:00:00+00:00"


def test_descarta_microssegundos_e_vira_o_dia():
    dt = datetime(2026, 1, 2, 22, 30, 15, 999_999, tzinfo=BRT)
    assert para_iso_utc(dt) == "2026-01-03T01:30:15+00:00"


def test_rejeita_datetime_sem_fuso():
    with pytest.raises(ValueError, match="sem fuso"):
        para_iso_utc(datetime(2026, 1, 2, 18, 0))


def test_ordem_do_texto_e_ordem_cronologica():
    a = para_iso_utc(datetime(2026, 1, 2, 23, 0, tzinfo=BRT))  # 02:00 UTC do dia 3
    b = para_iso_utc(datetime(2026, 1, 3, 1, 0, tzinfo=timezone.utc))
    assert a > b


def test_agora_no_formato_padrao():
    agora = agora_utc_iso()
    assert agora.endswith("+00:00") and len(agora) == 25
