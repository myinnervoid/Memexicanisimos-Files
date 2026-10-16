"""
core/locks.py - Bloqueo de concurrencia a nivel de destino para Memexicanisimos Files.

Garantiza que dos procesos (agente de IA, CLI o GUI) no escriban simultáneamente
en la misma carpeta destino ni corrompan el ledger de transferencias.
Incluye recuperación automática de locks huérfanos (stale locks).
"""

import os
import json
import socket
from pathlib import Path
from datetime import datetime
from typing import Optional


class LockError(Exception):
    """Excepción lanzada cuando el directorio destino está bloqueado por otro proceso activo."""
    pass


class DestinationLock:
    """Representa un bloqueo activo sobre un directorio de destino."""

    def __init__(self, ruta_destino: Path, timeout_segundos: int = 10):
        self.ruta_destino = Path(ruta_destino)
        self.memex_dir = self.ruta_destino / ".memex"
        self.lock_file = self.memex_dir / "transfer.lock"
        self._adquirido = False

    @classmethod
    def esta_bloqueado(cls, ruta_destino: Path) -> bool:
        """Determina de forma no invasiva si el destino está bloqueado activamente por otro proceso."""
        instancia = cls(ruta_destino)
        if not instancia.lock_file.exists():
            return False
        return not instancia._es_stale()

    def adquirir(self) -> "DestinationLock":
        self.memex_dir.mkdir(parents=True, exist_ok=True)

        if self.lock_file.exists():
            if self._es_stale():
                try:
                    self.lock_file.unlink(missing_ok=True)
                except OSError:
                    pass
            else:
                info = self._leer_info()
                pid = info.get("pid", "desconocido")
                host = info.get("host", "desconocido")
                raise LockError(f"El destino '{self.ruta_destino}' está bloqueado por el PID {pid} en {host}.")

        payload = {
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "timestamp": datetime.now().isoformat(),
        }

        try:
            # Creación atómica exclusiva O_CREAT | O_EXCL
            fd = os.open(str(self.lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            self._adquirido = True
        except (FileExistsError, OSError) as e:
            raise LockError(f"No se pudo adquirir lock exclusivo: {e}")

        return self

    def liberar(self):
        if self._adquirido:
            try:
                self.lock_file.unlink(missing_ok=True)
            except OSError:
                pass
            self._adquirido = False

    def _leer_info(self) -> dict:
        try:
            with open(self.lock_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _es_stale(self) -> bool:
        """
        Determina si el lock es huérfano (stale) evaluando:
        1. Si el timestamp tiene más de 24 horas de antigüedad.
        2. Si el host es diferente al host actual (o no determinable).
        3. Si el PID local ya no existe en la tabla de procesos.
        """
        info = self._leer_info()
        pid = info.get("pid")
        host = info.get("host")
        ts_str = info.get("timestamp")

        if not pid:
            return True

        # (1) Antigüedad > 24 horas
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str)
                if (datetime.now() - ts).total_seconds() > 86400:
                    return True
            except Exception:
                pass

        # (2) Host distinto
        if host and host != socket.gethostname():
            return True

        # (3) Proceso ya no existe en el sistema operativo local
        try:
            os.kill(pid, 0)
            return False  # El proceso sigue vivo y es local
        except ProcessLookupError:
            return True  # PID no existe: lock huérfano
        except PermissionError:
            return False  # Proceso existe pero es de otro usuario local (activo)


def adquirir_lock(ruta_destino: Path) -> DestinationLock:
    return DestinationLock(ruta_destino).adquirir()


def liberar_lock(lock: Optional[DestinationLock]):
    if lock:
        lock.liberar()
