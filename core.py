"""
Modulo core.py - Funciones puras e infraestructura Backend para Memexicanisimos Files.

Implementa la lógica de búsqueda, clasificación, ejecución de planes,
desduplicación y Undo con Logging Centralizado (loguru) e i18n.
"""

from collections import deque
from datetime import datetime, date, timedelta
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import List, Dict, Optional, Union, Tuple, Any, Callable

# Importaciones del proyecto
from app_types import (
    ServiceResult, PlanArchivo, FiltrosAvanzados, EstructuraConfig, UndoRecord,
    RutaNoValidaError, FechaNoEncontradaError, DiskFullError, PermissionDeniedError, FileLockedError
)
from error_codes import ErrorCode
from config import AppConfig, CATEGORIAS_EXT
from logger import app_logger
from i18n import _

try:
    import mutagen
    MUTAGEN_DISPONIBLE = True
except ImportError:
    MUTAGEN_DISPONIBLE = False

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def obtener_archivos(
    ruta_origen: Union[str, Path],
    extensiones_permitidas: Optional[List[str]] = None,
    incluir_subcarpetas: bool = True,
    tamano_min_bytes: Optional[int] = None,
    tamano_max_bytes: Optional[int] = None,
    dias_antiguedad: Optional[int] = None,
    usar_creacion: bool = False,
    incluir_ocultos: bool = False,
    patron_regex: Optional[str] = None,
) -> ServiceResult:
    """Obtiene archivos en la ruta filtrados por múltiples criterios."""
    origen_path = Path(ruta_origen)

    if not origen_path.exists() or not origen_path.is_dir():
        msg = _("La ruta de origen no existe o no es un directorio válido.")
        app_logger.warning(f"{msg}: {ruta_origen}")
        return ServiceResult(success=False, error=msg, error_code=ErrorCode.ERR_ORIGIN_NOT_FOUND)

    exts_norm = None
    if extensiones_permitidas:
        exts_norm = [ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in extensiones_permitidas]

    regex_compilado = None
    if patron_regex:
        try:
            regex_compilado = re.compile(patron_regex)
        except re.error as err:
            msg = f"{_('Patrón Regex inválido')}: {err}"
            app_logger.error(msg)
            return ServiceResult(success=False, error=msg, error_code=ErrorCode.ERR_REGEX_INVALID)

    fecha_limite = None
    if dias_antiguedad is not None and dias_antiguedad > 0:
        fecha_limite = datetime.now() - timedelta(days=dias_antiguedad)

    necesita_stat = (tamano_min_bytes is not None or tamano_max_bytes is not None or fecha_limite is not None)

    archivos_encontrados: List[Path] = []

    def _escanear_directorio(dir_path: str):
        try:
            with os.scandir(dir_path) as it:
                for entry in it:
                    try:
                        if entry.is_file():
                            yield Path(entry.path)
                        elif incluir_subcarpetas and entry.is_dir():
                            yield from _escanear_directorio(entry.path)
                    except PermissionError:
                        app_logger.warning(f"Permiso denegado en: '{entry.path}'")
                    except Exception as e:
                        app_logger.warning(f"Error procesando '{entry.path}': {e}")
        except PermissionError:
            app_logger.warning(f"Permiso denegado al escanear directorio: '{dir_path}'")
        except Exception as e:
            app_logger.warning(f"Error escaneando directorio '{dir_path}': {e}")

    try:
        iterador = _escanear_directorio(str(origen_path))
    except Exception as e:
        app_logger.error(f"Error inicializando escáner en {origen_path}: {e}")
        return ServiceResult(success=False, error=_("Error al acceder a la carpeta."), error_code=ErrorCode.ERR_PERMISSION_DENIED)

    for elemento in iterador:
        try:

            if not incluir_ocultos and elemento.name.startswith('.'):
                continue

            if exts_norm is not None and elemento.suffix.lower() not in exts_norm:
                continue

            if regex_compilado and not regex_compilado.search(elemento.name):
                continue

            if necesita_stat:
                try:
                    stat_info = elemento.stat()
                    if tamano_min_bytes is not None and stat_info.st_size < tamano_min_bytes:
                        continue
                    if tamano_max_bytes is not None and stat_info.st_size > tamano_max_bytes:
                        continue
                    if fecha_limite is not None:
                        ts = stat_info.st_ctime if usar_creacion else stat_info.st_mtime
                        if datetime.fromtimestamp(ts) < fecha_limite:
                            continue
                except OSError as oe:
                    app_logger.warning(f"No se pudo obtener stat() de '{elemento.name}': {oe}")

            archivos_encontrados.append(elemento)

        except PermissionError:
            app_logger.warning(f"Permiso denegado en el archivo: '{elemento.name}'")
        except Exception as e:
            app_logger.warning(f"Error omitiendo elemento '{elemento.name}': {e}")

    app_logger.info(f"Escaneo completado: {len(archivos_encontrados)} archivos encontrados en '{origen_path}'")
    return ServiceResult(success=True, data=archivos_encontrados)


