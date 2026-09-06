"""
Modulo app_types.py - Contratos de Datos y Excepciones Específicas del Sistema.

Define las estructuras de datos explícitas (TypedDict, dataclass) y la jerarquía de
excepciones especializadas utilizadas por el Backend y Frontend.
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Any, TypedDict, Union

from error_codes import ErrorCode


# ==============================================================================
# JERARQUÍA DE EXCEPCIONES PERSONALIZADAS (Recomendación Técnica b)
# ==============================================================================

class AppBaseException(Exception):
    """Excepción base del sistema Memexicanisimos Files."""
    def __init__(self, message: str, error_code: ErrorCode = ErrorCode.ERR_UNKNOWN):
        super().__init__(message)
        self.message = message
        self.error_code = error_code


class RutaNoValidaError(AppBaseException):
    """Se lanza cuando la ruta especificada no existe o no es un directorio válido."""
    def __init__(self, message: str):
        super().__init__(message, ErrorCode.ERR_PATH_INVALID)


class FechaNoEncontradaError(AppBaseException):
    """Se lanza cuando no se puede determinar la fecha de un archivo."""
    def __init__(self, message: str):
        super().__init__(message, ErrorCode.ERR_NO_FILES_MATCHED)


class DiskFullError(AppBaseException):
    """Se lanza cuando el disco de destino se queda sin espacio suficiente."""
    def __init__(self, message: str = "Espacio insuficiente en el disco de destino."):
        super().__init__(message, ErrorCode.ERR_DISK_FULL)


class PathTooLongError(AppBaseException):
    """Se lanza cuando la ruta excede el límite de caracteres permitido por el SO."""
    def __init__(self, message: str = "La ruta excede el límite máximo de caracteres."):
        super().__init__(message, ErrorCode.ERR_PATH_INVALID)


class PermissionDeniedError(AppBaseException):
    """Se lanza cuando no se tienen permisos de lectura o escritura en el archivo/carpeta."""
    def __init__(self, message: str = "Acceso denegado: permisos insuficientes."):
        super().__init__(message, ErrorCode.ERR_PERMISSION_DENIED)


class FileLockedError(AppBaseException):
    """Se lanza cuando el archivo está bloqueado por otro proceso."""
    def __init__(self, message: str = "El archivo está siendo utilizado por otro proceso."):
        super().__init__(message, ErrorCode.ERR_IO_FAILURE)


# ==============================================================================
# CONTRATOS DE DATOS DE LA APLICACIÓN
# ==============================================================================

class PlanArchivo(TypedDict):
    """Contrato de datos para un elemento planificado de copia/movimiento."""
    origen: Path
    destino: Path
    fecha: Optional[date]
    accion: str  # 'mover', 'copiar', 'duplicado'


class FiltrosAvanzados(TypedDict, total=False):
    """Contrato de datos para los criterios de filtrado de archivos."""
    todos: bool
    categorias: List[str]
    ext_adicionales: List[str]
    incluir_subcarpetas: bool
    usar_exif: bool
    usar_hash: bool
    tamano_min_bytes: Optional[int]
    tamano_max_bytes: Optional[int]
    dias_antiguedad: Optional[int]
    incluir_ocultos: bool
    patron_regex: Optional[str]
    usar_creacion_filtro: bool


class EstructuraConfig(TypedDict, total=False):
    """Contrato de datos para las reglas de organizacion de carpetas."""
    criterio_primario: str      # 'fecha', 'tipo', 'nombre', 'ninguno'
    criterio_secundario: Optional[str]
    formato_fecha: str          # '{YYYY}/{MM}', '{YYYY}-{MM}-{DD}', etc.
    organizacion_tipo: str      # 'extension' o 'categoria'
    organizacion_nombre: str    # 'primera_letra' o 'completo'
    usar_fecha_creacion: bool
    activar_renombrado: bool
    plantilla_nombre: Optional[str]


class UndoRecord(TypedDict):
    """Contrato de datos para un registro del historial Undo (JSON Lines)."""
    timestamp: str
    modo: str
    origen: str
    destino: str
    nombre_original: str
    nombre_final: str


@dataclass
class ServiceResult:
    """Estructura de respuesta unificada retornada por todas las funciones Backend."""
    success: bool
    data: Any = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    message: Optional[str] = None

    def __post_init__(self):
        if self.message is None and self.error is not None:
            self.message = self.error
        elif self.error is None and self.message is not None:
            self.error = self.message

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "error_code": self.error_code,
            "message": self.message or self.error
        }

    @classmethod
    def ok(cls, data: Any = None, message: Optional[str] = None) -> "ServiceResult":
        """Factory helper para respuestas exitosas estandarizadas."""
        return cls(success=True, data=data, message=message, error=None, error_code=None)

    @classmethod
    def fail(cls, error: str, error_code: Optional[Union[str, ErrorCode]] = None, data: Any = None) -> "ServiceResult":
        """Factory helper para respuestas fallidas estandarizadas."""
        code_str = error_code.value if isinstance(error_code, ErrorCode) else error_code
        return cls(success=False, data=data, error=error, message=error, error_code=code_str)


# Alias estandarizado de transporte/IPC conforme a Ley 5 (ApiResponse<T>)
ApiResponse = ServiceResult
