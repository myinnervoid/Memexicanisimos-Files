"""
core/backup.py - Motor de Respaldo Inteligente y Clonación por Streaming.

- Streaming puro mediante core.scanner.iterar_archivos (memoria RAM constante O(profundidad)).
- Durabilidad atómica mediante core.atomic_io.copia_atomica.
- Auditoría y reanudación automática mediante core.checkpoint.CheckpointLedger.
- Protección contra colisiones concurrentes mediante core.locks.adquirir_lock.
- Versionado opcional seguro mediante core.versioning.resolver_conflicto_versionado.
"""

import os
import re
import shutil
import time
import resource
from pathlib import Path
from typing import Callable, List, Optional, Union, Dict, Any

from app_types import ServiceResult
from error_codes import ErrorCode
from config import AppConfig
from logger import app_logger
from i18n import _

from core.scanner import iterar_archivos, iterar_directorios, contar_archivos_y_bytes
from core.atomic_io import copia_atomica
from core.checkpoint import CheckpointLedger, OpRecord, make_op_id
from core.locks import adquirir_lock, liberar_lock, LockError
from core.versioning import resolver_conflicto_versionado


PATRONES_BASURA = [
    re.compile(r'\.tmp$', re.IGNORECASE),
    re.compile(r'\.bak$', re.IGNORECASE),
    re.compile(r'~$'),
    re.compile(r'Thumbs\.db$', re.IGNORECASE),
    re.compile(r'desktop\.ini$', re.IGNORECASE),
    re.compile(r'\.DS_Store$'),
]

DIRECTORIOS_OMITIR = {
    'AppData', 'Local Settings', 'Application Data', '.cache',
    'node_modules', '__pycache__', 'temp', 'tmp', '.npm', '.cargo',
    '.venv', 'venv', 'target', 'dist', 'build', '.next', '.nuxt',
}


def _es_basura(nombre: str) -> bool:
    return any(p.search(nombre) for p in PATRONES_BASURA)


def detectar_carpetas_usuario() -> List[Dict[str, str]]:
    home = Path.home()
    carpetas_std = [
        ("Documentos", home / "Documentos"), ("Imágenes", home / "Imágenes"),
        ("Música", home / "Música"), ("Descargas", home / "Descargas"),
        ("Vídeos", home / "Vídeos"), ("Escritorio", home / "Escritorio"),
        ("Documents", home / "Documents"), ("Pictures", home / "Pictures"),
        ("Music", home / "Music"), ("Downloads", home / "Downloads"),
    ]
    return [{'nombre': n, 'ruta': str(p)} for n, p in carpetas_std if p.exists() and p.is_dir()]


def detectar_dispositivos_multimedia() -> List[Dict[str, str]]:
    dispositivos = []
    usuario = os.environ.get('USER', '')
    rutas = [
        Path("/media"), Path(f"/media/{usuario}"), Path(f"/run/media/{usuario}"),
        Path(f"/run/user/{os.getuid()}/gvfs") if hasattr(os, 'getuid') else None
    ]
    for r in rutas:
        if r and r.exists() and r.is_dir():
            try:
                for item in r.iterdir():
                    if item.is_dir():
                        tipo = "Teléfono Android / Cámara MTP" if ("mtp" in item.name.lower() or "gphoto2" in item.name.lower()) else "USB Extraíble"
                        espacio = "Desconocido"
                        try:
                            st = shutil.disk_usage(item)
                            espacio = f"{st.free / (1024 ** 3):.1f} GB libres"
                        except Exception:
                            pass
                        dispositivos.append({'etiqueta': item.name, 'ruta': str(item), 'tipo': tipo, 'espacio': espacio})
            except Exception as e:
                app_logger.debug(f"Error escaneando punto de montaje '{r}': {e}")

    return dispositivos