def obtener_categoria(extension: Union[str, Path]) -> str:
    if isinstance(extension, Path):
        ext_limpia = extension.suffix.lstrip(".").lower()
    else:
        ext_limpia = str(extension).lstrip(".").lower()
    for cat, exts in CATEGORIAS_EXT.items():
        if ext_limpia in exts:
            return cat
    return "Otros"


def extraer_fecha(archivo_path: Path, usar_exif: bool = True, usar_creacion: bool = False) -> date:
    if not isinstance(archivo_path, Path):
        archivo_path = Path(archivo_path)

    nombre = archivo_path.name
    patrones_regex = [
        (r'(?<!\d)(19\d\d|20\d\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)', "%Y%m%d"),
        (r'(?<!\d)(19\d\d|20\d\d)[-_](0[1-9]|1[0-2])[-_](0[1-9]|[12]\d|3[01])(?!\d)', "%Y-%m-%d"),
        (r'(?<!\d)(19\d\d|20\d\d)\.(0[1-9]|1[0-2])\.(0[1-9]|[12]\d|3[01])(?!\d)', "%Y.%m.%d"),
        (r'(?<!\d)(0[1-9]|[12]\d|3[01])[-_](0[1-9]|1[0-2])[-_](19\d\d|20\d\d)(?!\d)', "%d-%m-%Y"),
        (r'(?<!\d)(0[1-9]|[12]\d|3[01])\.(0[1-9]|1[0-2])\.(19\d\d|20\d\d)(?!\d)', "%d.%m.%Y"),
    ]

    for patron, formato in patrones_regex:
        coincidencia = re.search(patron, nombre)
        if coincidencia:
            texto_fecha = coincidencia.group(0)
            if formato in ("%Y-%m-%d", "%d-%m-%Y"):
                texto_fecha = texto_fecha.replace("_", "-")
            try:
                dt = datetime.strptime(texto_fecha, formato)
                return dt.date()
            except ValueError:
                pass

    ext_imagen = {'.jpg', '.jpeg', '.png', '.tiff', '.tif'}
    if usar_exif and HAS_PIL and archivo_path.suffix.lower() in ext_imagen:
        try:
            with Image.open(archivo_path) as img:
                exif_data = img._getexif() if hasattr(img, "_getexif") else None
                if exif_data:
                    fecha_str = exif_data.get(36867) or exif_data.get(306)
                    if fecha_str and isinstance(fecha_str, str):
                        partes = fecha_str.split(" ")[0].split(":")
                        if len(partes) == 3:
                            return date(int(partes[0]), int(partes[1]), int(partes[2]))
        except Exception as e:
            app_logger.debug(f"No se leyeron datos EXIF de '{archivo_path.name}': {e}")

    try:
        stat_info = archivo_path.stat()
        ts = stat_info.st_ctime if usar_creacion else stat_info.st_mtime
        return datetime.fromtimestamp(ts).date()
    except Exception as e:
        app_logger.warning(f"Fallo al obtener fecha del sistema para '{archivo_path.name}': {e}")
        raise FechaNoEncontradaError(f"No se pudo determinar la fecha de '{archivo_path.name}': {e}")


def _formatear_fecha_estructura(fecha: date, formato_patron: str) -> str:
    meses_es = [
        "", "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
    ]
    meses_abr_es = [
        "", "ene", "feb", "mar", "abr", "may", "jun",
        "jul", "ago", "sep", "oct", "nov", "dic"
    ]
    res = formato_patron
    res = res.replace("{YYYY}", f"{fecha.year:04d}")
    res = res.replace("{MM}", f"{fecha.month:02d}")
    res = res.replace("{DD}", f"{fecha.day:02d}")
    if 1 <= fecha.month <= 12:
        res = res.replace("{MES_NOMBRE}", meses_es[fecha.month])
        res = res.replace("{MES_ABR}", meses_abr_es[fecha.month])
    return res


