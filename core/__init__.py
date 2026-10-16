"""
Paquete core/ de Memexicanisimos Files.

Reexporta todas las funciones de los módulos especializados y mantiene
100% de retrocompatibilidad con las funciones históricas de core_legacy.
"""

from core.atomic_io import PARTIAL_SUFFIX, copia_atomica, limpiar_partials_huerfanos
from core.backup import (
    clonar_carpeta,
    detectar_carpetas_usuario,
    detectar_dispositivos_multimedia,
    respaldo_inteligente_windows_linux,
)
from core.checkpoint import CheckpointLedger, OpRecord, generar_op_id, make_op_id
from core.locks import DestinationLock, LockError, adquirir_lock, liberar_lock
from core.scanner import FileEntry, contar_archivos_y_bytes, iterar_archivos, iterar_directorios
from core.security import SecuritySandboxError, borrar_seguro, validar_dentro_de_sandbox
from core.versioning import resolver_conflicto_versionado
from core_legacy import *
