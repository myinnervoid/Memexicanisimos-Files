"""
core/locks.py - Bloqueo de concurrencia a nivel de destino para Memexicanisimos Files.

Garantiza que dos procesos (agente de IA, CLI o GUI) no escriban simultáneamente
en la misma carpeta destino ni corrompan el ledger de transferencias.
Incluye recuperación automática de locks huérfanos (stale locks).
"""

import json
import os
import socket
from datetime import datetime
from pathlib import Path
from typing import Optional, Union, Dict, Any


class LockError(Exception):
    """Excepción lanzada cuando el directorio destino está bloqueado por otro proceso activo."""
    pass


class DestinationLock:
    """Representa un bloqueo activo sobre un directorio de destino.
    
    Attributes:
        ruta_destino (Path): El directorio de destino a proteger.
        memex_dir (Path): Subdirectorio interno `.memex` usado por la aplicación.
        lock_file (Path): Archivo de bloqueo específico dentro de `memex_dir`.
    """

    def __init__(self, ruta_destino: Union[Path, str], timeout_segundos: int = 10) -> None:
        """Inicializa el objeto DestinationLock sin adquirir el bloqueo.

        Args:
            ruta_destino (Union[Path, str]): Ruta hacia el directorio de destino.
            timeout_segundos (int, optional): Segundos a esperar o considerar para el timeout. Por defecto es 10.
        """
        self.ruta_destino: Path = Path(ruta_destino)
        self.memex_dir: Path = self.ruta_destino / ".memex"
        self.lock_file: Path = self.memex_dir / "transfer.lock"
        self._adquirido: bool = False

    @classmethod
    def esta_bloqueado(cls, ruta_destino: Union[Path, str]) -> bool:
        """Determina de forma no invasiva si el destino está bloqueado activamente por otro proceso.

        Args:
            ruta_destino (Union[Path, str]): Ruta hacia el directorio de destino a comprobar.

        Returns:
            bool: True si está bloqueado activamente y no es huérfano, False en caso contrario.
        """
        instancia = cls(ruta_destino)
        if not instancia.lock_file.exists():
            return False
        return not instancia._es_stale()

    def adquirir(self) -> "DestinationLock":
        """Adquiere el bloqueo exclusivo sobre el directorio de destino.

        Si existe un archivo de lock huérfano (stale), intenta eliminarlo y crear uno nuevo.

        Raises:
            LockError: Si el destino ya está bloqueado por otro proceso o si falla la creación del archivo de bloqueo.

        Returns:
            DestinationLock: La instancia actual tras adquirir el bloqueo.
        """
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

    def liberar(self) -> None:
        """Libera el bloqueo activo si fue adquirido previamente por esta instancia."""
        if self._adquirido:
            try:
                self.lock_file.unlink(missing_ok=True)
            except OSError:
                pass
            self._adquirido = False

    def _leer_info(self) -> Dict[str, Any]:
        """Lee la información almacenada en el archivo de bloqueo.

        Returns:
            Dict[str, Any]: Diccionario con la información del bloqueo, o un diccionario vacío si falla.
        """
        try:
            with open(self.lock_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _es_stale(self) -> bool:
        """Determina si el lock es huérfano (stale).

        Evalúa las siguientes condiciones:
        1. Si el timestamp tiene más de 24 horas de antigüedad.
        2. Si el host es diferente al host actual (o no determinable).
        3. Si el PID local ya no existe en la tabla de procesos.

        Returns:
            bool: True si el lock es huérfano, False si es un lock activo.
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


def adquirir_lock(ruta_destino: Union[Path, str]) -> DestinationLock:
    """Función de conveniencia para instanciar y adquirir un bloqueo.

    Args:
        ruta_destino (Union[Path, str]): La ruta al directorio de destino.

    Returns:
        DestinationLock: La instancia del bloqueo adquirido.

    Raises:
        LockError: Si no se puede adquirir el bloqueo.
    """
    return DestinationLock(ruta_destino).adquirir()


def liberar_lock(lock: Optional[DestinationLock]) -> None:
    """Función de conveniencia para liberar un bloqueo si existe.

    Args:
        lock (Optional[DestinationLock]): El objeto de bloqueo a liberar.
    """
    if lock:
        lock.liberar()
