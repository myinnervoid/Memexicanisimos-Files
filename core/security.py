"""
core/security.py - Guardián de Borrado Seguro y Sandbox para Memexicanisimos Files.

Implementa una política estricta de mitigación de pérdida accidental de datos:
1. Resolución canónica de enlaces simbólicos mediante os.path.realpath().
2. Verificación estricta de pertenencia al sandbox autorizado (el objetivo debe ser un
   descendiente estricto del área autorizada).
3. Rechazo explícito si el objetivo es idéntico a la raíz del área autorizada.
4. Rechazo de áreas autorizadas peligrosas (/, /home, /root, /etc, /usr, /var).
5. Borrado controlado paso a paso (archivo por archivo) en lugar de rmtree ciego.
"""

import os
import shutil
from pathlib import Path
from typing import Union, List, Dict, Any

from app_types import ServiceResult
from error_codes import ErrorCode
from logger import app_logger
from i18n import _

RUTAS_PROHIBIDAS_COMO_SANDBOX = {
    Path("/").resolve(),
    Path("/root").resolve(),
    Path("/home").resolve(),
    Path("/etc").resolve(),
    Path("/usr").resolve(),
    Path("/var").resolve(),
    Path("/bin").resolve(),
    Path("/sbin").resolve(),
    Path.home().resolve(),  # No se permite usar todo el HOME como sandbox
}


class SecuritySandboxError(Exception):
    """Excepción al violar las restricciones de aislamiento del sandbox."""
    pass


def validar_dentro_de_sandbox(objetivo: Union[str, Path], area_autorizada: Union[str, Path]) -> Path:
    """
    Valida canónicamente que el objetivo resida estrictamente dentro del área autorizada.
    Retorna el Path canónico resuelto del objetivo si es válido, o lanza SecuritySandboxError.
    """
    p_sandbox = Path(os.path.realpath(area_autorizada)).resolve()
    p_obj = Path(os.path.realpath(objetivo)).resolve()

    # (1) Verificar que el área autorizada no sea una ruta crítica del sistema
    if p_sandbox in RUTAS_PROHIBIDAS_COMO_SANDBOX:
        raise SecuritySandboxError(
            f"El área '{p_sandbox}' es una ruta protegida del sistema y no puede usarse como sandbox de borrado."
        )

    # (2) Verificar que el objetivo exista
    if not p_obj.exists():
        raise FileNotFoundError(f"El objetivo de borrado '{p_obj}' no existe.")

    # (3) Rechazar si el objetivo es exactamente la raíz del área autorizada
    if p_obj == p_sandbox:
        raise SecuritySandboxError(
            f"Operación bloqueada: El objetivo es idéntico a la raíz del área autorizada '{p_sandbox}'."
        )

    # (4) Verificar descendencia estricta (p_sandbox debe estar en los ancestros de p_obj)
    try:
        p_obj.relative_to(p_sandbox)
    except ValueError:
        raise SecuritySandboxError(
            f"Violación de Sandbox: '{p_obj}' no reside dentro del área autorizada '{p_sandbox}'."
        )

    return p_obj


def borrar_seguro(
    objetivo: Union[str, Path],
    area_autorizada: Union[str, Path],
    dry_run: bool = False
) -> ServiceResult:
    """
    Elimina un archivo o directorio de forma segura únicamente dentro del sandbox autorizado.
    """
    try:
        p_obj = validar_dentro_de_sandbox(objetivo, area_autorizada)
    except SecuritySandboxError as sse:
        app_logger.error(f"Intento de borrado bloqueado por Sandbox: {sse}")
        return ServiceResult(success=False, error=str(sse), error_code="ERR_SECURITY_SANDBOX_VIOLATION")
    except FileNotFoundError as fnf:
        return ServiceResult(success=False, error=str(fnf), error_code=ErrorCode.ERR_ORIGIN_NOT_FOUND)
    except Exception as e:
        return ServiceResult(success=False, error=str(e), error_code=ErrorCode.ERR_IO_FAILURE)

    if dry_run:
        tipo = "directorio" if p_obj.is_dir() else "archivo"
        return ServiceResult(
            success=True,
            data={"simulado": True, "eliminado": str(p_obj), "tipo": tipo}
        )

    eliminados = 0
    errores = 0

    try:
        p_sandbox = Path(os.path.realpath(area_autorizada)).resolve()
        if p_obj.is_symlink() or p_obj.is_file():
            p_obj.unlink()
            eliminados = 1
        elif p_obj.is_dir():
            # Borrado granular recursivo: os.walk por defecto followlinks=False
            for raiz, dirs, files in os.walk(p_obj, topdown=False, followlinks=False):
                for f in files:
                    item_file = Path(raiz) / f
                    try:
                        # Si es symlink, unlink solo elimina el enlace, jamás el destino fuera
                        if item_file.is_symlink():
                            item_file.unlink()
                            eliminados += 1
                        else:
                            # Re-verificar que el realpath siga dentro del sandbox
                            if Path(os.path.realpath(item_file)).resolve().is_relative_to(p_sandbox):
                                item_file.unlink()
                                eliminados += 1
                            else:
                                app_logger.warning(f"Omitido archivo que escapa del sandbox: '{item_file}'")
                    except OSError as oe:
                        errores += 1
                        app_logger.warning(f"Error borrando archivo '{f}': {oe}")

                for d in dirs:
                    item_dir = Path(raiz) / d
                    try:
                        if item_dir.is_symlink():
                            item_dir.unlink()
                            eliminados += 1
                        else:
                            if Path(os.path.realpath(item_dir)).resolve().is_relative_to(p_sandbox):
                                item_dir.rmdir()
                                eliminados += 1
                            else:
                                app_logger.warning(f"Omitido directorio que escapa del sandbox: '{item_dir}'")
                    except OSError as oe:
                        errores += 1
                        app_logger.warning(f"Error borrando directorio '{d}': {oe}")

            p_obj.rmdir()
            eliminados += 1

        app_logger.info(f"Borrado seguro completado en sandbox: {eliminados} elementos eliminados de '{p_obj}'")
        return ServiceResult(
            success=(errores == 0),
            data={"eliminados": eliminados, "errores": errores, "ruta": str(p_obj)}
        )

    except Exception as e:
        app_logger.error(f"Fallo durante el borrado seguro de '{p_obj}': {e}")
        return ServiceResult(success=False, error=str(e), error_code=ErrorCode.ERR_IO_FAILURE)