def _obtener_segmento_criterio(criterio: Optional[str], archivo_path: Path, fecha: Optional[date], estructura: Dict[str, Any]) -> Optional[str]:
    if not criterio or criterio.lower() == 'ninguno':
        return None
    crit = criterio.lower()
    if crit == 'fecha':
        if fecha is None:
            return "sin_fecha"
        formato_patron = estructura.get('formato_fecha', '{YYYY}/{MM}')
        return _formatear_fecha_estructura(fecha, formato_patron)
    elif crit == 'tipo':
        org_tipo = estructura.get('organizacion_tipo', 'extension').lower()
        ext_sin_punto = archivo_path.suffix.lstrip(".").lower() or "sin_extension"
        return obtener_categoria(ext_sin_punto) if org_tipo == 'categoria' else ext_sin_punto
    elif crit == 'nombre':
        org_nombre = estructura.get('organizacion_nombre', 'primera_letra').lower()
        stem = archivo_path.stem
        if not stem:
            return "sin_nombre"
        if org_nombre == 'primera_letra':
            primera = stem[0].upper()
            return primera if primera.isalnum() else "_"
        return stem
    return None


def generar_ruta_destino(archivo_path: Path, fecha: Optional[date], carpeta_raiz_destino: Union[str, Path], estructura: Optional[Dict[str, Any]] = None) -> Path:
    raiz = Path(carpeta_raiz_destino)
    if not estructura:
        if fecha is None:
            return raiz / "sin_fecha" / archivo_path.name
        return raiz / str(fecha.year) / f"{fecha.month:02d}" / archivo_path.name

    criterio_p = estructura.get('criterio_primario')
    criterio_s = estructura.get('criterio_secundario')

    if not criterio_p:
        if fecha is None:
            return raiz / "sin_fecha" / archivo_path.name
        return raiz / str(fecha.year) / f"{fecha.month:02d}" / archivo_path.name

    seg_primario = _obtener_segmento_criterio(criterio_p, archivo_path, fecha, estructura)
    seg_secundario = _obtener_segmento_criterio(criterio_s, archivo_path, fecha, estructura)

    ruta_resultante = raiz
    if seg_primario:
        ruta_resultante = ruta_resultante / seg_primario
    if seg_secundario:
        ruta_resultante = ruta_resultante / seg_secundario

    return ruta_resultante / archivo_path.name


def generar_nombre_unico(ruta_base: Path, nombres_reservados: set) -> Path:
    stem = ruta_base.stem
    suffix = ruta_base.suffix
    parent = ruta_base.parent

    contador = 1
    nueva_ruta = ruta_base
    while nueva_ruta.exists() or nueva_ruta in nombres_reservados:
        nueva_ruta = parent / f"{stem} ({contador}){suffix}"
        contador += 1

    return nueva_ruta


def generar_plan_con_estructura(
    origen: Union[str, Path],
    destino_base: Union[str, Path],
    extensiones: Optional[List[str]] = None,
    incluir_subcarpetas: bool = True,
    usar_exif: bool = True,
    usar_hash_duplicados: bool = False,
    estructura: Optional[Dict[str, Any]] = None,
    filtros_avanzados: Optional[Dict[str, Any]] = None
) -> ServiceResult:
    filt_av = filtros_avanzados or {}

    res_archivos = obtener_archivos(
        ruta_origen=origen,
        extensiones_permitidas=extensiones,
        incluir_subcarpetas=incluir_subcarpetas,
        tamano_min_bytes=filt_av.get('tamano_min_bytes'),
        tamano_max_bytes=filt_av.get('tamano_max_bytes'),
        dias_antiguedad=filt_av.get('dias_antiguedad'),
        usar_creacion=filt_av.get('usar_creacion_filtro', False),
        incluir_ocultos=filt_av.get('incluir_ocultos', False),
        patron_regex=filt_av.get('patron_regex')
    )

    if not res_archivos.success:
        return res_archivos

    archivos: List[Path] = res_archivos.data
    planes: List[Dict[str, Any]] = []

    for arch in archivos:
        try:
            f_date = extraer_fecha(arch, usar_exif=usar_exif)
        except FechaNoEncontradaError:
            f_date = None

        dest = generar_ruta_destino(arch, f_date, destino_base, estructura)
        planes.append({
            'origen': arch,
            'destino': dest,
            'fecha': f_date,
            'accion': 'mover'
        })

    planes = detectar_duplicados_por_nombre(planes, destino_base)
    if usar_hash_duplicados:
        planes = detectar_duplicados_por_hash(planes, destino_base, usar_hash=True)

    app_logger.info(f"Plan generado: {len(planes)} operaciones planificadas.")
    return ServiceResult(success=True, data=planes)


