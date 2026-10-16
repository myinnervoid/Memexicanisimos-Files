"""
core/versioning.py - Resolución de conflictos mediante archivo histórico de versiones.

Evita la sobrescritura ciega de archivos modificados:
- Si el archivo origen y destino son idénticos en tamaño y timestamp/contenido, retorna None (omitir).
- Si el archivo destino existe y tiene contenido distinto, lo traslada de forma segura a
  una subcarpeta .historial/ con marca de tiempo ISO (YYYYMMDD_HHMMSS), dejando libre la ruta original.
"""

import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional


def _archivos_identicos(p1: Path, p2: Path) -> bool:
    """Compara byte a byte en bloques de 64 KB de forma rápida."""
    try:
        with open(p1, "rb") as f1, open(p2, "rb") as f2:
            while True:
                b1 = f1.read(65536)
                b2 = f2.read(65536)
                if b1 != b2:
                    return False
                if not b1:
                    return True
    except OSError:
        return False


def resolver_conflicto_versionado(
    origen: Path,
    destino: Path,
    dir_historial_nombre: str = ".historial"
) -> Optional[Path]:
    """
    Evalúa colisión de archivos.
    - Retorna None si los archivos son idénticos (no requiere acción, omitir).
    - Mueve la versión preexistente a .historial/ y retorna destino (para recibir el nuevo archivo).
    """
    origen = Path(origen)
    destino = Path(destino)

    if not destino.exists():
        return destino

    try:
        st_orig = origen.stat()
        st_dest = destino.stat()

        # Si el tamaño coincide, verificar si el contenido es idéntico
        if st_orig.st_size == st_dest.st_size:
            if _archivos_identicos(origen, destino):
                return None  # Archivos idénticos: no requiere copiar ni versionar

    except OSError:
        pass

    # El archivo destino difiere del nuevo: archivar la versión previa en .historial
    dir_historial = destino.parent / dir_historial_nombre
    dir_historial.mkdir(parents=True, exist_ok=True)

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre_archivado = f"{timestamp_str}_{destino.name}"
    destino_archivado = dir_historial / nombre_archivado

    # Si ya existiera ese nombre por un batch del mismo segundo, agregar contador
    contador = 1
    while destino_archivado.exists():
        destino_archivado = dir_historial / f"{timestamp_str}_{contador}_{destino.name}"
        contador += 1

    try:
        os.replace(str(destino), str(destino_archivado))
    except OSError:
        shutil.move(str(destino), str(destino_archivado))

    # Rotación automática: conservar solo las últimas N versiones
    try:
        from config import AppConfig
        max_versiones = getattr(AppConfig, "MAX_VERSIONES_HISTORIAL", 5)
        patron = f"*_{destino.name}"
        versiones = sorted(dir_historial.glob(patron))
        if len(versiones) > max_versiones:
            for sobrante in versiones[:-max_versiones]:
                try:
                    sobrante.unlink(missing_ok=True)
                except OSError:
                    pass
    except Exception:
        pass

    return destino
