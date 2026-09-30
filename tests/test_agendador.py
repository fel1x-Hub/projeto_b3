from datetime import datetime, timezone

from scripts.agendador import tarefas_devidas


def utc(dia, h, m=0):
    return datetime(2026, 9, dia, h, m, tzinfo=timezone.utc)


def test_ciclo_intradiario_a_cada_15_minutos_no_pregao():
    assert tarefas_devidas(utc(30, 14), {}) == ["intradiario"]                               # 11h BRT
    assert tarefas_devidas(utc(30, 14, 10), {"intradiario": utc(30, 14).isoformat()}) == []    # só 10 min depois
    assert tarefas_devidas(utc(30, 14, 15), {"intradiario": utc(30, 14).isoformat()}) == ["intradiario"]
    assert tarefas_devidas(utc(30, 11), {}) == []                                              # 8h BRT: fechado


def test_pipeline_diario_uma_vez_por_dia_util_depois_das_21h30():
    assert tarefas_devidas(utc(30, 0, 29), {}) == []                                           # 21h29 BRT do dia 29
    assert "diario" in tarefas_devidas(utc(30, 0, 31), {})                                     # 21h31 BRT
    assert tarefas_devidas(utc(30, 0, 40), {"diario": "2026-09-29"}) == []                     # já rodou hoje
    assert tarefas_devidas(datetime(2026, 10, 4, 1, 0, tzinfo=timezone.utc), {}) == []         # sábado 22h BRT