def detectar_duplicados_por_nombre(planes: List[Dict[str, Any]], carpeta_raiz_destino: Union[str, Path]) -> List[Dict[str, Any]]:
    raiz = Path(carpeta_raiz_destino)
    carpeta_duplicadas = raiz / "Duplicadas"

    destinos_map: Dict[Path, List[Dict[str, Any]]] = {}
    for plan in planes:
        dest = plan['destino']
        destinos_map.setdefault(dest, []).append(plan)

    nombres_reservados = set()

    for dest, lista_planes in destinos_map.items():
        if len(lista_planes) == 1:
            nombres_reservados.add(dest)
        else:
            primer_plan = lista_planes[0]
            nombres_reservados.add(primer_plan['destino'])
            for plan_dup in lista_planes[1:]:
                plan_dup['accion'] = 'duplicado'
                destino_dup_base = carpeta_duplicadas / plan_dup['origen'].name
                nuevo_destino = generar_nombre_unico(destino_dup_base, nombres_reservados)
                plan_dup['destino'] = nuevo_destino
                nombres_reservados.add(nuevo_destino)

    return planes


def _calcular_hash_md5(archivo_path: Path) -> Optional[str]:
    hasher = hashlib.md5()
    try:
        with open(archivo_path, 'rb') as f:
            while chunk := f.read(AppConfig.BUFFER_SIZE):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception as e:
        app_logger.warning(f"No se pudo calcular Hash MD5 de '{archivo_path.name}': {e}")
        return None


def detectar_duplicados_por_hash(planes: List[Dict[str, Any]], carpeta_raiz_destino: Union[str, Path], usar_hash: bool = True) -> List[Dict[str, Any]]:
    if not usar_hash:
        return planes

    raiz = Path(carpeta_raiz_destino)
    carpeta_duplicadas = raiz / "Duplicadas"
    nombres_reservados = {p['destino'] for p in planes}
    hashes_map: Dict[str, List[Dict[str, Any]]] = {}

    for plan in planes:
        if plan['accion'] == 'duplicado':
            continue
        h_val = _calcular_hash_md5(plan['origen'])
        if h_val:
            hashes_map.setdefault(h_val, []).append(plan)

    for h_val, lista_planes in hashes_map.items():
        if len(lista_planes) > 1:
            for plan_dup in lista_planes[1:]:
                nombres_reservados.discard(plan_dup['destino'])
                plan_dup['accion'] = 'duplicado'
                destino_dup_base = carpeta_duplicadas / plan_dup['origen'].name
                nuevo_destino = generar_nombre_unico(destino_dup_base, nombres_reservados)
                plan_dup['destino'] = nuevo_destino
                nombres_reservados.add(nuevo_destino)

    return planes


