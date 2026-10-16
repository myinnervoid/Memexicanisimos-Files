"""
Paquete core/ de Memexicanisimos Files.

Reexporta todas las funciones de los módulos especializados y mantiene
100% de retrocompatibilidad con las funciones históricas de core_legacy.
"""

from core_legacy import *

from core.atomic_io import (
    copia_atomica,
    limpiar_partials_huerfanos,
    PARTIAL_SUFFIX
)
from core.checkpoint import (
    CheckpointLedger,
    OpRecord,
    make_op_id,
    generar_op_id
)
from core.scanner import (
    FileEntry,
    iterar_archivos,
    iterar_directorios,
    contar_archivos_y_bytes
)
from core.locks import (
    DestinationLock,
    LockError,
    adquirir_lock,
    liberar_lock
)
from core.versioning import (
    resolver_conflicto_versionado
)
from core.backup import (
    respaldo_inteligente_windows_linux,
    clonar_carpeta,
    detectar_carpetas_usuario,
    detectar_dispositivos_multimedia
)
from core.security import (
    borrar_seguro,
    validar_dentro_de_sandbox,
    SecuritySandboxError
)