def _validar_seguridad_rutas(origen: Path, destino: Path) -> Optional[ServiceResult]:
    """
    Validaciones de seguridad vitales:
    1. Origen == Destino o Destino dentro de Origen (prevención de bucle infinito).
    2. Destino con permisos de escritura.
    3. Advertencia si se corre como root (sudo).
    4. Detección de desmontaje de dispositivo en /media o /mnt.
    """
    orig_res = origen.resolve()
    dest_res = destino.resolve()

    # 1. Bucle infinito: Origen == Destino o Destino es descendiente de Origen
    if orig_res == dest_res:
        return ServiceResult.fail(
            error=_("El destino no puede ser idéntico al origen ({orig}).").format(orig=orig_res),
            error_code=ErrorCode.ERR_DESTINATION_INSIDE_ORIGIN
        )

    try:
        dest_res.relative_to(orig_res)
        return ServiceResult.fail(
            error=_("El destino ({dest}) está dentro del origen ({orig}), lo que causaría un bucle infinito.").format(
                dest=dest_res, orig=orig_res
            ),
            error_code=ErrorCode.ERR_DESTINATION_INSIDE_ORIGIN
        )
    except ValueError:
        pass  # Destino no es descendiente de origen, seguro.

    # 2. Detección de dispositivo no montado (en /media/**, /mnt/**, /run/media/**)
    partes = dest_res.parts
    if len(partes) >= 3 and partes[1] in ("media", "mnt", "run"):
        # Determinar punto de montaje esperado (ej. /media/user/USB)
        # Comprobar si el st_dev de la carpeta coincide con el de la raíz del sistema
        try:
            if dest_res.exists():
                st_dest = dest_res.stat()
                st_root = Path("/").stat()
                # Si está bajo /media o /mnt pero comparte st_dev con /, está en el filesystem raíz (no montado)
                if st_dest.st_dev == st_root.st_dev:
                    app_logger.warning(
                        f"Advertencia: '{dest_res}' está en /media o /mnt pero comparte st_dev con el sistema raíz. "
                        f"Podría ser una carpeta vacía sin montar."
                    )
        except OSError:
            pass

    # 3. Permisos de escritura en destino
    check_w = dest_res
    while not check_w.exists() and check_w != check_w.parent:
        check_w = check_w.parent
    if not os.access(check_w, os.W_OK):
        return ServiceResult.fail(
            error=_("Permiso de escritura denegado en la ruta de destino '{dest}'.").format(dest=check_w),
            error_code=ErrorCode.ERR_PERMISSION_DENIED
        )

    # 4. Advertencia de ejecución con privilegios de root (sudo)
    try:
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            app_logger.warning(
                "⚠️ ADVERTENCIA: Proceso ejecutándose con privilegios de root (sudo). "
                "Los archivos creados pertenecerán a root:root."
            )
    except Exception:
        pass

    return None