def ejecutar_plan_con_modo(
    planes: List[Dict[str, Any]],
    modo: str = "Copiar",
    callback_progreso: Optional[Callable[[int, int, str], None]] = None,
    cancelar_flag: Optional[Callable[[], bool]] = None,
) -> ServiceResult:
    """Ejecuta el plan registrando eventos en app_logger."""
    if not planes:
        return ServiceResult(success=True, data="No hay planes para ejecutar.")

    exitos = 0
    errores = 0
    logs: List[str] = []

    modo_norm = modo.strip().capitalize()
    es_copia = (modo_norm == "Copiar")
    verbo_log = "COPIAR" if es_copia else "MOVER"

    nombres_reservados: set = {p['destino'] for p in planes}

    # Verificación preventiva de espacio en disco si el modo es copiar
    if es_copia and planes:
        bytes_requeridos = 0
        for plan in planes:
            orig = plan.get('origen')
            if orig and Path(orig).is_file():
                try:
                    bytes_requeridos += Path(orig).stat().st_size
                except Exception:
                    pass

        primer_dest = planes[0].get('destino')
        target_dir = Path(primer_dest).parent if primer_dest else Path(".")
        check_dir = target_dir
        while not check_dir.exists() and check_dir != check_dir.parent:
            check_dir = check_dir.parent

        try:
            espacio_libre = shutil.disk_usage(str(check_dir)).free
            # Margen de seguridad de 20MB
            if bytes_requeridos > 0 and (bytes_requeridos + 20 * 1024 * 1024) > espacio_libre:
                app_logger.error(
                    f"Espacio insuficiente en disco destino '{check_dir}': "
                    f"requerido={bytes_requeridos}B, libre={espacio_libre}B"
                )
                return ServiceResult.fail(
                    error=_("Espacio insuficiente en el disco de destino. Requerido: {req:.2f} MB, Disponible: {disp:.2f} MB").format(
                        req=bytes_requeridos / (1024 * 1024),
                        disp=espacio_libre / (1024 * 1024)
                    ),
                    error_code=ErrorCode.ERR_DISK_FULL
                )
        except Exception as e:
            app_logger.warning(f"No se pudo verificar el espacio en disco para '{check_dir}': {e}")

    app_logger.info(f"Iniciando ejecución de {len(planes)} archivos en modo [{verbo_log}]")
    buffer_undo: List[Dict[str, Any]] = []

    for i, plan in enumerate(planes, start=1):
        if cancelar_flag and cancelar_flag():
            if buffer_undo:
                registrar_operacion_undo(buffer_undo)
                buffer_undo.clear()
            app_logger.warning(_("Ejecución cancelada por el usuario."))
            return ServiceResult(
                success=False,
                error=_("Operación cancelada por el usuario."),
                error_code=ErrorCode.ERR_EXECUTION_CANCELLED,
                data=logs
            )

        origen: Path = plan['origen']
        destino: Path = plan['destino']
        accion: str = plan['accion'].lower()

        if callback_progreso:
            callback_progreso(i, len(planes), origen.name)

        if accion not in ('mover', 'copiar', 'duplicado'):
            app_logger.warning(f"[{i}/{len(planes)}] Ignorado: Acción '{accion}' desconocida.")
            continue

        try:
            if not origen.exists():
                raise FileNotFoundError(f"El archivo origen '{origen}' no existe.")

            destino.parent.mkdir(parents=True, exist_ok=True)

            destino_final = destino
            if destino_final.exists() or destino_final in nombres_reservados:
                nombres_reservados.discard(destino_final)
                destino_final = generar_nombre_unico(destino, nombres_reservados)
                nombres_reservados.add(destino_final)

            if es_copia or accion == 'copiar':
                shutil.copy2(str(origen), str(destino_final))
            else:
                shutil.move(str(origen), str(destino_final))

            buffer_undo.append({
                'timestamp': datetime.now().isoformat(),
                'modo': modo_norm,
                'origen': str(origen),
                'destino': str(destino_final),
                'nombre_original': origen.name,
                'nombre_final': destino_final.name
            })
            if len(buffer_undo) >= 50:
                registrar_operacion_undo(buffer_undo)
                buffer_undo.clear()

            exitos += 1
            msg_ok = f"[{i}/{len(planes)}] OK [{verbo_log}]: '{origen.name}' ➔ '{destino_final.name}'"
            app_logger.info(msg_ok)
            logs.append(msg_ok)

        except PermissionError as pe:
            errores += 1
            msg_err = f"[{i}/{len(planes)}] ERROR Permisos en '{origen.name}': {pe}"
            app_logger.error(msg_err, exc_info=True)
            logs.append(msg_err)

        except OSError as oe:
            errores += 1
            msg_err = f"[{i}/{len(planes)}] ERROR I/O en '{origen.name}': {oe}"
            app_logger.error(msg_err, exc_info=True)
            logs.append(msg_err)

        except Exception as e:
            errores += 1
            msg_err = f"[{i}/{len(planes)}] ERROR inesperado en '{origen.name}': {e}"
            app_logger.error(msg_err, exc_info=True)
            logs.append(msg_err)

    if buffer_undo:
        registrar_operacion_undo(buffer_undo)
        buffer_undo.clear()

    app_logger.info(f"Ejecución completada: {exitos} exitosos | {errores} errores.")

    return ServiceResult(
        success=(errores == 0),
        data={"exitos": exitos, "errores": errores, "logs": logs},
        error=_("Proceso finalizado con errores.") if errores > 0 else None,
        error_code=ErrorCode.ERR_IO_FAILURE if errores > 0 else None
    )


def registrar_operacion_undo(operaciones: List[Dict[str, Any]], log_file_path: Optional[Path] = None):
    path = log_file_path or AppConfig.UNDO_FILE
    try:
        with open(path, 'a', encoding='utf-8') as f:
            for op in operaciones:
                f.write(json.dumps(op, ensure_ascii=False) + '\n')
    except Exception as e:
        app_logger.error(f"Fallo al registrar en archivo Undo: {e}")


