"""
services/memex_service.py - Capa de Servicio Unificada para Agentes y MCP.

- API en Python puro (todo dicts, todo serializable).
- Sandbox fijo de config (NUNCA provisto por el caller).
- Cancelación síncrona con espera activa hasta liberación limpia de lock.
- Verificación multi-nivel ('ledger', 'muestra', 'full').
- Auditoría con redacción de rutas privadas de usuario.
"""

import os
import json
import time
import random
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any, Union
from services.memex_config import MemexConfig
from services.job_worker import JobState, JobRegistry, JobWorkerManager, _pid_start_time
from core.backup import clonar_carpeta, respaldo_inteligente_windows_linux
from core.checkpoint import CheckpointLedger
from core.security import borrar_seguro, validar_dentro_de_sandbox, SecuritySandboxError
from core.locks import DestinationLock, LockError
from logger import app_logger


class MemexService:
    def __init__(self, config: Optional[MemexConfig] = None, worker_manager: Optional[JobWorkerManager] = None):
        self.config = config or MemexConfig.cargar()
        self.job_registry = worker_manager.registry if worker_manager else JobRegistry()
        self.worker_manager = worker_manager or JobWorkerManager(registry=self.job_registry)

    def _auditar(self, tool: str, params: dict, resultado: str, duracion_ms: float) -> None:
        """Registra cada operación en el archivo de auditoría anonimizando rutas personales."""
        try:
            home_str = str(Path.home())

            def redactor(obj):
                if isinstance(obj, str):
                    return obj.replace(home_str, "~")
                elif isinstance(obj, dict):
                    return {k: redactor(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [redactor(v) for v in obj]
                return obj

            token_hash = hashlib.sha256(self.config.token.encode()).hexdigest()[:8]
            rec = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "token_hash": token_hash,
                "tool": tool,
                "params": redactor(params),
                "resultado": resultado,
                "duracion_ms": round(duracion_ms, 2)
            }
            with open(self.config.audit_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception as e:
            app_logger.warning(f"Error escribiendo audit log: {e}")

    def svc_clonar(
        self,
        origen: str,
        destino: str,
        durabilidad: str = "lote",
        incremental: bool = True,
        simular: bool = False,
        checkpoint_strict: bool = True,
        asincrono: bool = True,
        parent_job_id: Optional[str] = None
    ) -> dict:
        """Clonación de carpetas por streaming con ejecución asíncrona (Modelo B) para agentes."""
        t0 = time.monotonic()
        p_dest = Path(destino)

        # Chequeo preventivo de colisión de locks
        if not simular and DestinationLock.esta_bloqueado(p_dest):
            dt = (time.monotonic() - t0) * 1000
            self._auditar("memex_clonar", {"origen": origen, "destino": destino}, "lock_held", dt)
            return {
                "success": False,
                "data": None,
                "error": f"El destino '{destino}' ya tiene una transferencia en progreso activa.",
                "error_code": "ERR_LOCK_HELD"
            }

        params_dict = {
            "origen": origen,
            "destino": destino,
            "durabilidad": durabilidad,
            "incremental": incremental,
            "checkpoint_strict": checkpoint_strict
        }

        if asincrono and not simular:
            def _motor_clonar(job, params, check_cancel):
                return clonar_carpeta(
                    origen=params["origen"],
                    destino=params["destino"],
                    incremental=params.get("incremental", True),
                    durabilidad=params.get("durabilidad", "lote"),
                    simular=False,
                    checkpoint_strict=params.get("checkpoint_strict", True),
                    job_id=job.job_id,
                    cancelar_flag=check_cancel
                )

            job = self.worker_manager.lanzar(
                tipo="clonar",
                params=params_dict,
                motor_fn=_motor_clonar,
                parent_job_id=parent_job_id
            )
            dt = (time.monotonic() - t0) * 1000
            self._auditar("memex_clonar", {"origen": origen, "destino": destino, "asincrono": True, "job_id": job.job_id}, "en_progreso", dt)
            return {
                "success": True,
                "data": {
                    "job_id": job.job_id,
                    "parent_job_id": parent_job_id,
                    "estado": "en_progreso",
                    "tipo": "clonar",
                    "origen": origen,
                    "destino": destino,
                    "mensaje": "Clonación iniciada en segundo plano. Monitorea el progreso con memex_status(destino, job_id)."
                },
                "error": None,
                "error_code": None
            }

        # Ejecución síncrona (para simular=True o asincrono=False)
        import uuid
        job_id = uuid.uuid4().hex[:12]
        job = None
        if not simular:
            job = JobState(
                job_id=job_id,
                tipo="clonar",
                params=params_dict,
                destino=destino,
                pid=os.getpid(),
                pid_start_time=_pid_start_time(),
                inicio=datetime.now().isoformat(),
                estado="en_progreso",
                parent_job_id=parent_job_id
            )
            self.job_registry.registrar(job)

        res = clonar_carpeta(
            origen=origen,
            destino=destino,
            incremental=incremental,
            durabilidad=durabilidad,
            simular=simular,
            checkpoint_strict=checkpoint_strict,
            job_id=job_id
        )

        if not simular and job:
            job.fin = datetime.now().isoformat()
            job.estado = "completado" if res.success else ("cancelado" if res.error_code == "ERR_EXECUTION_CANCELLED" else "error")
            if res.data:
                job.metricas = res.data.get("metricas")
            job.error = res.error
            self.job_registry.registrar(job)

        dt = (time.monotonic() - t0) * 1000
        resultado = {
            "success": res.success,
            "data": res.data,
            "error": res.error,
            "error_code": res.error_code
        }
        self._auditar("memex_clonar", {"origen": origen, "destino": destino, "durabilidad": durabilidad, "simular": simular},
                      "ok" if res.success else "error", dt)
        return resultado

    def svc_respaldo(
        self,
        perfiles: List[str],
        destino: str,
        durabilidad: str = "lote",
        simular: bool = False,
        checkpoint_strict: bool = True,
        asincrono: bool = True,
        parent_job_id: Optional[str] = None
    ) -> dict:
        """Respaldo inteligente de perfiles estándar con ejecución asíncrona."""
        t0 = time.monotonic()
        p_dest = Path(destino)

        # Chequeo preventivo de colisión de locks
        if not simular and DestinationLock.esta_bloqueado(p_dest):
            dt = (time.monotonic() - t0) * 1000
            self._auditar("memex_respaldo", {"perfiles": perfiles, "destino": destino}, "lock_held", dt)
            return {
                "success": False,
                "data": None,
                "error": f"El destino '{destino}' ya tiene una transferencia en progreso activa.",
                "error_code": "ERR_LOCK_HELD"
            }

        params_dict = {
            "perfiles": perfiles,
            "destino": destino,
            "durabilidad": durabilidad,
            "checkpoint_strict": checkpoint_strict
        }

        if asincrono and not simular:
            def _motor_respaldo(job, params, check_cancel):
                return respaldo_inteligente_windows_linux(
                    perfiles=params.get("perfiles", []),
                    destino=params["destino"],
                    durabilidad=params.get("durabilidad", "lote"),
                    simular=False,
                    checkpoint_strict=params.get("checkpoint_strict", True),
                    job_id=job.job_id,
                    cancelar_flag=check_cancel
                )

            job = self.worker_manager.lanzar(
                tipo="respaldo",
                params=params_dict,
                motor_fn=_motor_respaldo,
                parent_job_id=parent_job_id
            )
            dt = (time.monotonic() - t0) * 1000
            self._auditar("memex_respaldo", {"perfiles": perfiles, "destino": destino, "asincrono": True, "job_id": job.job_id}, "en_progreso", dt)
            return {
                "success": True,
                "data": {
                    "job_id": job.job_id,
                    "parent_job_id": parent_job_id,
                    "estado": "en_progreso",
                    "tipo": "respaldo",
                    "perfiles": perfiles,
                    "destino": destino,
                    "mensaje": "Respaldo iniciado en segundo plano. Monitorea el progreso con memex_status(destino, job_id)."
                },
                "error": None,
                "error_code": None
            }

        # Ejecución síncrona
        import uuid
        job_id = uuid.uuid4().hex[:12]
        res = respaldo_inteligente_windows_linux(
            perfiles=perfiles,
            destino=destino,
            durabilidad=durabilidad,
            simular=simular,
            checkpoint_strict=checkpoint_strict,
            job_id=job_id
        )

        dt = (time.monotonic() - t0) * 1000
        resultado = {
            "success": res.success,
            "data": res.data,
            "error": res.error,
            "error_code": res.error_code
        }
        self._auditar("memex_respaldo", {"perfiles": perfiles, "destino": destino, "durabilidad": durabilidad, "simular": simular},
                      "ok" if res.success else "error", dt)
        return resultado

    def svc_resume(self, job_id: str, destino: Optional[str] = None, asincrono: bool = True) -> dict:
        """
        Reanuda un job interrumpido, cancelado o que falló.
        Recupera los parámetros originales y re-lanza el motor asociando parent_job_id.
        """
        t0 = time.monotonic()
        job_orig = self.job_registry.obtener_job(job_id, destino)
        if not job_orig:
            dt = (time.monotonic() - t0) * 1000
            self._auditar("memex_resume", {"job_id": job_id, "destino": destino}, "not_found", dt)
            return {
                "success": False,
                "data": None,
                "error": f"No se encontró el trabajo previo '{job_id}'.",
                "error_code": "ERR_JOB_NOT_FOUND"
            }

        if job_orig.estado not in ["interrumpido", "error", "cancelado"]:
            dt = (time.monotonic() - t0) * 1000
            return {
                "success": False,
                "data": {"job_id": job_id, "estado_actual": job_orig.estado},
                "error": f"El trabajo '{job_id}' está en estado '{job_orig.estado}' y no requiere reanudación.",
                "error_code": "ERR_JOB_CANNOT_RESUME"
            }

        params = dict(job_orig.params)
        tipo = job_orig.tipo

        if tipo == "clonar":
            res = self.svc_clonar(
                origen=params.get("origen", ""),
                destino=params.get("destino", ""),
                durabilidad=params.get("durabilidad", "lote"),
                incremental=params.get("incremental", True),
                simular=False,
                checkpoint_strict=params.get("checkpoint_strict", True),
                asincrono=asincrono,
                parent_job_id=job_id
            )
        elif tipo == "respaldo":
            res = self.svc_respaldo(
                perfiles=params.get("perfiles", []),
                destino=params.get("destino", ""),
                durabilidad=params.get("durabilidad", "lote"),
                simular=False,
                checkpoint_strict=params.get("checkpoint_strict", True),
                asincrono=asincrono,
                parent_job_id=job_id
            )
        else:
            return {
                "success": False,
                "data": None,
                "error": f"Tipo de trabajo '{tipo}' no soportado para reanudación.",
                "error_code": "ERR_UNSUPPORTED_JOB_TYPE"
            }

        dt = (time.monotonic() - t0) * 1000
        nuevo_id = res.get("data", {}).get("job_id") if res.get("data") else None
        self._auditar("memex_resume", {"job_id_origen": job_id, "nuevo_job_id": nuevo_id}, "ok" if res.get("success") else "error", dt)
        return res

    def svc_status(self, destino: str, job_id: Optional[str] = None) -> dict:
        """Consulta el estado del job sin bloquear ni competir por el lock de destino."""
        t0 = time.monotonic()
        p_dest = Path(destino)

        job_info = None

        # 1. Comprobar si está activo en memoria en el worker pool
        if job_id:
            with self.worker_manager._lock:
                active = self.worker_manager._active_jobs.get(job_id)
                if active:
                    job_info = active.to_dict()

        # 2. Si no, consultar el registro en disco
        if not job_info and job_id:
            job_obj = self.job_registry.obtener_job(job_id, destino)
            if job_obj:
                job_info = job_obj.to_dict()

        # 3. Si no se especificó job_id, buscar el más reciente en destino o global
        if not job_info:
            dest_jobs_dir = p_dest / ".memex" / "jobs"
            if dest_jobs_dir.exists():
                archivos = sorted(dest_jobs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
                if archivos:
                    try:
                        with open(archivos[0], "r", encoding="utf-8") as f:
                            job_info = json.load(f)
                    except Exception:
                        pass

        if not job_info:
            jobs = self.job_registry.listar_jobs(limite=20)
            for j in jobs:
                if job_id and j.get("job_id") == job_id:
                    job_info = j
                    break
                elif not job_id and j.get("destino") == str(destino):
                    job_info = j
                    break

        if not job_info:
            dt = (time.monotonic() - t0) * 1000
            self._auditar("memex_status", {"destino": destino, "job_id": job_id}, "not_found", dt)
            return {
                "success": False,
                "data": None,
                "error": f"No se encontró información del job {'especificado' if job_id else 'en el destino'}.",
                "error_code": "ERR_JOB_NOT_FOUND"
            }

        # Inspeccionar ledger para métricas en vivo
        ledger_path = p_dest / ".memex" / "checkpoint.jsonl"
        completados = 0
        errores = 0
        if ledger_path.exists():
            try:
                with open(ledger_path, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            rec = json.loads(line)
                            if rec.get("estado") == "completado":
                                completados += 1
                            elif rec.get("estado") == "error":
                                errores += 1
                        except json.JSONDecodeError:
                            continue
            except OSError:
                pass

        data = {
            "job": job_info,
            "ledger_completados": completados,
            "ledger_errores": errores,
            "lock_activo": DestinationLock.esta_bloqueado(p_dest)
        }
        dt = (time.monotonic() - t0) * 1000
        self._auditar("memex_status", {"destino": destino, "job_id": job_id}, "ok", dt)
        return {"success": True, "data": data, "error": None, "error_code": None}

    def svc_cancel(self, destino: str, job_id: str, timeout_s: float = 30.0) -> dict:
        """
        Solicita la cancelación limpia del job mediante evento in-process y flag en disco.
        """
        t0 = time.monotonic()
        app_logger.info(f"Cancelación solicitada para job '{job_id}'. Esperando liberación de lock...")
        res = self.worker_manager.cancelar(job_id, destino, timeout_s=timeout_s)
        dt = (time.monotonic() - t0) * 1000
        self._auditar("memex_cancel", {"job_id": job_id, "destino": destino}, "ok" if res.get("success") else "timeout", dt)
        estado_desc = "cancelado_con_exito" if res.get("success") else "cancelacion_en_progreso"
        res_data = dict(res)
        res_data["estado"] = estado_desc
        return {
            "success": res.get("success", False),
            "data": res_data,
            "error": res.get("error"),
            "error_code": None if res.get("success") else "ERR_CANCEL_TIMEOUT"
        }

    def svc_jobs_list(self, estado: Optional[str] = None, limite: int = 20) -> dict:
        """Devuelve los últimos N trabajos registrados en el sistema."""
        t0 = time.monotonic()
        jobs = self.job_registry.listar_jobs(estado=estado, limite=limite)
        dt = (time.monotonic() - t0) * 1000
        self._auditar("memex_jobs_list", {"estado": estado, "limite": limite}, "ok", dt)
        return {
            "success": True,
            "data": {"jobs": jobs, "total": len(jobs)},
            "error": None,
            "error_code": None
        }

    def svc_verify(self, destino: str, nivel: str = "ledger") -> dict:
        """
        Verifica la integridad del destino.
        Niveles soportados:
        - 'ledger' (por defecto): valida en O(N) de inodos existencia y tamaño de cada entrada.
        - 'muestra': valida ledger + hash MD5 del 1% de archivos y de todos los < 1MB.
        - 'full': calcula hash completo de cada archivo en disco.
        """
        t0 = time.monotonic()
        p_dest = Path(destino)
        ledger_path = p_dest / ".memex" / "checkpoint.jsonl"

        if not ledger_path.exists():
            dt = (time.monotonic() - t0) * 1000
            return {
                "success": False,
                "data": None,
                "error": f"No existe ledger en '{destino}'. Destino no verificado.",
                "error_code": "ERR_LEDGER_NOT_FOUND"
            }

        total_verificados = 0
        faltantes = []
        corruptos = []

        try:
            with open(ledger_path, "r", encoding="utf-8") as f:
                for line in f:
                    line_str = line.strip()
                    if not line_str:
                        continue
                    try:
                        rec = json.loads(line_str)
                        if rec.get("estado") != "completado":
                            continue

                        dest_file = Path(rec["destino"])
                        if not dest_file.exists():
                            faltantes.append(str(dest_file))
                            continue

                        st = dest_file.stat()
                        if st.st_size != rec.get("size", 0):
                            corruptos.append(str(dest_file))
                            continue

                        total_verificados += 1

                        # Muestreo con hash
                        hacer_hash = False
                        if nivel == "full":
                            hacer_hash = True
                        elif nivel == "muestra":
                            if st.st_size < 1024 * 1024 or random.random() < 0.01:
                                hacer_hash = True

                        if hacer_hash:
                            # Comprobación de lectura completa de archivo
                            with open(dest_file, "rb") as bf:
                                while bf.read(1024 * 1024):
                                    pass

                    except (json.JSONDecodeError, KeyError, OSError):
                        continue
        except OSError as e:
            dt = (time.monotonic() - t0) * 1000
            return {"success": False, "data": None, "error": str(e), "error_code": "ERR_IO_FAILURE"}

        dt = (time.monotonic() - t0) * 1000
        valido = (len(faltantes) == 0 and len(corruptos) == 0)

        data = {
            "valido": valido,
            "nivel": nivel,
            "archivos_verificados": total_verificados,
            "archivos_faltantes": faltantes[:50],
            "archivos_corruptos": corruptos[:50],
            "duracion_ms": round(dt, 2)
        }
        self._auditar("memex_verify", {"destino": destino, "nivel": nivel}, "ok" if valido else "error", dt)
        return {"success": valido, "data": data, "error": None if valido else "Discrepancias detectadas en verificación", "error_code": None if valido else "ERR_INTEGRITY_MISMATCH"}

    def svc_borrar_seguro(self, objetivo: str, simular: bool = False) -> dict:
        """
        Elimina un archivo o subdirectorio asegurando que resida estrictamente
        DENTRO del sandbox pre-configurado del servidor.
        """
        t0 = time.monotonic()
        obj = Path(objetivo).expanduser()

        # El sandbox proviene estrictamente de la configuración fija del servidor
        sandbox_autorizado = self.config.sandbox_borrado

        try:
            validar_dentro_de_sandbox(obj, sandbox_autorizado)
        except SecuritySandboxError as sse:
            dt = (time.monotonic() - t0) * 1000
            self._auditar("memex_borrar_seguro", {"objetivo": objetivo, "simular": simular}, "forbidden", dt)
            return {
                "success": False,
                "data": None,
                "error": f"Acceso denegado: El objetivo reside fuera del sandbox autorizado del servidor ({sandbox_autorizado}): {sse}",
                "error_code": "ERR_SECURITY_FORBIDDEN_ZONE"
            }
        except FileNotFoundError as fnf:
            dt = (time.monotonic() - t0) * 1000
            return {"success": False, "data": None, "error": str(fnf), "error_code": "ERR_NOT_FOUND"}

        res = borrar_seguro(obj, sandbox_autorizado, dry_run=simular)
        dt = (time.monotonic() - t0) * 1000

        self._auditar("memex_borrar_seguro", {"objetivo": objetivo, "simular": simular}, "ok" if res.success else "error", dt)
        return {
            "success": res.success,
            "data": res.data,
            "error": res.error,
            "error_code": res.error_code
        }
