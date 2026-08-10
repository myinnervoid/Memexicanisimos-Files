"""
Modulo core.py - Funciones puras para organizacion de archivos por fecha.

Este modulo contiene las funciones logicas de busqueda, inspeccion y clasificacion
de archivos sin realizar modificaciones en el sistema de archivos (operaciones puras).
"""

from datetime import datetime, date, timedelta
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Union, Tuple, Any, Callable

# Importaciones condicionales para dependencias opcionales
try:
    import mutagen
    MUTAGEN_DISPONIBLE = True
except ImportError:
    MUTAGEN_DISPONIBLE = False

try:
    import pyudev
    PYUDEV_DISPONIBLE = True
except ImportError:
    PYUDEV_DISPONIBLE = False


# Intentamos importar PIL para metadatos EXIF.
# Si no esta disponible, el modulo seguira funcionando usando fechas por regex/mtime.
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


# Excepciones personalizadas para un control de errores limpio
class RutaNoValidaError(Exception):
    """Se lanza cuando la ruta especificada no existe o no es un directorio."""
    pass


class FechaNoEncontradaError(Exception):
    """Se lanza cuando no se puede determinar la fecha de un archivo por ningún método."""
    pass


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
) -> List[Path]:
    """
    Obtiene la lista de archivos en una ruta dada, filtrando por multiples criterios.

    :param ruta_origen: Ruta del directorio a explorar (str o Path).
    :param extensiones_permitidas: Lista de extensiones (ej. ['.jpg', '.png']). None acepta todas.
    :param incluir_subcarpetas: Si es True, explora subdirectorios recursivamente.
    :param tamano_min_bytes: Si se especifica, excluye archivos mas pequenos que este valor en bytes.
    :param tamano_max_bytes: Si se especifica, excluye archivos mas grandes que este valor en bytes.
    :param dias_antiguedad: Si se especifica (>0), solo incluye archivos modificados/creados en los
                            ultimos N dias.
    :param usar_creacion: Si es True, usa st_ctime para el filtro de antiguedad; si no, st_mtime.
    :param incluir_ocultos: Si es False, excluye archivos cuyo nombre comienza con '.'.
    :param patron_regex: Si se especifica, solo incluye archivos cuyo nombre coincide con el patron.
                         Se aplica DESPUES del filtro de extensiones (logica AND).
    :return: Lista de objetos Path correspondientes a los archivos encontrados.
    :raises RutaNoValidaError: Si la ruta no existe o no es un directorio.
    """
    origen_path = Path(ruta_origen)

    if not origen_path.exists() or not origen_path.is_dir():
        raise RutaNoValidaError(f"La ruta '{ruta_origen}' no existe o no es un directorio valido.")

    # Normalizar extensiones a minusculas
    exts_norm = None
    if extensiones_permitidas:
        exts_norm = [
            ext.lower() if ext.startswith(".") else f".{ext.lower()}"
            for ext in extensiones_permitidas
        ]

    # Compilar regex si se proporciona
    regex_compilado = None
    if patron_regex:
        try:
            regex_compilado = re.compile(patron_regex)
        except re.error:
            regex_compilado = None

    # Calcular fecha limite para filtro de antiguedad
    fecha_limite = None
    if dias_antiguedad is not None and dias_antiguedad > 0:
        fecha_limite = datetime.now() - timedelta(days=dias_antiguedad)

    # Solo llamar a stat() si algun filtro de tamano/fecha lo requiere (optimizacion de rendimiento)
    necesita_stat = (
        tamano_min_bytes is not None or
        tamano_max_bytes is not None or
        fecha_limite is not None
    )

    # Recorrido del directorio
    if incluir_subcarpetas:
        iterador = origen_path.rglob("*")
    else:
        iterador = origen_path.iterdir()

    archivos_encontrados: List[Path] = []

    for elemento in iterador:
        if not elemento.is_file():
            continue

        # Filtro de archivos ocultos
        if not incluir_ocultos and elemento.name.startswith('.'):
            continue

        # Filtro por extension
        if exts_norm is not None and elemento.suffix.lower() not in exts_norm:
            continue

        # Filtro por regex (aplicado despues de extensiones — logica AND)
        if regex_compilado and not regex_compilado.search(elemento.name):
            continue

        # Filtros por tamano y antiguedad (stat() solo cuando es necesario)
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
            except OSError:
                pass  # Si falla stat(), incluir el archivo igualmente

        archivos_encontrados.append(elemento)

    return archivos_encontrados


CATEGORIAS_EXT = {
    "Documentos": ["pdf", "docx", "txt", "xlsx", "pptx", "odt"],
    "Imagen": ["jpg", "jpeg", "png", "gif", "bmp", "tiff", "svg"],
    "Audio": ["mp3", "wav", "flac", "aac"],
    "Video": ["mp4", "avi", "mkv", "mov", "wmv"],
    "Codigo": ["py", "js", "html", "css", "java", "c", "cpp", "go", "rs"],
    "Comprimidos": ["zip", "rar", "7z", "tar", "gz"]
}


def obtener_categoria(extension: str) -> str:
    """
    Devuelve la categoría a partir de una extensión de archivo.
    Si no se encuentra en las categorías conocidas, retorna 'Otros'.

    :param extension: Extensión del archivo (con o sin punto).
    :return: Nombre de la categoría.
    """
    ext_limpia = extension.lstrip(".").lower()
    for cat, exts in CATEGORIAS_EXT.items():
        if ext_limpia in exts:
            return cat
    return "Otros"