def obtener_historial_undo(limite: int = 100, log_file_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    path = log_file_path or AppConfig.UNDO_FILE
    if not path.exists():
        return []

    dq = deque(maxlen=limite)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                l_str = line.strip()
                if l_str:
                    try:
                        dq.append(json.loads(l_str))
                    except Exception as e:
                        app_logger.debug(f"Línea JSON inválida en Undo omitida: {e}")
    except Exception as e:
        app_logger.error(f"Error leyendo historial Undo: {e}")
        return []

    return list(dq)


def deshacer_n_operaciones(n: int = 1, dry_run: bool = False, log_file_path: Optional[Path] = None) -> ServiceResult:
    path = log_file_path or AppConfig.UNDO_FILE
    if not path.exists():
        return ServiceResult(success=False, error=_("No existe historial Undo."), error_code=ErrorCode.ERR_UNDO_EMPTY)

    historial = obtener_historial_undo(limite=999999, log_file_path=path)
    if not historial:
        return ServiceResult(success=False, error=_("El historial Undo está vacío."), error_code=ErrorCode.ERR_UNDO_EMPTY)

    a_revertir = historial[-n:]
    restantes = historial[:-n]

    exitos = 0
    errores = 0
    logs = []

    for i, op in enumerate(reversed(a_revertir), start=1):
        modo = op.get('modo', 'Mover').capitalize()
        origen = Path(op['origen'])
        destino = Path(op['destino'])

        if dry_run:
            exitos += 1
            logs.append(f"[SIMULACIÓN {i}] Revertir '{destino}' ➔ '{origen}'")
            continue

        try:
            if modo == 'Mover':
                if not destino.exists():
                    errores += 1
                    logs.append(f"[{i}] ERROR: '{destino.name}' no existe.")
                    continue
                origen.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(destino), str(origen))
                logs.append(f"[{i}] REVERTIDO [MOVER]: '{destino.name}' ➔ '{origen.name}'")
            else:
                if destino.exists():
                    destino.unlink()
                    logs.append(f"[{i}] REVERTIDO [COPIAR]: Eliminada copia en '{destino.name}'")
            exitos += 1
        except Exception as e:
            errores += 1
            msg_err = f"[{i}] ERROR al deshacer '{destino.name}': {e}"
            app_logger.error(msg_err, exc_info=True)
            logs.append(msg_err)

    if not dry_run:
        try:
            temp_dir = path.parent
            with tempfile.NamedTemporaryFile('w', dir=temp_dir, delete=False, encoding='utf-8') as tf:
                temp_name = tf.name
                for op in restantes:
                    tf.write(json.dumps(op, ensure_ascii=False) + '\n')
            os.replace(temp_name, path)
        except Exception as e:
            app_logger.error(f"Fallo al actualizar de forma atómica el historial Undo: {e}")

    return ServiceResult(success=(errores == 0), data={"exitos": exitos, "errores": errores, "logs": logs})


