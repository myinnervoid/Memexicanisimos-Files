"""
services/job_manager.py - Registro Global y Local de Jobs para Memexicanisimos Files.

Implementa la arquitectura dual:
- Índice global en ~/.memex/jobs.jsonl (consulta O(1) de trabajos históricos sin montar USBs).
- Detalle por destino en <destino>/.memex/jobs/{job_id}.json (portabilidad en el disco externo).
- Control de cancelación mediante archivo flag <destino>/.memex/jobs/{job_id}.cancel.
"""

import os
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

JOBS_GLOBAL_FILE = Path("~/.memex/jobs.jsonl").expanduser()


def registrar_inicio_job(job_id: str, tipo: str, origen: str, destino: str) -> None:
    """Registra el inicio de un job tanto en el índice global como en el destino."""
    p_dest = Path(destino)
    dest_jobs_dir = p_dest / ".memex" / "jobs"
    try:
        dest_jobs_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    registro = {
        "job_id": job_id,
        "tipo": tipo,
        "origen": str(origen),
        "destino": str(destino),
        "inicio": datetime.now().isoformat(),
        "fin": None,
        "estado": "en_progreso",
        "metricas": None,
        "error": None
    }

    # Guardar en destino
    try:
        job_file = dest_jobs_dir / f"{job_id}.json"
        with open(job_file, "w", encoding="utf-8") as f:
            json.dump(registro, f, indent=2, ensure_ascii=False)
    except OSError:
        pass

    # Guardar en índice global (~/.memex/jobs.jsonl)
    try:
        JOBS_GLOBAL_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(JOBS_GLOBAL_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    except OSError:
        pass


def registrar_fin_job(job_id: str, destino: str, estado: str, metricas: Optional[dict] = None, error: Optional[str] = None) -> None:
    """Actualiza el estado final del job al concluir o fallar."""
    p_dest = Path(destino)
    job_file = p_dest / ".memex" / "jobs" / f"{job_id}.json"

    registro = {}
    if job_file.exists():
        try:
            with open(job_file, "r", encoding="utf-8") as f:
                registro = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass

    registro["job_id"] = job_id
    registro["destino"] = str(destino)
    registro["fin"] = datetime.now().isoformat()
    registro["estado"] = estado
    if metricas:
        registro["metricas"] = metricas
    if error:
        registro["error"] = error

    # Actualizar en destino
    try:
        with open(job_file, "w", encoding="utf-8") as f:
            json.dump(registro, f, indent=2, ensure_ascii=False)
    except OSError:
        pass

    # Registrar evento de finalización en el ledger global
    try:
        with open(JOBS_GLOBAL_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    except OSError:
        pass


def verificar_solicitud_cancelacion(job_id: str, destino: str) -> bool:
    """Comprueba si se creó el flag de cancelación para este job."""
    flag_file = Path(destino) / ".memex" / "jobs" / f"{job_id}.cancel"
    return flag_file.exists()


def solicitar_cancelacion(job_id: str, destino: str) -> None:
    """Crea el flag de cancelación para que el motor detenga la transferencia limpiamente."""
    flag_file = Path(destino) / ".memex" / "jobs" / f"{job_id}.cancel"
    flag_file.parent.mkdir(parents=True, exist_ok=True)
    flag_file.write_text(datetime.now().isoformat(), encoding="utf-8")


def limpiar_solicitud_cancelacion(job_id: str, destino: str) -> None:
    """Limpia el archivo flag tras finalizar la cancelación."""
    flag_file = Path(destino) / ".memex" / "jobs" / f"{job_id}.cancel"
    try:
        flag_file.unlink(missing_ok=True)
    except OSError:
        pass


def listar_jobs_globales(estado: Optional[str] = None, limite: int = 20) -> List[Dict[str, Any]]:
    """Lee el índice global de jobs devolviendo los últimos N registros."""
    if not JOBS_GLOBAL_FILE.exists():
        return []

    jobs_map: Dict[str, dict] = {}
    try:
        with open(JOBS_GLOBAL_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    rec = json.loads(line_str)
                    jid = rec.get("job_id")
                    if jid:
                        # La última línea sobreescribe el estado de la anterior
                        jobs_map[jid] = rec
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []

    lista = list(jobs_map.values())
    if estado:
        lista = [j for j in lista if j.get("estado") == estado]

    # Ordenar más recientes primero
    lista.reverse()
    return lista[:limite]