def respaldo_inteligente_windows_linux(
    perfiles: List[str],
    destino: Union[str, Path],
    callback_progreso: Optional[Callable[[int, int, int, int, str], None]] = None,
    cancelar_flag: Optional[Callable[[], bool]] = None,
    usar_checkpoint: bool = True,
    archivar_versiones: bool = False,
    pre_contar: bool = True,
    simular: bool = False,
    durabilidad: str = "lote",
    checkpoint_strict: bool = False,
    job_id: Optional[str] = None,
) -> ServiceResult:
    """
    Respalda perfiles estándar omitiendo cachés y temporales, con streaming y reanudación ledger.
    """
    p_dest = Path(destino)
    if not p_dest.exists() or not p_dest.is_dir():
        return ServiceResult(success=False, error=_("La ruta de destino no es válida."),
                             error_code=ErrorCode.ERR_DESTINATION_NOT_FOUND)

    # Validar permisos de escritura y que no sea / o ruta de sistema
    dest_res = p_dest.resolve()
    if not os.access(dest_res, os.W_OK):
        return ServiceResult.fail(
            error=_("Permiso de escritura denegado en la ruta de destino '{dest}'.").format(dest=dest_res),
            error_code=ErrorCode.ERR_PERMISSION_DENIED
        )

    # Advertencia si se corre como root (sudo)
    try:
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            app_logger.warning("⚠️ ADVERTENCIA: Proceso ejecutándose con privilegios de root (sudo). Los archivos creados pertenecerán a root:root.")
    except Exception:
        pass

    # Adquirir lock exclusivo de destino
    try:
        lock = adquirir_lock(p_dest)
    except LockError as e:
        app_logger.error(f"No se pudo adquirir lock de destino: {e}")
        return ServiceResult(success=False, error=str(e), error_code="ERR_LOCK_HELD")

    ledger: Optional[CheckpointLedger] = None
    try:
        # Validación de checkpoint estricto
        if usar_checkpoint and not simular:
            check_ledger = CheckpointLedger(p_dest)
            errores_prev = check_ledger.tiene_errores_pendientes()
            if checkpoint_strict and errores_prev:
                app_logger.error(f"Checkpoint estricto bloqueado: {len(errores_prev)} errores pendientes.")
                return ServiceResult(
                    success=False,
                    error=f"ERR_CHECKPOINT_HAS_ERRORS: {len(errores_prev)} archivos fallaron en la corrida anterior sin resolver.",
                    error_code="ERR_CHECKPOINT_HAS_ERRORS",
                    data={"errores_pendientes": errores_prev}
                )

        carpetas_usuario = {d['nombre']: Path(d['ruta']) for d in detectar_carpetas_usuario()}
        carpetas = [carpetas_usuario[p] for p in perfiles if p in carpetas_usuario]
        if not carpetas:
            return ServiceResult(success=False, error=_("No se encontraron los perfiles seleccionados o están vacíos."),
                                 error_code=ErrorCode.ERR_ORIGIN_NOT_FOUND)

        # Prevenir bucle infinito si el destino está dentro de uno de los perfiles
        for c in carpetas:
            c_res = c.resolve()
            if dest_res == c_res:
                return ServiceResult.fail(
                    error=_("El destino no puede ser idéntico al perfil de origen ({orig}).").format(orig=c_res),
                    error_code=ErrorCode.ERR_DESTINATION_INSIDE_ORIGIN
                )
            try:
                dest_res.relative_to(c_res)
                return ServiceResult.fail(
                    error=_("El destino ({dest}) está dentro de la carpeta del perfil ({orig}), lo que causaría un bucle infinito.").format(
                        dest=dest_res, orig=c_res
                    ),
                    error_code=ErrorCode.ERR_DESTINATION_INSIDE_ORIGIN
                )
            except ValueError:
                pass

        scan_kwargs = dict(
            incluir_subcarpetas=True,
            incluir_ocultos=False,
            excluir_directorios=DIRECTORIOS_OMITIR,
            excluir_ocultos_dir=True,
        )

        total = 0
        bytes_totales = 0
        if pre_contar:
            for carpeta in carpetas:
                for entry in iterar_archivos(carpeta, **scan_kwargs):
                    if _es_basura(entry.path.name):
                        continue
                    total += 1
                    bytes_totales += entry.size

            # Verificación preventiva de espacio en disco
            check_dest = p_dest
            while not check_dest.exists() and check_dest != check_dest.parent:
                check_dest = check_dest.parent
            try:
                espacio_libre = shutil.disk_usage(str(check_dest)).free
                if bytes_totales > 0 and (bytes_totales + 20 * 1024 * 1024) > espacio_libre:
                    return ServiceResult.fail(
                        error=_("Espacio insuficiente. Requerido: {req:.2f} MB, Disponible: {disp:.2f} MB").format(
                            req=bytes_totales / (1024 ** 2), disp=espacio_libre / (1024 ** 2)),
                        error_code=ErrorCode.ERR_DISK_FULL
                    )
            except Exception as e:
                app_logger.warning(f"No se pudo verificar espacio en '{check_dest}': {e}")

        t_inicio = time.time()
        ledger = CheckpointLedger(p_dest, job_id=job_id) if (usar_checkpoint and not simular) else None
        job_actual = ledger.job_id if ledger else (job_id or "simulado")

        copiados = 0
        omitidos = 0
        errores = 0
        bytes_copiados = 0
        home_dir = Path.home()
        idx = 0

        for carpeta in carpetas:
            for entry in iterar_archivos(carpeta, **scan_kwargs):
                if cancelar_flag and cancelar_flag():
                    app_logger.info("Respaldo cancelado por el usuario.")
                    if ledger:
                        ledger.cerrar()
                    return ServiceResult(
                        success=False,
                        error=_("Operación cancelada por el usuario."),
                        error_code=ErrorCode.ERR_EXECUTION_CANCELLED,
                        data={"copiados": copiados, "omitidos": omitidos, "errores": errores, "bytes_copiados": bytes_copiados}
                    )

                if _es_basura(entry.path.name):
                    continue

                idx += 1
                try:
                    rel = entry.path.relative_to(home_dir)
                except ValueError:
                    rel = Path(entry.path.name)

                destino_final = p_dest / rel
                op_id = make_op_id("backup", str(rel), entry.size, entry.mtime_ns)

                # (1) Verificar en ledger con confirmación defensiva en el filesystem
                if ledger and ledger.ya_completado(op_id):
                    if destino_final.exists():
                        omitidos += 1
                        bytes_copiados += entry.size
                        continue
                    else:
                        app_logger.warning(f"Ledger marcaba '{op_id}' como completado pero '{destino_final}' no existe en disco. Re-copiando.")

                # (2) Fast-path: si ya existe en destino idéntico
                if destino_final.exists():
                    try:
                        st_d = destino_final.stat()
                        if st_d.st_size == entry.size and abs(st_d.st_mtime - (entry.mtime_ns / 1e9)) < 2.0:
                            if ledger:
                                ledger.registrar(OpRecord(
                                    op_id=op_id, origen=str(entry.path), destino=str(destino_final),
                                    size=entry.size, mtime_ns=entry.mtime_ns, estado='completado'
                                ))
                            omitidos += 1
                            bytes_copiados += entry.size
                            continue
                    except OSError:
                        pass

                if callback_progreso:
                    callback_progreso(idx, total, bytes_copiados, bytes_totales, entry.path.name)

                # Modo Simulación: acumula contadores sin tocar disco
                if simular:
                    copiados += 1
                    bytes_copiados += entry.size
                    continue

                # (3) Versionado ante conflicto
                final_dest = destino_final
                if archivar_versiones and final_dest.exists():
                    resuelto = resolver_conflicto_versionado(entry.path, final_dest)
                    if resuelto is None:
                        if ledger:
                            ledger.registrar(OpRecord(
                                op_id=op_id, origen=str(entry.path), destino=str(final_dest),
                                size=entry.size, mtime_ns=entry.mtime_ns, estado='completado'
                            ))
                        omitidos += 1
                        bytes_copiados += entry.size
                        continue
                    final_dest = resuelto

                # (4) Registro de intención
                if ledger:
                    ledger.registrar(OpRecord(
                        op_id=op_id, origen=str(entry.path), destino=str(final_dest),
                        size=entry.size, mtime_ns=entry.mtime_ns, estado='copiando'
                    ))

                # (5) Copia atómica
                ok, err = copia_atomica(entry.path, final_dest, durabilidad=durabilidad)
                if ok:
                    copiados += 1
                    bytes_copiados += entry.size
                    if ledger:
                        ledger.registrar(OpRecord(
                            op_id=op_id, origen=str(entry.path), destino=str(final_dest),
                            size=entry.size, mtime_ns=entry.mtime_ns, estado='completado'
                        ))
                else:
                    errores += 1
                    app_logger.warning(f"Error copiando '{entry.path}' → '{final_dest}': {err}")
                    if ledger:
                        ledger.registrar(OpRecord(
                            op_id=op_id, origen=str(entry.path), destino=str(final_dest),
                            size=entry.size, mtime_ns=entry.mtime_ns, estado='error', error=err
                        ))

        if ledger:
            ledger.cerrar()

        if callback_progreso and pre_contar:
            callback_progreso(total, total, bytes_totales, bytes_totales, "Completado")

        duracion_total = max(0.001, time.time() - t_inicio)
        metricas = {
            "duracion_total_s": round(duracion_total, 2),
            "throughput_mb_s": round((bytes_copiados / (1024 * 1024)) / duracion_total, 2),
            "archivos_por_segundo": round(copiados / duracion_total, 2),
            "ram_pico_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2),
        }

        return ServiceResult(success=(errores == 0), data={
            "job_id": job_actual,
            "copiados": copiados, "omitidos": omitidos, "errores": errores,
            "bytes_copiados": bytes_copiados, "total": total,
            "metricas": metricas, "simulado": simular
        })

    except KeyboardInterrupt:
        app_logger.warning("Operación de respaldo interrumpida por KeyboardInterrupt (Ctrl+C).")
        if ledger:
            ledger.flush()
        raise
    finally:
        if ledger:
            ledger.cerrar()
        liberar_lock(lock)