def clonar_carpeta(
    origen: Union[str, Path],
    destino: Union[str, Path],
    incremental: bool = False,
    callback_progreso: Optional[Callable[[int, int, int, int, str], None]] = None,
    cancelar_flag: Optional[Callable[[], bool]] = None
) -> ServiceResult:
    p_orig = Path(origen)
    p_dest = Path(destino)

    if not p_orig.exists() or not p_orig.is_dir():
        return ServiceResult(success=False, error=_("La ruta de origen no es válida."), error_code=ErrorCode.ERR_ORIGIN_NOT_FOUND)

    try:
        archivos = [p for p in p_orig.rglob('*') if p.is_file()]
    except Exception as e:
        app_logger.error(f"Fallo escaneando archivos en '{p_orig}': {e}")
        return ServiceResult(success=False, error=str(e), error_code=ErrorCode.ERR_IO_FAILURE)

    total = len(archivos)
    if total == 0:
        return ServiceResult(success=True, data={"copiados": 0, "omitidos": 0, "errores": 0, "bytes_copiados": 0})

    # Calcular tamaño total en bytes para porcentaje de avance preciso
    bytes_totales = 0
    for a in archivos:
        try:
            bytes_totales += a.stat().st_size
        except Exception:
            pass

    # Verificación preventiva de espacio en disco destino
    check_dest = p_dest
    while not check_dest.exists() and check_dest != check_dest.parent:
        check_dest = check_dest.parent

    try:
        espacio_libre = shutil.disk_usage(str(check_dest)).free
        if bytes_totales > 0 and (bytes_totales + 20 * 1024 * 1024) > espacio_libre:
            app_logger.error(
                f"Espacio insuficiente en disco destino '{check_dest}' para clonar: "
                f"requerido={bytes_totales}B, libre={espacio_libre}B"
            )
            return ServiceResult.fail(
                error=_("Espacio insuficiente en el disco de destino para clonar. Requerido: {req:.2f} MB, Disponible: {disp:.2f} MB").format(
                    req=bytes_totales / (1024 * 1024),
                    disp=espacio_libre / (1024 * 1024)
                ),
                error_code=ErrorCode.ERR_DISK_FULL
            )
    except Exception as e:
        app_logger.warning(f"No se pudo verificar el espacio en disco para '{check_dest}': {e}")

    exitos = 0
    omitidos = 0
    errores = 0
    bytes_copiados = 0

    for i, arch in enumerate(archivos, start=1):
        if cancelar_flag and cancelar_flag():
            return ServiceResult(success=False, error=_("Clonación cancelada."), error_code=ErrorCode.ERR_EXECUTION_CANCELLED)

        tamano_arch = 0
        try:
            tamano_arch = arch.stat().st_size
        except Exception:
            pass

        if callback_progreso:
            callback_progreso(i, total, bytes_copiados, bytes_totales, arch.name)

        rel = arch.relative_to(p_orig)
        dest_arch = p_dest / rel

        try:
            dest_arch.parent.mkdir(parents=True, exist_ok=True)
            if incremental and dest_arch.exists():
                st_d = dest_arch.stat()
                if tamano_arch == st_d.st_size and abs(arch.stat().st_mtime - st_d.st_mtime) < 1.0:
                    omitidos += 1
                    bytes_copiados += tamano_arch
                    continue
            shutil.copy2(str(arch), str(dest_arch))
            exitos += 1
            bytes_copiados += tamano_arch
        except Exception as e:
            errores += 1
            app_logger.warning(f"Error al clonar '{arch.name}': {e}")

    # Callback final de 100%
    if callback_progreso:
        callback_progreso(total, total, bytes_totales, bytes_totales, "Completado")

    return ServiceResult(success=(errores == 0), data={"copiados": exitos, "omitidos": omitidos, "errores": errores, "bytes_copiados": bytes_copiados})


def analizar_estructura_destino(destino_base: Union[str, Path]) -> Dict[str, Any]:
    path_dest = Path(destino_base)
    resultado: Dict[str, Any] = {'existe': path_dest.exists() and path_dest.is_dir(), 'tipo': 'desconocido', 'ejemplo': '', 'carpetas': [], 'estructura_sugerida': {}}
    if not resultado['existe']:
        return resultado

    try:
        carpetas_nivel1 = [p for p in path_dest.iterdir() if p.is_dir()]
        resultado['carpetas'] = [c.name for c in carpetas_nivel1[:10]]
        if not carpetas_nivel1:
            resultado['tipo'] = 'vacio'
            return resultado

        nombres1 = [c.name for c in carpetas_nivel1]
        anios = [n for n in nombres1 if re.match(r'^(19|20)\d{2}$', n)]
        if len(anios) >= 1:
            resultado['tipo'] = 'fecha'
            sub_c = list((path_dest / anios[0]).iterdir())
            sub_dirs = [s.name for s in sub_c if s.is_dir()]
            resultado['estructura_sugerida'] = {'criterio_primario': 'fecha', 'criterio_secundario': 'ninguno', 'formato_fecha': '{YYYY}/{MM}' if sub_dirs else '{YYYY}'}
            return resultado
    except Exception as e:
        app_logger.warning(f"No se pudo analizar la estructura de destino '{path_dest}': {e}")

    return resultado


def limpiar_carpetas_vacias(directorio_raiz: Union[str, Path], dry_run: bool = False) -> List[Path]:
    raiz = Path(directorio_raiz)
    eliminadas: List[Path] = []
    if not raiz.exists() or not raiz.is_dir():
        return eliminadas

    for dirpath, dirnames, filenames in os.walk(raiz, topdown=False):
        p = Path(dirpath)
        if p == raiz:
            continue
        try:
            if not any(p.iterdir()):
                if not dry_run:
                    p.rmdir()
                eliminadas.append(p)
        except Exception as e:
            app_logger.debug(f"No se pudo eliminar carpeta vacía '{p.name}': {e}")

    return eliminadas


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

