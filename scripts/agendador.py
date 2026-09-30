"""Agendador contínuo local (regra 15: tudo se atualiza sozinho).

- Durante o pregão (dias úteis, 10h-18h de Brasília): ciclo intradiário a cada
  15 minutos (cotação do momento, notícias, ranking provisório).
- Dias úteis às 21h30: pipeline diário completo (rodar_diario.py), depois que
  o arquivo oficial da B3 do dia é publicado.

Uso:
    python scripts/agendador.py            # fica rodando (Ctrl+C para parar)
    pythonw scripts/agendador.py           # sem janela (para iniciar com o Windows)

O estado (últimas execuções) fica em data/agendador_estado.json, então
reiniciar o agendador não repete o que já rodou. Na etapa 8 o mesmo papel
passa para a nuvem (sem depender do PC ligado).
"""

import json
import logging
import subprocess
import sys
import time
from datetime import datetime, time as hora, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src.coleta.intradiario import pregao_em_andamento  # noqa: E402
from src.db.tempo import FUSO_B3  # noqa: E402
from src.logging_config import configurar_logging  # noqa: E402

logger = logging.getLogger("agendador")
ESTADO = RAIZ / "data" / "agendador_estado.json"
INTERVALO_INTRADIARIO = timedelta(minutes=15)
HORA_DIARIO = hora(21, 30)


def ler_estado() -> dict:
    try:
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def salvar_estado(estado: dict) -> None:
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    ESTADO.write_text(json.dumps(estado, indent=1), encoding="utf-8")


def tarefas_devidas(agora: datetime, estado: dict) -> list[str]:
    """Quais tarefas devem rodar agora (função pura, testável)."""
    local = agora.astimezone(FUSO_B3)
    devidas = []
    ultimo_ciclo = estado.get("intradiario")
    if pregao_em_andamento(agora) and (
            ultimo_ciclo is None or agora - datetime.fromisoformat(ultimo_ciclo) >= INTERVALO_INTRADIARIO):
        devidas.append("intradiario")
    if local.weekday() < 5 and local.time() >= HORA_DIARIO and estado.get("diario") != local.date().isoformat():
        devidas.append("diario")
    return devidas


def rodar(tarefa: str) -> int:
    script = {"intradiario": "scripts/ciclo_intradiario.py", "diario": "scripts/rodar_diario.py"}[tarefa]
    logger.info("Agendador: iniciando %s", tarefa)
    r = subprocess.run([sys.executable, script], cwd=RAIZ, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    (logger.info if r.returncode == 0 else logger.error)("Agendador: %s terminou com código %d", tarefa, r.returncode)
    return r.returncode


def main() -> int:
    configurar_logging()
    logger.info("Agendador iniciado")
    while True:
        try:
            agora = datetime.now(timezone.utc)
            estado = ler_estado()
            for tarefa in tarefas_devidas(agora, estado):
                rodar(tarefa)
                estado = ler_estado()
                estado[tarefa] = (agora.isoformat() if tarefa == "intradiario"
                                  else agora.astimezone(FUSO_B3).date().isoformat())
                salvar_estado(estado)
        except Exception:  # noqa: BLE001 - o agendador nunca pode morrer por uma falha
            logger.exception("Erro no agendador; continuando")
        time.sleep(60)


if __name__ == "__main__":
    sys.exit(main())