def clonar_carpeta(
    origen: Union[str, Path],
    destino: Union[str, Path],
    incremental: bool = False,
    callback_progreso: Optional[Callable[[int, int, int, int, str], None]] = None,
    cancelar_flag: Optional[Callable[[], bool]] = None,
    usar_checkpoint: bool = True,
    omitir_basura: bool = False,
    archivar_versiones: bool = False,
    pre_contar: bool = True,
    simular: bool = False,
    preservar_vacios: bool = True,
    durabilidad: str = "lote",
    checkpoint_strict: bool = False,
    job_id: Optional[str] = None,
) -> ServiceResult:
    """
    Clona un directorio hacia otro por streaming con soporte para modo incremental, ledger y telemetría.
    """
    p_orig = Path(origen)
    p_dest = Path(destino)

    if not p_orig.exists() or not p_orig.is_dir():
        return ServiceResult(success=False, error=_("La ruta de origen no es válida."), error_code=ErrorCode.ERR_ORIGIN_NOT_FOUND)

    # Validaciones de seguridad (bucle infinito, permisos, root, disco no montado)
    err_seguridad = _validar_seguridad_rutas(p_orig, p_dest)
    if err_seguridad:
        return err_seguridad

    try:
        lock = adquirir_lock(p_dest)
    except LockError as e:
        return ServiceResult(success=False, error=str(e), error_code="ERR_LOCK_HELD")

    ledger: Optional[CheckpointLedger] = None
    try:
        # Validación de checkpoint estricto
        if usar_checkpoint and not simular:
            check_ledger = CheckpointLedger(p_dest)
            errores_prev = check_ledger.tiene_errores_pendientes()
            if checkpoint_strict and errores_prev:
                app_logger.error(f"Checkpoint estricto bloqueado: {len(errores_prev)} errores pendientes.")
                return ServiceResult(
                    success=False,
                    error=f"ERR_CHECKPOINT_HAS_ERRORS: {len(errores_prev)} archivos fallaron en la corrida anterior sin resolver.",
                    error_code="ERR_CHECKPOINT_HAS_ERRORS",
                    data={"errores_pendientes": errores_prev}
                )

        scan_kwargs = dict(
            incluir_subcarpetas=True,
            incluir_ocultos=True,
            excluir_directorios=DIRECTORIOS_OMITIR if omitir_basura else set(),
        )

        total = 0
        bytes_totales = 0
        directorios_totales = 0
        directorios_vacios = 0

        if pre_contar or simular:
            for entry in iterar_archivos(p_orig, **scan_kwargs):
                if omitir_basura and _es_basura(entry.path.name):
                    continue
                total += 1
                bytes_totales += entry.size

            if preservar_vacios:
                excl_dirs = DIRECTORIOS_OMITIR if omitir_basura else set()
                for d in iterar_directorios(p_orig, excluir_directorios=excl_dirs):
                    directorios_totales += 1
                    try:
                        # Comprobar si el directorio está vacío sin materializar lista completa
                        with os.scandir(d) as it_d:
                            if not any(True for _ in it_d):
                                directorios_vacios += 1
                    except OSError:
                        pass

            check_dest = p_dest
            while not check_dest.exists() and check_dest != check_dest.parent:
                check_dest = check_dest.parent
            try:
                espacio_libre = shutil.disk_usage(str(check_dest)).free
                if bytes_totales > 0 and (bytes_totales + 20 * 1024 * 1024) > espacio_libre:
                    return ServiceResult.fail(
                        error=_("Espacio insuficiente en disco destino. Requerido: {req:.2f} MB, Disponible: {disp:.2f} MB").format(
                            req=bytes_totales / (1024 ** 2), disp=espacio_libre / (1024 ** 2)),
                        error_code=ErrorCode.ERR_DISK_FULL
                    )
            except Exception as e:
                app_logger.warning(f"No se pudo verificar espacio en '{check_dest}': {e}")

        # Replicar estructura de directorios (incluyendo carpetas vacías)
        if preservar_vacios and not simular:
            excl_dirs = DIRECTORIOS_OMITIR if omitir_basura else set()
            for d in iterar_directorios(p_orig, excluir_directorios=excl_dirs):
                rel_d = d.relative_to(p_orig)
                dest_sub = p_dest / rel_d
                dest_sub.mkdir(parents=True, exist_ok=True)

        t_inicio = time.time()
        ledger = CheckpointLedger(p_dest, job_id=job_id) if (usar_checkpoint and not simular) else None
        job_actual = ledger.job_id if ledger else (job_id or "simulado")

        copiados = 0
        omitidos = 0
        errores = 0
        bytes_copiados = 0
        idx = 0

        for entry in iterar_archivos(p_orig, **scan_kwargs):
            if cancelar_flag and cancelar_flag():
                if ledger:
                    ledger.cerrar()
                return ServiceResult(success=False, error=_("Clonación cancelada."), error_code=ErrorCode.ERR_EXECUTION_CANCELLED)

            if omitir_basura and _es_basura(entry.path.name):
                continue

            idx += 1
            rel = entry.path.relative_to(p_orig)
            dest_arch = p_dest / rel
            op_id = make_op_id("clone", str(rel), entry.size, entry.mtime_ns)

            # (1) Ledger con confirmación defensiva en el filesystem
            if ledger and ledger.ya_completado(op_id):
                if dest_arch.exists():
                    omitidos += 1
                    bytes_copiados += entry.size
                    continue
                else:
                    app_logger.warning(f"Ledger marcaba '{op_id}' como completado pero '{dest_arch}' no existe en disco. Re-copiando.")

            # (2) Incremental
            if incremental and dest_arch.exists():
                try:
                    st_d = dest_arch.stat()
                    if st_d.st_size == entry.size and abs(st_d.st_mtime - (entry.mtime_ns / 1e9)) < 1.0:
                        if ledger:
                            ledger.registrar(OpRecord(
                                op_id=op_id, origen=str(entry.path), destino=str(dest_arch),
                                size=entry.size, mtime_ns=entry.mtime_ns, estado='completado'
                            ))
                        omitidos += 1
                        bytes_copiados += entry.size
                        continue
                except OSError:
                    pass

            if callback_progreso:
                callback_progreso(idx, total, bytes_copiados, bytes_totales, entry.path.name)

            # Simulación: acumular contadores sin tocar disco
            if simular:
                copiados += 1
                bytes_copiados += entry.size
                continue

            final_dest = dest_arch
            if archivar_versiones and final_dest.exists():
                resuelto = resolver_conflicto_versionado(entry.path, final_dest)
                if resuelto is None:
                    if ledger:
                        ledger.registrar(OpRecord(
                            op_id=op_id, origen=str(entry.path), destino=str(final_dest),
                            size=entry.size, mtime_ns=entry.mtime_ns, estado='completado'
                        ))
                    omitidos += 1
                    bytes_copiados += entry.size
                    continue
                final_dest = resuelto

            ok, err = copia_atomica(entry.path, final_dest, durabilidad=durabilidad)
            if ok:
                copiados += 1
                bytes_copiados += entry.size
                if ledger:
                    ledger.registrar(OpRecord(
                        op_id=op_id, origen=str(entry.path), destino=str(final_dest),
                        size=entry.size, mtime_ns=entry.mtime_ns, estado='completado'
                    ))
            else:
                errores += 1
                app_logger.warning(f"Error al clonar '{entry.path.name}': {err}")
                if ledger:
                    ledger.registrar(OpRecord(
                        op_id=op_id, origen=str(entry.path), destino=str(final_dest),
                        size=entry.size, mtime_ns=entry.mtime_ns, estado='error', error=err
                    ))

        if ledger:
            ledger.cerrar()

        if callback_progreso and pre_contar:
            callback_progreso(total, total, bytes_totales, bytes_totales, "Completado")

        duracion_total = max(0.001, time.time() - t_inicio)
        metricas = {
            "duracion_total_s": round(duracion_total, 2),
            "throughput_mb_s": round((bytes_copiados / (1024 * 1024)) / duracion_total, 2),
            "archivos_por_segundo": round(copiados / duracion_total, 2),
            "ram_pico_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2),
        }

        return ServiceResult(success=(errores == 0), data={
            "job_id": job_actual,
            "copiados": copiados, "omitidos": omitidos, "errores": errores,
            "bytes_copiados": bytes_copiados, "total": total,
            "directorios_totales": directorios_totales,
            "directorios_vacios": directorios_vacios,
            "metricas": metricas, "simulado": simular
        })

    except KeyboardInterrupt:
        app_logger.warning("Clonación interrumpida por KeyboardInterrupt (Ctrl+C).")
        if ledger:
            ledger.flush()
        raise
    finally:
        if ledger:
            ledger.cerrar()
        liberar_lock(lock)