def extraer_fecha(
    archivo_path: Path,
    usar_exif: bool = True,
    usar_creacion: bool = False
) -> date:
    """
    Extrae la fecha asociada a un archivo intentando los siguientes metodos en orden:
    1. Patron de fecha en el nombre del archivo (expresiones regulares).
    2. Metadatos EXIF (si es una imagen soportada y `usar_exif=True`).
    3. Fecha del sistema de archivos (ctime si `usar_creacion=True`, mtime en caso contrario).

    :param archivo_path: Objeto Path del archivo.
    :param usar_exif: Si es True, intenta leer metadatos EXIF de imagenes.
    :param usar_creacion: Si es True, usa st_ctime en lugar de st_mtime como ultimo recurso.
    :return: Objeto datetime.date con la fecha detectada.
    :raises FechaNoEncontradaError: Si ocurre un error irrecuperable al obtener la fecha.
    """
    if not isinstance(archivo_path, Path):
        archivo_path = Path(archivo_path)

    nombre = archivo_path.name

    # ---------------------------------------------------------
    # METODO 1: Expresiones Regulares sobre el nombre del archivo
    # ---------------------------------------------------------
    patrones_regex = [
        # YYYYMMDD (8 digitos seguidos, ej: 20230514)
        (r'(?<!\d)(19\d\d|20\d\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)', "%Y%m%d"),
        
        # YYYY-MM-DD o YYYY_MM_DD (ej: 2023-05-14 o 2023_05_14)
        (r'(?<!\d)(19\d\d|20\d\d)[-_](0[1-9]|1[0-2])[-_](0[1-9]|[12]\d|3[01])(?!\d)', "%Y-%m-%d"),
        
        # YYYY.MM.DD (ej: 2023.05.14)
        (r'(?<!\d)(19\d\d|20\d\d)\.(0[1-9]|1[0-2])\.(0[1-9]|[12]\d|3[01])(?!\d)', "%Y.%m.%d"),
        
        # DD-MM-YYYY o DD_MM_YYYY (ej: 14-05-2023 o 14_05_2023)
        (r'(?<!\d)(0[1-9]|[12]\d|3[01])[-_](0[1-9]|1[0-2])[-_](19\d\d|20\d\d)(?!\d)', "%d-%m-%Y"),

        # DD.MM.YYYY (ej: 14.05.2023)
        (r'(?<!\d)(0[1-9]|[12]\d|3[01])\.(0[1-9]|1[0-2])\.(19\d\d|20\d\d)(?!\d)', "%d.%m.%Y"),
    ]

    for patron, formato in patrones_regex:
        coincidencia = re.search(patron, nombre)
        if coincidencia:
            texto_fecha = coincidencia.group(0)
            if formato == "%Y-%m-%d" or formato == "%d-%m-%Y":
                texto_fecha = texto_fecha.replace("_", "-")
            
            try:
                dt = datetime.strptime(texto_fecha, formato)
                return dt.date()
            except ValueError:
                pass

    # ---------------------------------------------------------
    # METODO 2: Lectura de Metadatos EXIF (para imagenes)
    # ---------------------------------------------------------
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
                            anio, mes, dia = map(int, partes)
                            return date(anio, mes, dia)
        except Exception:
            pass

    # ---------------------------------------------------------
    # METODO 3: Fecha del sistema de archivos (ctime / mtime)
    # ---------------------------------------------------------
    try:
        stat_info = archivo_path.stat()
        timestamp = stat_info.st_ctime if usar_creacion else stat_info.st_mtime
        return datetime.fromtimestamp(timestamp).date()
    except Exception as e:
        raise FechaNoEncontradaError(
            f"No se pudo determinar la fecha para el archivo '{archivo_path.name}': {e}"
        )


def clasificar_por_fecha(
    archivos: List[Path],
    usar_exif: bool = True,
    usar_creacion: bool = False
) -> Dict[Optional[date], List[Path]]:
    """
    Toma una lista de rutas de archivo y los agrupa en un diccionario por fecha.

    :param archivos: Lista de objetos Path.
    :param usar_exif: Si se debe intentar extraer metadatos EXIF.
    :param usar_creacion: Si es True, usa st_ctime en lugar de st_mtime como fallback.
    :return: Diccionario con llaves date (o None si fallo) y valores lista de Path.
    """
    clasificacion: Dict[Optional[date], List[Path]] = {}

    for archivo in archivos:
        try:
            fecha_obtenida = extraer_fecha(archivo, usar_exif=usar_exif, usar_creacion=usar_creacion)
        except FechaNoEncontradaError:
            fecha_obtenida = None

        if fecha_obtenida not in clasificacion:
            clasificacion[fecha_obtenida] = []
        
        clasificacion[fecha_obtenida].append(archivo)

    return clasificacion


