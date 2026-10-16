"""
services/job_worker.py - Gestor Concurrente Asíncrono de Trabajos (Modelo B) para Memexicanisimos Files.

Resuelve los 5 gotchas de producción:
1. Sin output a stdout: el worker no escribe nada al canal de comunicación.
2. Detección precisa de PID recycling mediante /proc/<pid>/stat campo 22 (starttime).
3. Shutdown cooperativo con threading.Event y executor.shutdown(wait=False).
4. Capacidad de reanudación (svc_resume) preservando parent_job_id y parámetros originales.
5. Cancelación híbrida ultra rápida: threading.Event in-process + flag .cancel en disco.
"""

import os
import sys
import json
import time
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable

from logger import app_logger


def _pid_start_time() -> float:
    """Lee el starttime del proceso actual desde /proc/self/stat (campo 22, índice 21)."""
    try:
        with open("/proc/self/stat", "r", encoding="utf-8") as f:
            campos = f.read().split()
            return float(campos[21])
    except Exception:
        return 0.0  # Fallback macOS / entornos sin /proc


def _pid_sigue_vivo(pid: int, start_time: float) -> bool:
    """
    Verifica que el PID existe Y es exactamente el mismo proceso que inició el job.
    Evita falsos positivos por reciclaje de PID en kernels Linux.
    """
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as f:
            campos = f.read().split()
            actual_start = float(campos[21])
            return actual_start == start_time
    except (FileNotFoundError, ProcessLookupError, IndexError, ValueError, OSError):
        # Fallback para sistemas sin /proc o cuando start_time era 0.0
        if start_time == 0.0:
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False
        return False


@dataclass
class JobState:
    job_id: str
    tipo: str                 # "clonar" | "respaldo"
    params: dict              # origen, destino, durabilidad, incremental...
    destino: str
    pid: int
    pid_start_time: float     # de /proc/self/stat campo 22
    inicio: str
    estado: str               # "en_progreso" | "completado" | "error" | "cancelado" | "interrumpido"
    parent_job_id: Optional[str] = None
    fin: Optional[str] = None
    error: Optional[str] = None
    metricas: Optional[dict] = None

    def to_dict(self) -> dict:
        return asdict(self)