def respaldo_inteligente_windows_linux(
    perfiles: List[str],
    destino: Union[str, Path],
    callback_progreso: Optional[Callable[[int, int, int, int, str], None]] = None,
    cancelar_flag: Optional[Callable[[], bool]] = None
) -> ServiceResult:
    """
    Respalda perfiles estándar (Documentos, Escritorio, etc.) omitiendo cachés y basura.
    """
    p_dest = Path(destino)

    if not p_dest.exists() or not p_dest.is_dir():
        return ServiceResult(success=False, error=_("La ruta de destino no es válida."), error_code=ErrorCode.ERR_DESTINATION_NOT_FOUND)

    carpetas_usuario = {d['nombre']: Path(d['ruta']) for d in detectar_carpetas_usuario()}
    carpetas_a_respaldar = []

    for perfil in perfiles:
        if perfil in carpetas_usuario:
            carpetas_a_respaldar.append(carpetas_usuario[perfil])

    if not carpetas_a_respaldar:
        return ServiceResult(success=False, error=_("No se encontraron los perfiles seleccionados o están vacíos."), error_code=ErrorCode.ERR_ORIGIN_NOT_FOUND)

    # Filtros inteligentes
    patrones_basura = [
        re.compile(r'\.tmp$', re.IGNORECASE),
        re.compile(r'\.bak$', re.IGNORECASE),
        re.compile(r'~$', re.IGNORECASE),
        re.compile(r'Thumbs\.db$', re.IGNORECASE),
        re.compile(r'desktop\.ini$', re.IGNORECASE),
    ]

    directorios_omitir = [
        'AppData', 'Local Settings', 'Application Data', '.cache',
        'node_modules', '__pycache__', 'temp', 'tmp', '.npm', '.cargo'
    ]

    archivos_totales = []

    # Recolectar archivos aplicando filtro de directorios
    def escanear_inteligente(dir_path: Path):
        try:
            with os.scandir(dir_path) as it:
                for entry in it:
                    if entry.is_file():
                        yield Path(entry.path)
                    elif entry.is_dir():
                        if entry.name not in directorios_omitir and not entry.name.startswith('.'):
                            yield from escanear_inteligente(Path(entry.path))
        except Exception:
            pass

    for carpeta in carpetas_a_respaldar:
        archivos_totales.extend(list(escanear_inteligente(carpeta)))

    total = len(archivos_totales)
    if total == 0:
        return ServiceResult(success=True, data={"copiados": 0, "omitidos": 0, "errores": 0, "bytes_copiados": 0})

    bytes_totales = sum(a.stat().st_size for a in archivos_totales if a.exists())

    check_dest = p_dest
    while not check_dest.exists() and check_dest != check_dest.parent:
        check_dest = check_dest.parent

    try:
        espacio_libre = shutil.disk_usage(str(check_dest)).free
        if bytes_totales > 0 and (bytes_totales + 20 * 1024 * 1024) > espacio_libre:
            return ServiceResult.fail(
                error=_("Espacio insuficiente en el disco de destino para el respaldo. Requerido: {req:.2f} MB, Disponible: {disp:.2f} MB").format(
                    req=bytes_totales / (1024 * 1024),
                    disp=espacio_libre / (1024 * 1024)
                ),
                error_code=ErrorCode.ERR_DISK_FULL
            )
    except Exception:
        pass

    copiados = 0
    omitidos = 0
    errores = 0
    bytes_copiados = 0
    home_dir = Path.home()

    for idx, a in enumerate(archivos_totales):
        if cancelar_flag and cancelar_flag():
            app_logger.info("Respaldo inteligente cancelado por el usuario.")
            break

        if callback_progreso:
            callback_progreso(copiados, omitidos, errores, total, a.name)

        # Omitir archivos basura
        es_basura = any(patron.search(a.name) for patron in patrones_basura)
        if es_basura:
            omitidos += 1
            continue

        try:
            # Mantener la estructura relativa al home directory
            try:
                ruta_relativa = a.relative_to(home_dir)
            except ValueError:
                # Fallback si no está en home
                ruta_relativa = Path(a.name)

            destino_final = p_dest / ruta_relativa
            destino_final.parent.mkdir(parents=True, exist_ok=True)

            stat_orig = a.stat()
            size_orig = stat_orig.st_size
            mtime_orig = stat_orig.st_mtime

            necesita_copia = True
            if destino_final.exists():
                stat_dest = destino_final.stat()
                if stat_dest.st_size == size_orig and abs(stat_dest.st_mtime - mtime_orig) < 2.0:
                    necesita_copia = False

            if necesita_copia:
                shutil.copy2(a, destino_final)
                copiados += 1
                bytes_copiados += size_orig
            else:
                omitidos += 1

        except Exception as e:
            app_logger.warning(f"Error copiando '{a}' en respaldo: {e}")
            errores += 1

    return ServiceResult(success=True, data={
        "copiados": copiados,
        "omitidos": omitidos,
        "errores": errores,
        "bytes_copiados": bytes_copiados
    })
