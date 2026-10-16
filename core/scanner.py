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
from typing import Iterator, List, Optional, Set, Tuple

from logger import app_logger


@dataclass(frozen=True, slots=True)
class FileEntry:
    path: Path
    size: int
    mtime_ns: int
    ctime: float = 0.0


def iterar_archivos(
    ruta_origen,
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
    Generador puro. Un solo recorrido. Sin listas intermedias.
    `excluir_directorios` permite podar subárboles completos (node_modules, .cache, AppData).
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