def generar_plan(
    origen: Union[str, Path],
    destino_base: Union[str, Path],
    extensiones: Optional[List[str]] = None,
    incluir_subcarpetas: bool = True,
    usar_exif: bool = True,
    usar_hash_duplicados: bool = False,
    estructura: Optional[Dict[str, Any]] = None,
    filtros_avanzados: Optional[Dict[str, Any]] = None
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Funcion maestra pura que genera un plan de ejecucion para organizar archivos.

    :param origen: Ruta del directorio a organizar.
    :param destino_base: Ruta del directorio donde se organizaran los archivos.
    :param extensiones: Lista opcional de extensiones permitidas.
    :param incluir_subcarpetas: Si es True, analiza subcarpetas recursivamente.
    :param usar_exif: Si es True, intenta leer metadatos EXIF de imagenes.
    :param usar_hash_duplicados: Si es True, detecta duplicados reales por hash binario MD5.
    :param estructura: Diccionario opcional con parametros de criterios organizativos y renombrado.
    :param filtros_avanzados: Diccionario opcional con filtros avanzados (tamano, antiguedad, ocultos, regex).
    :return: Tupla de (planes, lista_errores).
             planes: List[Dict] con claves 'origen', 'destino', 'fecha', 'accion'.
             lista_errores: List[Dict] con claves 'archivo', 'error'.
    """
    planes: List[Dict[str, Any]] = []
    lista_errores: List[Dict[str, Any]] = []

    # Extraer parametros de filtros avanzados
    filtros_av = filtros_avanzados or {}
    tamano_min = filtros_av.get('tamano_min_bytes')
    tamano_max = filtros_av.get('tamano_max_bytes')
    dias_ant = filtros_av.get('dias_antiguedad')
    usar_creacion_filt = filtros_av.get('usar_creacion_filtro', False)
    incl_ocultos = filtros_av.get('incluir_ocultos', False)
    patron_rx = filtros_av.get('patron_regex') or None

    # a) Obtener archivos con todos los filtros aplicados
    try:
        archivos = obtener_archivos(
            ruta_origen=origen,
            extensiones_permitidas=extensiones,
            incluir_subcarpetas=incluir_subcarpetas,
            tamano_min_bytes=tamano_min,
            tamano_max_bytes=tamano_max,
            dias_antiguedad=dias_ant,
            usar_creacion=usar_creacion_filt,
            incluir_ocultos=incl_ocultos,
            patron_regex=patron_rx,
        )
    except RutaNoValidaError as e:
        lista_errores.append({'archivo': Path(origen), 'error': str(e)})
        return ([], lista_errores)

    usar_creacion_fecha = False
    if estructura and isinstance(estructura, dict):
        usar_creacion_fecha = estructura.get('usar_fecha_creacion', False)

    # b) Clasificar por fecha
    clasificados = clasificar_por_fecha(archivos, usar_exif=usar_exif, usar_creacion=usar_creacion_fecha)

    # c) Extraer configuracion de renombrado desde estructura
    plantilla_nombre = None
    activar_renombrado = False
    fmt_fecha_plantilla = '{YYYY}-{MM}-{DD}'
    if estructura and isinstance(estructura, dict):
        activar_renombrado = estructura.get('activar_renombrado', False)
        if activar_renombrado:
            plantilla_nombre = estructura.get('plantilla_nombre') or None
        fmt_fecha_plantilla = estructura.get('formato_fecha', '{YYYY}-{MM}-{DD}')

    # d) Aplanar y ordenar para asignacion consistente de contadores
    archivos_planos = sorted(
        [
            (fecha_val, arch)
            for fecha_val, lista_archivos in clasificados.items()
            for arch in lista_archivos
        ],
        key=lambda x: str(x[1])
    )

    # e) Construir planes iniciales con accion 'mover'
    for contador, (fecha_val, arch) in enumerate(archivos_planos, start=1):
        try:
            dest_path = generar_ruta_destino(
                archivo_path=arch,
                fecha=fecha_val,
                carpeta_raiz_destino=destino_base,
                estructura=estructura
            )
            # Aplicar plantilla de renombrado si esta activa
            if activar_renombrado and plantilla_nombre:
                nuevo_nombre = renombrar_archivo(
                    arch, plantilla_nombre, fecha_val, contador, fmt_fecha_plantilla
                )
                dest_path = dest_path.parent / nuevo_nombre

            planes.append({
                'origen': arch,
                'destino': dest_path,
                'fecha': fecha_val,
                'accion': 'mover'
            })
        except Exception as e:
            lista_errores.append({'archivo': arch, 'error': f"Error al generar ruta destino: {e}"})

    # f) Detectar duplicados por nombre
    planes = detectar_duplicados_por_nombre(planes, carpeta_raiz_destino=destino_base)

    # g) Detectar duplicados por contenido/hash (opcional)
    planes = detectar_duplicados_por_hash(
        planes,
        carpeta_raiz_destino=destino_base,
        usar_hash=usar_hash_duplicados
    )

    return (planes, lista_errores)


def generar_plan_con_estructura(
    origen: Union[str, Path],
    destino_base: Union[str, Path],
    extensiones: Optional[List[str]] = None,
    incluir_subcarpetas: bool = True,
    usar_exif: bool = True,
    usar_hash_duplicados: bool = False,
    estructura: Optional[Dict[str, Any]] = None,
    filtros_avanzados: Optional[Dict[str, Any]] = None
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Funcion envolvente que genera un plan de ejecucion usando una estructura organizativa
    explicita y filtros avanzados opcionales.
    """
    return generar_plan(
        origen=origen,
        destino_base=destino_base,
        extensiones=extensiones,
        incluir_subcarpetas=incluir_subcarpetas,
        usar_exif=usar_exif,
        usar_hash_duplicados=usar_hash_duplicados,
        estructura=estructura,
        filtros_avanzados=filtros_avanzados
    )


def renombrar_archivo(
    archivo_path: Path,
    plantilla: str,
    fecha: Optional[date] = None,
    contador: int = 1,
    formato_fecha: str = '{YYYY}-{MM}-{DD}'
) -> str:
    """
    Genera un nuevo nombre de archivo a partir de una plantilla con placeholders.

    Placeholders soportados:
    - {nombre}         : Nombre del archivo sin extension
    - {ext}            : Extension sin punto (ej. jpg)
    - {fecha}          : Fecha formateada usando formato_fecha
    - {fecha_formato}  : Alias de {fecha}
    - {contador:NNNd}  : Contador con relleno de ceros (ej. {contador:03d})
    - {contador}       : Contador sin relleno
    - {artista}        : Artista (archivos de audio con mutagen)
    - {album}          : Album (archivos de audio)
    - {titulo}         : Titulo (archivos de audio)
    - {ano}            : Anio de lanzamiento (archivos de audio)
    - {genero}         : Genero musical (archivos de audio)
    - {caratula}       : 'si' o 'no' segun presencia de album art
    """
    stem = archivo_path.stem
    ext_sin_punto = archivo_path.suffix.lstrip('.').lower()

    # Formatear fecha para uso en nombre de archivo
    if fecha is not None:
        fecha_str = _formatear_fecha_estructura(fecha, formato_fecha)
        fecha_str = fecha_str.replace('/', '-').replace('\\', '-').replace(' ', '_')
    else:
        fecha_str = 'sin_fecha'

    resultado = plantilla

    # Extraer metadatos de audio si la plantilla usa placeholders de audio
    placeholders_audio = {'{artista}', '{album}', '{titulo}', '{ano}', '{genero}', '{caratula}'}
    if any(ph in resultado for ph in placeholders_audio):
        meta_audio = leer_metadatos_audio(archivo_path)
        for clave, val in meta_audio.items():
            resultado = resultado.replace(f"{{{clave}}}", str(val))

    # Reemplazar placeholders estandar
    resultado = re.sub(
        r'\{contador:(\d+)d\}',
        lambda m: f"{contador:0{int(m.group(1))}d}",
        resultado
    )
    resultado = resultado.replace('{contador}', str(contador))
    resultado = resultado.replace('{nombre}', stem)
    resultado = resultado.replace('{ext}', ext_sin_punto)
    resultado = resultado.replace('{fecha_formato}', fecha_str)
    resultado = resultado.replace('{fecha}', fecha_str)

    # Si {ext} no aparece en la plantilla, preservar la extension del archivo original
    if ext_sin_punto and not resultado.lower().endswith(f'.{ext_sin_punto}'):
        nombre_sin_ruta = resultado.rsplit('/', 1)[-1].rsplit('\\', 1)[-1]
        if '.' not in nombre_sin_ruta:
            resultado = f"{resultado}.{ext_sin_punto}"

    # Sanitizar caracteres prohibidos en sistemas de archivos
    resultado = re.sub(r'[<>:"/\\|?*]', '_', resultado)

    return resultado


def leer_metadatos_audio(archivo_path: Path) -> Dict[str, str]:
    """
    Lee etiquetas de metadatos de archivos de audio (MP3, FLAC, M4A, OGG) usando mutagen si esta disponible.
    """
    defaults = {
        'artista': 'artista_desconocido',
        'album': 'sin_album',
        'titulo': archivo_path.stem,
        'ano': 'desconocido',
        'genero': 'desconocido',
        'caratula': 'no'
    }

    if not MUTAGEN_DISPONIBLE:
        return defaults

    ext = archivo_path.suffix.lower()
    if ext not in ('.mp3', '.flac', '.m4a', '.mp4', '.ogg', '.opus', '.wma'):
        return defaults

    try:
        audio = mutagen.File(archivo_path)
        if audio is None:
            return defaults

        meta = dict(defaults)

        # Tratar ID3 (MP3) y Vorbis (FLAC/OGG) y MP4/M4A
        if hasattr(audio, 'tags') and audio.tags:
            tags = audio.tags

            # Artista
            for key in ('TPE1', 'artist', '\xa9ART', 'ARTIST'):
                if key in tags:
                    val = str(tags[key][0] if isinstance(tags[key], list) else tags[key])
                    if val.strip():
                        meta['artista'] = val.strip()
                        break

            # Album
            for key in ('TALB', 'album', '\xa9alb', 'ALBUM'):
                if key in tags:
                    val = str(tags[key][0] if isinstance(tags[key], list) else tags[key])
                    if val.strip():
                        meta['album'] = val.strip()
                        break

            # Titulo
            for key in ('TIT2', 'title', '\xa9nam', 'TITLE'):
                if key in tags:
                    val = str(tags[key][0] if isinstance(tags[key], list) else tags[key])
                    if val.strip():
                        meta['titulo'] = val.strip()
                        break

            # Anio / Fecha
            for key in ('TDRC', 'date', '\xa9day', 'DATE', 'TYER'):
                if key in tags:
                    val = str(tags[key][0] if isinstance(tags[key], list) else tags[key])
                    val_sub = val.strip()[:4]
                    if val_sub.isdigit():
                        meta['ano'] = val_sub
                        break

            # Genero
            for key in ('TCON', 'genre', '\xa9gen', 'GENRE'):
                if key in tags:
                    val = str(tags[key][0] if isinstance(tags[key], list) else tags[key])
                    if val.strip():
                        meta['genero'] = val.strip()
                        break

            # Caratula
            has_cover = False
            if hasattr(tags, 'getall'):
                if tags.getall('APIC'):
                    has_cover = True
            if not has_cover and hasattr(audio, 'pictures') and audio.pictures:
                has_cover = True
            if not has_cover and 'covr' in tags:
                has_cover = True

            meta['caratula'] = 'si' if has_cover else 'no'

        # Sanitizar valores para uso en nombres de archivo
        for k, v in meta.items():
            if k != 'caratula':
                meta[k] = re.sub(r'[<>:"/\\|?*]', '_', v)

        return meta
    except Exception:
        return defaults


def limpiar_metadatos_audio(archivo_path: Path) -> bool:
    """
    Elimina metadatos sensibles (comentarios, ubicaciones GPS, etc.) de un archivo de audio.
    """
    if not MUTAGEN_DISPONIBLE:
        return False
    try:
        audio = mutagen.File(archivo_path)
        if audio is not None:
            # Eliminar etiquetas sensibles o comentarios
            if hasattr(audio, 'tags') and audio.tags:
                keys_to_remove = [k for k in audio.tags.keys() if 'COMM' in str(k) or 'comment' in str(k).lower() or 'gps' in str(k).lower()]
                for k in keys_to_remove:
                    del audio.tags[k]
                audio.save()
            return True
    except Exception:
        pass
    return False


def limpiar_carpetas_vacias(
    carpeta_raiz: Union[str, Path],
    dry_run: bool = False
) -> List[Path]:
    """
    Elimina recursivamente las carpetas vacias dentro de carpeta_raiz (en orden bottom-up).
    La propia carpeta_raiz nunca se elimina.

    :param carpeta_raiz: Directorio raiz donde buscar carpetas vacias.
    :param dry_run: Si es True, solo lista las carpetas que se eliminarian sin borrar nada.
    :return: Lista de carpetas eliminadas (o que se eliminarian en dry_run).
    """
    raiz = Path(carpeta_raiz)
    if not raiz.exists() or not raiz.is_dir():
        return []

    eliminadas: List[Path] = []

    # Recorrer en orden bottom-up: las carpetas mas profundas primero
    todas_carpetas = sorted(
        [p for p in raiz.rglob('*') if p.is_dir() and p != raiz],
        key=lambda p: len(p.parts),
        reverse=True
    )

    for carpeta in todas_carpetas:
        try:
            contenido = list(carpeta.iterdir())
            if not contenido:
                eliminadas.append(carpeta)
                if not dry_run:
                    carpeta.rmdir()
        except Exception:
            pass

    return eliminadas


MESES_NOMBRES = {
    1: ("enero", "ene"), 2: ("febrero", "feb"), 3: ("marzo", "mar"),
    4: ("abril", "abr"), 5: ("mayo", "may"), 6: ("junio", "jun"),
    7: ("julio", "jul"), 8: ("agosto", "ago"), 9: ("septiembre", "sep"),
    10: ("octubre", "oct"), 11: ("noviembre", "nov"), 12: ("diciembre", "dic")
}


def _formatear_fecha_estructura(fecha: date, patron_formato: str) -> str:
    """
    Formatea un objeto date reemplazando los placeholders soportados en el patrón de formato.
    Placeholders soportados:
    - {YYYY}: Año a 4 dígitos
    - {MM}: Mes a 2 dígitos (01-12)
    - {DD}: Día a 2 dígitos (01-31)
    - {MES_NOMBRE}: Nombre completo del mes en español (ej. enero, febrero)
    - {MES_ABR}: Nombre abreviado del mes en español (ej. ene, feb)
    """
    if not patron_formato:
        return f"{fecha.year}/{fecha.month:02d}"

    res = patron_formato
    res = res.replace("{YYYY}", f"{fecha.year:04d}")
    res = res.replace("{MM}", f"{fecha.month:02d}")
    res = res.replace("{DD}", f"{fecha.day:02d}")

    if "{MES_NOMBRE}" in res or "{MES_ABR}" in res:
        nombre_completo, abreviado = MESES_NOMBRES.get(fecha.month, ("desconocido", "desc"))
        res = res.replace("{MES_NOMBRE}", nombre_completo)
        res = res.replace("{MES_ABR}", abreviado)

    # Si el patrón utilizaba la sintaxis YYYY/MM genérica sin llaves (ej. 'YYYY/MM')
    res = res.replace("YYYY", f"{fecha.year:04d}")
    res = res.replace("MM", f"{fecha.month:02d}")
    res = res.replace("DD", f"{fecha.day:02d}")

    return res


def _obtener_segmento_criterio(
    criterio: Optional[str],
    archivo_path: Path,
    fecha: Optional[date],
    estructura: Dict[str, Any]
) -> Optional[str]:
    """
    Calcula la subcarpeta resultante para un determinado criterio ('fecha', 'tipo', 'nombre', 'ninguno').
    """
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
        ext_sin_punto = archivo_path.suffix.lstrip(".").lower()
        if not ext_sin_punto:
            ext_sin_punto = "sin_extension"

        if org_tipo == 'categoria':
            return obtener_categoria(ext_sin_punto)
        else:
            return ext_sin_punto

    elif crit == 'nombre':
        org_nombre = estructura.get('organizacion_nombre', 'primera_letra').lower()
        stem = archivo_path.stem
        if not stem:
            return "sin_nombre"

        if org_nombre == 'primera_letra':
            primera = stem[0].upper()
            return primera if primera.isalnum() else "_"
        else:
            return stem

    return None


def generar_ruta_destino(
    archivo_path: Path,
    fecha: Optional[date],
    carpeta_raiz_destino: Union[str, Path],
    estructura: Optional[Dict[str, Any]] = None
) -> Path:
    """
    Construye la ruta de destino deseada para un archivo basada en su fecha u otros criterios organizativos.

    :param archivo_path: Objeto Path del archivo original.
    :param fecha: Fecha calculada (date) o None si no se determino.
    :param carpeta_raiz_destino: Directorio raiz de destino (str o Path).
    :param estructura: Diccionario opcional con parametros de criterios de organizacion.
    :return: Objeto Path con la ruta de destino completa.
    """
    raiz = Path(carpeta_raiz_destino)

    # Si no se proporciona estructura, usar comportamiento por defecto (fecha YYYY/MM)
    if not estructura:
        if fecha is None:
            return raiz / "sin_fecha" / archivo_path.name
        return raiz / str(fecha.year) / f"{fecha.month:02d}" / archivo_path.name

    criterio_p = estructura.get('criterio_primario')
    criterio_s = estructura.get('criterio_secundario')

    # Si ninguno está especificado, se usa el modo legacy por defecto
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
    """
    Funcion auxiliar para generar una ruta unica añadiendo un sufijo (1), (2), etc.
    si la ruta especificada ya existe en disco o en el conjunto de nombres reservados.

    :param ruta_base: Ruta destino proyectada inicial.
    :param nombres_reservados: Conjunto de objetos Path ya asignados en el plan actual.
    :return: Nueva ruta Path garantizada de no estar en uso.
    """
    stem = ruta_base.stem
    suffix = ruta_base.suffix
    parent = ruta_base.parent

    contador = 1
    nueva_ruta = ruta_base

    while nueva_ruta.exists() or nueva_ruta in nombres_reservados:
        nueva_ruta = parent / f"{stem} ({contador}){suffix}"
        contador += 1

    return nueva_ruta


def detectar_duplicados_por_nombre(
    planes: List[Dict[str, Any]],
    carpeta_raiz_destino: Union[str, Path]
) -> List[Dict[str, Any]]:
    """
    Identifica planes que apuntan a una misma ruta destino. A partir del segundo
    archivo conflictivo, se reasigna su accion a 'duplicado' y su destino a 'Duplicadas/'.

    :param planes: Lista de diccionarios representando los planes de movimiento.
    :param carpeta_raiz_destino: Ruta raiz de destino para ubicar la carpeta 'Duplicadas'.
    :return: Lista de planes actualizada.
    """
    raiz = Path(carpeta_raiz_destino)
    carpeta_duplicadas = raiz / "Duplicadas"

    # Agrupar planes por la ruta de destino asignada
    destinos_map: Dict[Path, List[Dict[str, Any]]] = {}
    for plan in planes:
        dest = plan['destino']
        if dest not in destinos_map:
            destinos_map[dest] = []
        destinos_map[dest].append(plan)

    # Conjunto para rastrear destinos reservados dentro del plan
    nombres_reservados = set()

    for dest, lista_planes in destinos_map.items():
        if len(lista_planes) == 1:
            # Sin conflicto
            nombres_reservados.add(dest)
        else:
            # El primero se conserva en su destino proyectado
            primer_plan = lista_planes[0]
            nombres_reservados.add(primer_plan['destino'])

            # Los subsecuentes se marcan como duplicados y se mueven a 'Duplicadas'
            for plan_dup in lista_planes[1:]:
                plan_dup['accion'] = 'duplicado'
                destino_dup_base = carpeta_duplicadas / plan_dup['origen'].name
                nuevo_destino = generar_nombre_unico(destino_dup_base, nombres_reservados)
                plan_dup['destino'] = nuevo_destino
                nombres_reservados.add(nuevo_destino)

    return planes


def _calcular_hash_md5(archivo_path: Path, bloque_tam: int = 8192) -> Optional[str]:
    """
    Calcula el hash MD5 de un archivo leyendo en bloques pequeños para alta eficiencia.
    """
    hasher = hashlib.md5()
    try:
        with open(archivo_path, 'rb') as f:
            while chunk := f.read(bloque_tam):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return None


def detectar_duplicados_por_hash(
    planes: List[Dict[str, Any]],
    carpeta_raiz_destino: Union[str, Path],
    usar_hash: bool = True
) -> List[Dict[str, Any]]:
    """
    Identifica duplicados mediante comparacion de contenido binario (MD5).
    Los archivos identicos (excepto el primero) se marcan como 'duplicado'
    y se re-dirigen a la carpeta 'Duplicadas/'.

    :param planes: Lista de diccionarios de plan.
    :param carpeta_raiz_destino: Ruta raiz para ubicar la carpeta 'Duplicadas'.
    :param usar_hash: Si es False, retorna los planes sin modificaciones.
    :return: Lista de planes actualizada.
    """
    if not usar_hash:
        return planes

    raiz = Path(carpeta_raiz_destino)
    carpeta_duplicadas = raiz / "Duplicadas"

    # Conjunto para rastrear todos los destinos reservados en el plan
    nombres_reservados = {p['destino'] for p in planes}

    # Agrupar por hash MD5 solo aquellos planes que aun no han sido marcados como duplicados por nombre
    hashes_map: Dict[str, List[Dict[str, Any]]] = {}

    for plan in planes:
        if plan['accion'] == 'duplicado':
            continue

        h_val = _calcular_hash_md5(plan['origen'])
        if h_val:
            if h_val not in hashes_map:
                hashes_map[h_val] = []
            hashes_map[h_val].append(plan)

    for h_val, lista_planes in hashes_map.items():
        if len(lista_planes) > 1:
            # El primer archivo del grupo con el mismo contenido se conserva en su lugar
            # Los siguientes se redirigen a la carpeta de duplicadas
            for plan_dup in lista_planes[1:]:
                # Liberamos su destino anterior del conjunto reservado
                nombres_reservados.discard(plan_dup['destino'])
                
                plan_dup['accion'] = 'duplicado'
                destino_dup_base = carpeta_duplicadas / plan_dup['origen'].name
                nuevo_destino = generar_nombre_unico(destino_dup_base, nombres_reservados)
                plan_dup['destino'] = nuevo_destino
                nombres_reservados.add(nuevo_destino)

    return planes





def simular_plan(planes: List[Dict[str, Any]]) -> str:
    """
    Genera una representacion textual legible y tabulada del plan de operaciones
    para previsualizar las acciones antes de ejecutarlas.

    :param planes: Lista de diccionarios con claves 'origen', 'destino', 'fecha', 'accion'.
    :return: String multilinea formateado con el resumen del plan.
    """
    if not planes:
        return "No hay operaciones planificadas."

    lineas: List[str] = []
    
    # Contadores estadisticos
    total_mover = sum(1 for p in planes if p['accion'] == 'mover')
    total_duplicados = sum(1 for p in planes if p['accion'] == 'duplicado')

    lineas.append("=" * 80)
    lineas.append("RESUMEN DE LA SIMULACION DEL PLAN")
    lineas.append(f"Total de archivos a procesar: {len(planes)} (A mover: {total_mover} | Duplicados: {total_duplicados})")
    lineas.append("=" * 80)
    lineas.append(f"{'ACCION':<12} | {'FECHA':<10} | {'ORIGEN':<30} -> {'DESTINO'}")
    lineas.append("-" * 80)

    for p in planes:
        accion = p['accion'].upper()
        fecha_str = str(p['fecha']) if p['fecha'] else "SIN FECHA"
        origen_nombre = p['origen'].name
        destino_rel = str(p['destino'])

        lineas.append(f"{accion:<12} | {fecha_str:<10} | {origen_nombre:<30} -> {destino_rel}")

    lineas.append("=" * 80)

    return "\n".join(lineas)


def ejecutar_plan_con_modo(
    planes: List[Dict[str, Any]],
    modo: str = "Copiar",
    callback_progreso: Optional[Callable[[int, int, str], None]] = None,
    cancelar_flag: Optional[Callable[[], bool]] = None,
) -> str:
    """
    Ejecuta el plan de operaciones moviendo o copiando los archivos segun el modo especificado.

    :param planes: Lista de diccionarios representando los planes.
    :param modo: 'Copiar' para usar shutil.copy2 o 'Mover' para usar shutil.move.
    :param callback_progreso: Funcion opcional llamada en cada archivo con (indice, total, nombre).
    :param cancelar_flag: Funcion opcional que retorna True si se debe cancelar la operacion.
    :return: String con el informe del procesamiento.
    """
    if not planes:
        return "No hay planes para ejecutar."

    exitos = 0
    errores = 0
    logs: List[str] = []

    modo_norm = modo.strip().capitalize()
    es_copia = modo_norm == "Copiar"
    verbo_log = "COPIAR" if es_copia else "MOVER"

    logs.append("=" * 80)
    logs.append(f"INICIO DE EJECUCION EN MODO [{verbo_log}]")
    logs.append("=" * 80)

    # Conjunto de destinos reservados para resolucion de colisiones en tiempo de ejecucion
    nombres_reservados: set = {p['destino'] for p in planes}

    for i, plan in enumerate(planes, start=1):
        # Verificar cancelacion antes de cada archivo
        if cancelar_flag and cancelar_flag():
            logs.append(f"[{i}/{len(planes)}] OPERACION CANCELADA POR EL USUARIO.")
            break

        origen: Path = plan['origen']
        destino: Path = plan['destino']
        accion: str = plan['accion'].lower()

        if callback_progreso:
            callback_progreso(i, len(planes), origen.name)

        if accion not in ('mover', 'duplicado'):
            logs.append(f"[{i}/{len(planes)}] IGNORADO: Accion '{accion}' no reconocida para '{origen.name}'")
            continue

        try:
            if not origen.exists():
                raise FileNotFoundError(f"El archivo origen '{origen}' no existe.")

            destino.parent.mkdir(parents=True, exist_ok=True)

            # Verificar colision de nombre y aplicar sufijo incremental si es necesario
            destino_final = destino
            if destino_final.exists() or destino_final in nombres_reservados:
                nombres_reservados.discard(destino_final)
                destino_final = generar_nombre_unico(destino, nombres_reservados)
                nombres_reservados.add(destino_final)

            if es_copia:
                shutil.copy2(str(origen), str(destino_final))
            else:
                shutil.move(str(origen), str(destino_final))

            # Registrar operacion en el sistema Undo (JSON Lines)
            registrar_operacion_undo([{
                'timestamp': datetime.now().isoformat(),
                'modo': modo_norm,
                'origen': str(origen),
                'destino': str(destino_final),
                'nombre_original': origen.name,
                'nombre_final': destino_final.name
            }])

            exitos += 1
            logs.append(f"[{i}/{len(planes)}] OK [{verbo_log}]: '{origen.name}' -> '{destino_final}'")

        except Exception as e:
            errores += 1
            logs.append(f"[{i}/{len(planes)}] ERROR al procesar '{origen.name}': {e}")

    logs.append("=" * 80)
    logs.append(f"INFORME FINAL: Operaciones exitosas: {exitos} | Errores: {errores}")
    logs.append("=" * 80)

    return "\n".join(logs)


# ==============================================================================
# FUNCIONALIDADES AVANZADAS (ANÁLISIS DE DESTINO, UNDO, RESPALDO, DISPOSITIVOS)
# ==============================================================================

def analizar_estructura_destino(destino_base: Union[str, Path]) -> Dict[str, Any]:
    """
    Analiza un directorio de destino existente para detectar patrones organizativos comunes.
    """
    path_dest = Path(destino_base)
    resultado: Dict[str, Any] = {
        'existe': path_dest.exists() and path_dest.is_dir(),
        'tipo': 'desconocido',
        'ejemplo': '',
        'carpetas': [],
        'estructura_sugerida': {}
    }

    if not resultado['existe']:
        return resultado

    carpetas_nivel1 = [p for p in path_dest.iterdir() if p.is_dir()]
    resultado['carpetas'] = [c.name for c in carpetas_nivel1[:10]]

    if not carpetas_nivel1:
        resultado['tipo'] = 'vacio'
        return resultado

    nombres1 = [c.name for c in carpetas_nivel1]

    # Detectar patron YYYY (cuatro digitos)
    anios = [n for n in nombres1 if re.match(r'^(19|20)\d{2}$', n)]
    if len(anios) >= 1:
        resultado['tipo'] = 'fecha'
        resultado['ejemplo'] = f"{anios[0]}/"
        # Verificar nivel 2
        sub_c = list((path_dest / anios[0]).iterdir())
        sub_dirs = [s.name for s in sub_c if s.is_dir()]
        if sub_dirs:
            resultado['ejemplo'] = f"{anios[0]}/{sub_dirs[0]}/"
        resultado['estructura_sugerida'] = {
            'criterio_primario': 'fecha',
            'criterio_secundario': 'ninguno',
            'formato_fecha': '{YYYY}/{MM}' if sub_dirs else '{YYYY}'
        }
        return resultado

    # Detectar patron extension / categoria (ej: jpg, pdf, Imagenes, Documentos)
    exts_comunes = {'jpg', 'jpeg', 'png', 'pdf', 'mp3', 'mp4', 'txt', 'zip', 'doc', 'docx', 'imagenes', 'documentos', 'audio', 'videos'}
    coincidencias_ext = [n for n in nombres1 if n.lower() in exts_comunes]
    if len(coincidencias_ext) >= 1:
        resultado['tipo'] = 'tipo'
        resultado['ejemplo'] = f"{coincidencias_ext[0]}/"
        resultado['estructura_sugerida'] = {
            'criterio_primario': 'tipo',
            'criterio_secundario': 'ninguno',
            'organizacion_tipo': 'categoria' if any(n.lower() in ('imagenes', 'documentos') for n in nombres1) else 'extension'
        }
        return resultado

    # Detectar patron letras A-Z
    letras = [n for n in nombres1 if len(n) == 1 and n.isalpha()]
    if len(letras) >= 2:
        resultado['tipo'] = 'nombre'
        resultado['ejemplo'] = f"{letras[0]}/"
        resultado['estructura_sugerida'] = {
            'criterio_primario': 'nombre',
            'criterio_secundario': 'ninguno',
            'organizacion_nombre': 'primera_letra'
        }
        return resultado

    resultado['tipo'] = 'mixto'
    resultado['ejemplo'] = f"{carpetas_nivel1[0].name}/"
    return resultado


def guardar_estructura_como_perfil(estructura: Dict[str, Any], nombre_perfil: str) -> bool:
    """
    Guarda la estructura dada como un nuevo perfil en ~/.organizador_perfiles.json.
    """
    perfiles_path = Path.home() / ".organizador_perfiles.json"
    perfiles = []
    if perfiles_path.exists():
        try:
            with open(perfiles_path, 'r', encoding='utf-8') as f:
                perfiles = json.load(f)
        except Exception:
            perfiles = []

    nuevo_perfil = {
        'nombre': nombre_perfil,
        'origen': '',
        'destino': '',
        'modo': 'Copiar',
        'filtros': {'todos': True},
        'estructura': estructura
    }

    # Reemplazar perfil si ya existe con el mismo nombre
    perfiles = [p for p in perfiles if p.get('nombre') != nombre_perfil]
    perfiles.append(nuevo_perfil)

    try:
        with open(perfiles_path, 'w', encoding='utf-8') as f:
            json.dump(perfiles, f, indent=4, ensure_ascii=False)
        return True
    except Exception:
        return False


def registrar_operacion_undo(operaciones: List[Dict[str, Any]], log_file_path: Optional[Path] = None):
    """
    Anade una o mas operaciones al archivo undo en formato JSON Lines (~/.organizador_undo.jsonl).
    """
    path = log_file_path or (Path.home() / ".organizador_undo.jsonl")
    try:
        with open(path, 'a', encoding='utf-8') as f:
            for op in operaciones:
                f.write(json.dumps(op, ensure_ascii=False) + '\n')
    except Exception:
        pass


def obtener_historial_undo(limite: int = 100, log_file_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """
    Obtiene las ultimas N operaciones del archivo undo JSON Lines.
    """
    path = log_file_path or (Path.home() / ".organizador_undo.jsonl")
    if not path.exists():
        return []

    operaciones = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line_str = line.strip()
                if line_str:
                    try:
                        operaciones.append(json.loads(line_str))
                    except Exception:
                        pass
    except Exception:
        return []

    return operaciones[-limite:]


def deshacer_n_operaciones(n: int = 1, dry_run: bool = False, log_file_path: Optional[Path] = None) -> Tuple[int, int, List[str]]:
    """
    Revierte las ultimas N operaciones registradas en el historial undo.

    :return: Tupla (exitos, errores, logs)
    """
    path = log_file_path or (Path.home() / ".organizador_undo.jsonl")
    if not path.exists():
        return (0, 0, ["No existe historial de operaciones para deshacer."])

    historial = obtener_historial_undo(limite=999999, log_file_path=path)
    if not historial:
        return (0, 0, ["El historial undo esta vacio."])

    a_revertir = historial[-n:]
    restantes = historial[:-n]

    exitos = 0
    errores = 0
    logs = []

    logs.append(f"--- INICIO UNDO ({'DRY-RUN' if dry_run else 'EJECUCION REAL'}) DE {len(a_revertir)} OPERACIONES ---")

    for i, op in enumerate(reversed(a_revertir), start=1):
        modo = op.get('modo', 'Mover').capitalize()
        origen = Path(op['origen'])
        destino = Path(op['destino'])

        if dry_run:
            if modo == 'Mover':
                logs.append(f"[SIMULACION {i}] Se moveria '{destino}' de vuelta a '{origen}'")
            else:
                logs.append(f"[SIMULACION {i}] Se eliminaria la copia en '{destino}'")
            exitos += 1
            continue

        try:
            if modo == 'Mover':
                if not destino.exists():
                    logs.append(f"[{i}] ERROR: El archivo destino '{destino}' no existe.")
                    errores += 1
                    continue
                origen.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(destino), str(origen))
                logs.append(f"[{i}] REVERTIDO [MOVER]: '{destino.name}' devuelto a '{origen}'")
            else:  # Copiar
                if destino.exists():
                    destino.unlink()
                    logs.append(f"[{i}] REVERTIDO [COPIAR]: Copia eliminada en '{destino}'")
                else:
                    logs.append(f"[{i}] ADVERTENCIA: La copia en '{destino}' ya no existia.")
            exitos += 1
        except Exception as e:
            errores += 1
            logs.append(f"[{i}] ERROR al deshacer '{destino.name}': {e}")

    # Si no es dry_run, actualizar el archivo JSON Lines con los registros restantes
    if not dry_run:
        try:
            with open(path, 'w', encoding='utf-8') as f:
                for op in restantes:
                    f.write(json.dumps(op, ensure_ascii=False) + '\n')
        except Exception:
            pass

    return (exitos, errores, logs)


def clonar_carpeta(
    origen: Union[str, Path],
    destino: Union[str, Path],
    incremental: bool = False,
    callback_progreso: Optional[Callable[[int, int, str, int, int], None]] = None,
    cancelar_flag: Optional[Callable[[], bool]] = None
) -> str:
    """
    Clona recursivamente una carpeta de origen a destino preservando tiempos y atributos.
    Soporta modo incremental (solo copia archivos nuevos o modificados).
    """
    p_orig = Path(origen)
    p_dest = Path(destino)

    if not p_orig.exists() or not p_orig.is_dir():
        raise RutaNoValidaError(f"La ruta de origen '{origen}' no es valida.")

    archivos = [p for p in p_orig.rglob('*') if p.is_file()]
    total = len(archivos)

    bytes_totales = sum(p.stat().st_size for p in archivos)
    bytes_copiados = 0

    exitos = 0
    omitidos = 0
    errores = 0

    for i, arch in enumerate(archivos, start=1):
        if cancelar_flag and cancelar_flag():
            return f"Clonacion cancelada por el usuario ({i-1}/{total} procesados)."

        try:
            st_o = arch.stat()
            file_size = st_o.st_size

            if callback_progreso:
                callback_progreso(i, total, arch.name, bytes_copiados, bytes_totales)

            rel = arch.relative_to(p_orig)
            dest_arch = p_dest / rel
            dest_arch.parent.mkdir(parents=True, exist_ok=True)

            if incremental and dest_arch.exists():
                st_d = dest_arch.stat()
                if st_o.st_size == st_d.st_size and abs(st_o.st_mtime - st_d.st_mtime) < 1.0:
                    omitidos += 1
                    bytes_copiados += file_size
                    if callback_progreso:
                        callback_progreso(i, total, arch.name, bytes_copiados, bytes_totales)
                    continue

            # Copy in chunks to report progress
            with open(arch, 'rb') as fsrc, open(dest_arch, 'wb') as fdst:
                while True:
                    if cancelar_flag and cancelar_flag():
                        # Eliminar el archivo parcialmente copiado
                        fdst.close()
                        dest_arch.unlink(missing_ok=True)
                        return f"Clonacion cancelada por el usuario ({i-1}/{total} procesados)."

                    buf = fsrc.read(1024 * 1024) # 1 MB chunks
                    if not buf:
                        break
                    fdst.write(buf)
                    bytes_copiados += len(buf)
                    if callback_progreso:
                        callback_progreso(i, total, arch.name, bytes_copiados, bytes_totales)

            shutil.copystat(str(arch), str(dest_arch))
            exitos += 1
        except Exception:
            errores += 1

    return f"Clonacion finalizada. Copiados: {exitos} | Incremental omitidos: {omitidos} | Errores: {errores}"


def clonar_disco(
    disco_origen: str,
    disco_destino: str,
    usar_ddrescue: bool = False,
    verificar_checksum: bool = False,
    callback_progreso: Optional[Callable[[str], None]] = None
) -> str:
    """
    Ejecuta dd o ddrescue para clonar un dispositivo/disco completo a nivel de bloque (requiere root/sudo).
    """
    cmd_name = "ddrescue" if usar_ddrescue else "dd"
    cmd_path = shutil.which(cmd_name)
    if not cmd_path:
        return f"Error: La herramienta '{cmd_name}' no esta instalada en el sistema."

    if usar_ddrescue:
        cmd = [cmd_path, "-f", "-d", disco_origen, disco_destino, "/tmp/ddrescue.map"]
    else:
        cmd = [cmd_path, f"if={disco_origen}", f"of={disco_destino}", "bs=4M", "status=progress", "conv=fsync"]

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        while True:
            line = proc.stderr.readline() if not usar_ddrescue else proc.stdout.readline()
            if not line and proc.poll() is not None:
                break
            if line and callback_progreso:
                callback_progreso(line.strip())

        rc = proc.wait()
        if rc != 0:
            return f"Error en la clonacion con {cmd_name} (codigo de salida {rc})."

        res_msg = f"Clonacion de disco '{disco_origen}' -> '{disco_destino}' completada con exito."

        # Verificacion checksum opcional
        if verificar_checksum:
            callback_progreso("Calculando checksum MD5 de verificacion...") if callback_progreso else None
            # Para bloques de disco, verificar primer 100MB
            h1 = _calcular_md5_parcial(Path(disco_origen))
            h2 = _calcular_md5_parcial(Path(disco_destino))
            if h1 == h2:
                res_msg += " Verificacion Checksum MD5: OK."
            else:
                res_msg += f" WARNING: Checksum mismatch ({h1} != {h2})."

        return res_msg
    except Exception as e:
        return f"Error durante ejecucion de {cmd_name}: {e}"


def _calcular_md5_parcial(path_obj: Path, max_bytes: int = 100 * 1024 * 1024) -> str:
    md5 = hashlib.md5()
    try:
        with open(path_obj, 'rb') as f:
            leido = 0
            while leido < max_bytes:
                chunk = f.read(min(65536, max_bytes - leido))
                if not chunk:
                    break
                md5.update(chunk)
                leido += len(chunk)
    except Exception:
        return "error"
    return md5.hexdigest()


def detectar_carpetas_usuario() -> List[Dict[str, str]]:
    """
    Detecta carpetas de usuario comunes en Linux (~/Documentos, ~/Imágenes, etc.).
    """
    home = Path.home()
    carpetas_std = [
        ("Documentos", home / "Documentos"),
        ("Imágenes", home / "Imágenes"),
        ("Música", home / "Música"),
        ("Descargas", home / "Descargas"),
        ("Vídeos", home / "Vídeos"),
        ("Escritorio", home / "Escritorio"),
        ("Documents", home / "Documents"),
        ("Pictures", home / "Pictures"),
        ("Music", home / "Music"),
        ("Downloads", home / "Downloads"),
    ]

    existentes = []
    for nombre, path in carpetas_std:
        if path.exists() and path.is_dir():
            existentes.append({'nombre': nombre, 'ruta': str(path)})
    return existentes


def detectar_dispositivos_multimedia() -> List[Dict[str, str]]:
    """
    Escanea el sistema buscando dispositivos de medios montados (camaras, celulares MTP/PTP, pendrives en /media/ o /run/media/).
    """
    dispositivos = []
    usuario = os.environ.get('USER', '')

    rutas_montaje = [
        Path("/media"),
        Path(f"/media/{usuario}"),
        Path(f"/run/media/{usuario}"),
        Path(f"/run/user/{os.getuid()}/gvfs") if hasattr(os, 'getuid') else None
    ]

    for r in rutas_montaje:
        if r and r.exists() and r.is_dir():
            try:
                for item in r.iterdir():
                    if item.is_dir():
                        tipo = "Punto de Montaje / USB"
                        if "mtp" in item.name.lower() or "gphoto2" in item.name.lower():
                            tipo = "Teléfono Android / Cámara MTP"

                        espacio_str = "Desconocido"
                        try:
                            st = shutil.disk_usage(item)
                            libre_gb = st.free / (1024 ** 3)
                            espacio_str = f"{libre_gb:.1f} GB libres"
                        except Exception:
                            pass

                        dispositivos.append({
                            'etiqueta': item.name,
                            'ruta': str(item),
                            'tipo': tipo,
                            'espacio': espacio_str
                        })
            except Exception:
                pass

    return dispositivos