class JobRegistry:
    """
    Índice dual persistente:
    - ~/.memex/jobs.jsonl (índice global rápido).
    - <destino>/.memex/jobs/{job_id}.json (detalle atómico en destino).
    """

    def __init__(self, global_file: Optional[Path] = None):
        self.global_file = global_file or Path("~/.memex/jobs.jsonl").expanduser()
        self._lock = threading.Lock()
        try:
            self.global_file.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    def registrar(self, job: JobState) -> None:
        """Registra o actualiza el estado de un job tanto en destino como en global."""
        with self._lock:
            # 1. Destino (<destino>/.memex/jobs/{id}.json) mediante reemplazo atómico
            try:
                dest_jobs_dir = Path(job.destino) / ".memex" / "jobs"
                dest_jobs_dir.mkdir(parents=True, exist_ok=True)
                tmp_file = dest_jobs_dir / f"{job.job_id}.json.tmp"
                final_file = dest_jobs_dir / f"{job.job_id}.json"
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(job.to_dict(), f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_file, final_file)
            except OSError as e:
                app_logger.warning(f"No se pudo escribir job en destino '{job.destino}': {e}")

            # 2. Índice global (~/.memex/jobs.jsonl)
            try:
                with open(self.global_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(job.to_dict(), ensure_ascii=False) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
            except OSError as e:
                app_logger.warning(f"No se pudo escribir en índice global de jobs: {e}")

    def obtener_job(self, job_id: str, destino: Optional[str] = None) -> Optional[JobState]:
        """Obtiene la información de un job buscando primero en destino y luego en el índice global."""
        if destino:
            j_file = Path(destino) / ".memex" / "jobs" / f"{job_id}.json"
            if j_file.exists():
                try:
                    with open(j_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        return JobState(**data)
                except Exception:
                    pass

        # Buscar en índice global
        if self.global_file.exists():
            try:
                ultimo_reg = None
                with open(self.global_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            d = json.loads(line)
                            if d.get("job_id") == job_id:
                                ultimo_reg = d
                        except json.JSONDecodeError:
                            continue
                if ultimo_reg:
                    return JobState(**ultimo_reg)
            except OSError:
                pass
        return None

    def listar_jobs(self, estado: Optional[str] = None, limite: int = 20) -> List[dict]:
        """Devuelve los últimos N jobs únicos deduplicados."""
        if not self.global_file.exists():
            return []

        jobs_map: Dict[str, dict] = {}
        try:
            with open(self.global_file, "r", encoding="utf-8") as f:
                for line in f:
                    line_str = line.strip()
                    if not line_str:
                        continue
                    try:
                        d = json.loads(line_str)
                        jid = d.get("job_id")
                        if jid:
                            jobs_map[jid] = d
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return []

        lista = list(jobs_map.values())
        if estado:
            lista = [j for j in lista if j.get("estado") == estado]

        lista.reverse()
        return lista[:limite]

    def recuperar_huerfanos(self) -> List[JobState]:
        """
        Escanea jobs marcados como 'en_progreso'. Si el PID ya no existe
        o su tiempo de inicio cambió (kernel recycling), los marca como 'interrumpido'.
        """
        if not self.global_file.exists():
            return []

        jobs_map: Dict[str, dict] = {}
        try:
            with open(self.global_file, "r", encoding="utf-8") as f:
                for line in f:
                    line_str = line.strip()
                    if not line_str:
                        continue
                    try:
                        d = json.loads(line_str)
                        jid = d.get("job_id")
                        if jid:
                            jobs_map[jid] = d
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return []

        huerfanos = []
        for jid, d in jobs_map.items():
            if d.get("estado") == "en_progreso":
                pid = d.get("pid", 0)
                start_time = float(d.get("pid_start_time", 0.0))
                if not _pid_sigue_vivo(pid, start_time):
                    d["estado"] = "interrumpido"
                    d["fin"] = datetime.now().isoformat()
                    d["error"] = "Servidor MCP reiniciado antes de concluir"
                    job_huerfano = JobState(**d)
                    huerfanos.append(job_huerfano)
                    self.registrar(job_huerfano)
        return huerfanos


class JobWorkerManager:
    """
    Administrador del pool de hilos para ejecución asíncrona de jobs en background.
    Garantiza cancelación rápida y shutdown cooperativo sin bloquear.
    """

    def __init__(self, registry: Optional[JobRegistry] = None, max_workers: int = 4):
        self.registry = registry or JobRegistry()
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="MemexWorker")
        self._active_jobs: Dict[str, JobState] = {}
        self._cancel_events: Dict[str, threading.Event] = {}
        self._shutdown_event = threading.Event()
        self._lock = threading.Lock()

    def lanzar(
        self,
        tipo: str,
        params: dict,
        motor_fn: Callable[[JobState, dict, Callable[[], bool]], Any],
        parent_job_id: Optional[str] = None
    ) -> JobState:
        """
        Crea el estado del job, lo persiste de inmediato y lo submitea al pool de hilos.
        Retorna el JobState en < 50ms para responder inmediatamente al cliente MCP.
        """
        job_id = uuid.uuid4().hex[:12]
        destino = params.get("destino", "")

        job = JobState(
            job_id=job_id,
            tipo=tipo,
            params=dict(params),
            destino=destino,
            pid=os.getpid(),
            pid_start_time=_pid_start_time(),
            inicio=datetime.now().isoformat(),
            estado="en_progreso",
            parent_job_id=parent_job_id
        )

        cancel_ev = threading.Event()

        with self._lock:
            self._active_jobs[job_id] = job
            self._cancel_events[job_id] = cancel_ev

        # Persistir estado inicial de inmediato
        self.registry.registrar(job)

        def _check_cancel() -> bool:
            # 1. Chequeo ultra rápido in-process
            if self._shutdown_event.is_set() or cancel_ev.is_set():
                return True
            # 2. Chequeo en disco para cancelaciones cross-process
            cancel_file = Path(destino) / ".memex" / "jobs" / f"{job_id}.cancel"
            if cancel_file.exists():
                cancel_ev.set()
                return True
            return False

        def _worker_wrapper():
            try:
                res = motor_fn(job, params, _check_cancel)
                if _check_cancel():
                    job.estado = "cancelado"
                    job.error = "Operación cancelada por solicitud de usuario o shutdown"
                elif res and getattr(res, "success", False):
                    job.estado = "completado"
                    if getattr(res, "data", None):
                        job.metricas = res.data.get("metricas")
                else:
                    err_code = getattr(res, "error_code", None)
                    if err_code == "ERR_EXECUTION_CANCELLED":
                        job.estado = "cancelado"
                    else:
                        job.estado = "error"
                        job.error = getattr(res, "error", "Error desconocido en motor")
            except Exception as e:
                job.estado = "error"
                job.error = str(e)
                app_logger.error(f"Error crítico en worker para job '{job.job_id}': {e}")
            finally:
                job.fin = datetime.now().isoformat()
                self.registry.registrar(job)
                # Limpiar flag de cancelación en disco
                try:
                    c_file = Path(destino) / ".memex" / "jobs" / f"{job_id}.cancel"
                    c_file.unlink(missing_ok=True)
                except OSError:
                    pass
                with self._lock:
                    self._active_jobs.pop(job_id, None)
                    self._cancel_events.pop(job_id, None)

        self.executor.submit(_worker_wrapper)
        return job

    def cancelar(self, job_id: str, destino: str, timeout_s: float = 30.0) -> dict:
        """
        Activa la cancelación in-process y el flag de disco.
        Espera de forma cooperativa hasta que el worker libere el lock o alcance timeout.
        """
        # 1. Activar evento in-process si está en memoria
        with self._lock:
            ev = self._cancel_events.get(job_id)
            if ev:
                ev.set()
            active = self._active_jobs.get(job_id)
            if active and active.estado == "en_progreso":
                active.estado = "cancelacion_en_progreso"

        # 2. Escribir flag en disco para soporte cross-process
        try:
            flag_file = Path(destino) / ".memex" / "jobs" / f"{job_id}.cancel"
            flag_file.parent.mkdir(parents=True, exist_ok=True)
            flag_file.write_text(datetime.now().isoformat(), encoding="utf-8")
        except OSError:
            pass

        # 3. Esperar liberación cooperativa del lock
        lock_file = Path(destino) / ".memex" / "transfer.lock"
        t0 = time.monotonic()
        intervalo = 0.1
        liberado = False

        while (time.monotonic() - t0) < timeout_s:
            if not lock_file.exists():
                liberado = True
                break
            time.sleep(intervalo)

        if liberado:
            with self._lock:
                active = self._active_jobs.get(job_id)
                if active:
                    active.estado = "cancelado"
                    active.fin = datetime.now().isoformat()
                    active.error = "Cancelado por solicitud de agente"

            job = self.registry.obtener_job(job_id, destino)
            if job and job.estado in ["en_progreso", "cancelacion_en_progreso"]:
                job.estado = "cancelado"
                job.fin = datetime.now().isoformat()
                job.error = "Cancelado por solicitud de agente"
                self.registry.registrar(job)
            return {"success": True, "job_id": job_id, "estado": "cancelado"}
        else:
            return {"success": False, "job_id": job_id, "estado": "cancelacion_en_progreso", "error": "Timeout esperando liberación del lock"}

    def shutdown(self, timeout_s: float = 5.0):
        """Detención ordenada del pool sin bloquear si hay jobs largos pendientes."""
        self._shutdown_event.set()
        with self._lock:
            for ev in self._cancel_events.values():
                ev.set()
        self.executor.shutdown(wait=False)
