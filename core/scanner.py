"""
core/scanner.py - Escaneo en streaming de alto rendimiento para Memexicanisimos Files.

- Generador puro (Iterator[FileEntry]). Nunca materializa listas en memoria.
- Escala a millones de archivos manteniendo memoria constante O(profundidad del árbol).
- DFS iterativo con pila explícita en lugar de recursión para evitar límites de pila.
- Poda de árboles prematura: omite directorios excluidos (node_modules, .cache, etc.)
  sin descender en sus subárboles.
"""

import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterator, List, Optional, Set, Tuple, Union

from logger import app_logger


@dataclass(frozen=True, slots=True)
class FileEntry:
    """
    Represents a file discovered during scanning with its essential metadata.

    Attributes:
        path (Path): The absolute or relative path to the file.
        size (int): The size of the file in bytes.
        mtime_ns (int): The modification time of the file in nanoseconds since the epoch.
        ctime (float): The creation time (or metadata change time on Unix) of the file in seconds since the epoch. Defaults to 0.0.
    """
    path: Path
    size: int
    mtime_ns: int
    ctime: float = 0.0


def iterar_archivos(
    ruta_origen: Union[str, Path],
    extensiones_permitidas: Optional[List[str]] = None,
    incluir_subcarpetas: bool = True,
    tamano_min_bytes: Optional[int] = None,
    tamano_max_bytes: Optional[int] = None,
    dias_antiguedad: Optional[int] = None,
    usar_creacion: bool = False,
    incluir_ocultos: bool = False,
    patron_regex: Optional[str] = None,
    excluir_directorios: Optional[Set[str]] = None,
    excluir_ocultos_dir: bool = False,
) -> Iterator[FileEntry]:
    """
    Yields files from a directory tree matching the specified criteria.

    This function acts as a pure generator, avoiding intermediate lists in memory.
    It performs an iterative Depth-First Search (DFS) and implements early tree pruning
    by skipping excluded directories (e.g., node_modules, .cache) without descending into them.

    Args:
        ruta_origen (Union[str, Path]): The starting directory path for the scan.
        extensiones_permitidas (Optional[List[str]]): A list of allowed file extensions (e.g., ['.txt', 'pdf']). Defaults to None.
        incluir_subcarpetas (bool): If True, recursively scans subdirectories. Defaults to True.
        tamano_min_bytes (Optional[int]): Minimum file size in bytes to include. Defaults to None.
        tamano_max_bytes (Optional[int]): Maximum file size in bytes to include. Defaults to None.
        dias_antiguedad (Optional[int]): Only include files modified/created in the last `dias_antiguedad` days. Defaults to None.
        usar_creacion (bool): If True, uses creation time for `dias_antiguedad` check; otherwise uses modification time. Defaults to False.
        incluir_ocultos (bool): If True, includes files starting with a dot. Defaults to False.
        patron_regex (Optional[str]): A regular expression pattern that the file name must match. Defaults to None.
        excluir_directorios (Optional[Set[str]]): A set of directory names to skip completely. Defaults to None.
        excluir_ocultos_dir (bool): If True, skips directories starting with a dot. Defaults to False.

    Yields:
        Iterator[FileEntry]: An iterator of FileEntry objects for each matching file.
    """
    origen_path = Path(ruta_origen)
    if not origen_path.is_dir():
        return

    exts_norm: Optional[Set[str]] = None
    if extensiones_permitidas:
        exts_norm = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in extensiones_permitidas}

    regex_compilado = None
    if patron_regex:
        try:
            regex_compilado = re.compile(patron_regex)
        except re.error as err:
            app_logger.error(f"Regex inválido: {err}")
            return

    fecha_limite = None
    if dias_antiguedad and dias_antiguedad > 0:
        fecha_limite = datetime.now() - timedelta(days=dias_antiguedad)

    excluir = excluir_directorios or set()

    # DFS iterativo con pila explícita
    stack: List[Path] = [origen_path]
    while stack:
        actual = stack.pop()
        try:
            with os.scandir(actual) as it:
                for entry in it:
                    try:
                        # Directorios: decidir si descender
                        if entry.is_dir(follow_symlinks=False):
                            if not incluir_subcarpetas:
                                continue
                            nombre_dir = entry.name
                            if nombre_dir in excluir:
                                continue
                            if excluir_ocultos_dir and nombre_dir.startswith('.'):
                                continue
                            stack.append(Path(entry.path))
                            continue

                        if not entry.is_file(follow_symlinks=False):
                            continue

                        nombre = entry.name
                        if not incluir_ocultos and nombre.startswith('.'):
                            continue

                        if exts_norm is not None:
                            ext = os.path.splitext(nombre)[1].lower()
                            if ext not in exts_norm:
                                continue

                        if regex_compilado and not regex_compilado.search(nombre):
                            continue

                        # stat cacheado por getdents en Linux
                        st = entry.stat(follow_symlinks=False)

                        if tamano_min_bytes is not None and st.st_size < tamano_min_bytes:
                            continue
                        if tamano_max_bytes is not None and st.st_size > tamano_max_bytes:
                            continue
                        if fecha_limite is not None:
                            ts = st.st_ctime if usar_creacion else st.st_mtime
                            if datetime.fromtimestamp(ts) < fecha_limite:
                                continue

                        yield FileEntry(
                            path=Path(entry.path),
                            size=st.st_size,
                            mtime_ns=st.st_mtime_ns,
                            ctime=st.st_ctime,
                        )
                    except (PermissionError, OSError) as e:
                        app_logger.warning(f"Omitiendo entrada inaccesible '{entry.path}': {e}")
        except (PermissionError, OSError) as e:
            app_logger.warning(f"Omitiendo directorio inaccesible '{actual}': {e}")


def iterar_directorios(
    ruta_origen,
    excluir_directorios: Optional[Set[str]] = None,
    excluir_ocultos_dir: bool = False,
) -> Iterator[Path]:
    """
    Generador puro que recorre y cede todos los directorios (incluyendo vacíos).
    DFS iterativo con poda de directorios excluidos.
    """
    origen_path = Path(ruta_origen)
    if not origen_path.is_dir():
        return

    excluir = excluir_directorios or set()
    stack: List[Path] = [origen_path]

    while stack:
        actual = stack.pop()
        try:
            with os.scandir(actual) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            nombre_dir = entry.name
                            if nombre_dir in excluir:
                                continue
                            if excluir_ocultos_dir and nombre_dir.startswith('.'):
                                continue
                            p = Path(entry.path)
                            yield p
                            stack.append(p)
                    except (PermissionError, OSError) as e:
                        app_logger.warning(f"Omitiendo directorio inaccesible '{entry.path}': {e}")
        except (PermissionError, OSError) as e:
            app_logger.warning(f"Omitiendo directorio inaccesible '{actual}': {e}")


def contar_archivos_y_bytes(
    ruta_origen,
    **kwargs,
) -> Tuple[int, int]:
    """
    Pre-pase liviano con memoria cero.
    Devuelve (num_archivos, bytes_totales).
    """
    n = 0
    b = 0
    for entry in iterar_archivos(ruta_origen, **kwargs):
        n += 1
        b += entry.size
    return n, b
