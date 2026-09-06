"""
Modulo error_codes.py - Catálogo Centralizado de Códigos de Error.

Contiene la enumeración ErrorCode consumida por Backend (para reportar errores)
y Frontend (para mapear estados visuales de UX).
"""

from enum import Enum


class ErrorCode(str, Enum):
    """Códigos de error estándar del sistema Memexicanisimos Files."""

    # Errores de Ruta y Archivos
    ERR_ORIGIN_NOT_FOUND = "ERR_ORIGIN_NOT_FOUND"
    ERR_DEST_NOT_FOUND = "ERR_DEST_NOT_FOUND"
    ERR_PATH_INVALID = "ERR_PATH_INVALID"
    ERR_FILE_NOT_FOUND = "ERR_FILE_NOT_FOUND"
    ERR_PERMISSION_DENIED = "ERR_PERMISSION_DENIED"

    # Errores de Configuración y Filtros
    ERR_REGEX_INVALID = "ERR_REGEX_INVALID"
    ERR_INVALID_MODE = "ERR_INVALID_MODE"
    ERR_NO_FILES_MATCHED = "ERR_NO_FILES_MATCHED"
    ERR_PROFILE_LOAD_FAILED = "ERR_PROFILE_LOAD_FAILED"
    ERR_PROFILE_SAVE_FAILED = "ERR_PROFILE_SAVE_FAILED"

    # Errores de Ejecución y Proceso
    ERR_EXECUTION_CANCELLED = "ERR_EXECUTION_CANCELLED"
    ERR_DISK_FULL = "ERR_DISK_FULL"
    ERR_IO_FAILURE = "ERR_IO_FAILURE"

    # Errores de Undo / Historial
    ERR_UNDO_EMPTY = "ERR_UNDO_EMPTY"
    ERR_UNDO_FAILED = "ERR_UNDO_FAILED"

    # Errores del Sistema / Dependencias
    ERR_TOOL_NOT_INSTALLED = "ERR_TOOL_NOT_INSTALLED"
    ERR_UNSUPPORTED_OS = "ERR_UNSUPPORTED_OS"
    ERR_UNKNOWN = "ERR_UNKNOWN"
