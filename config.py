"""
Modulo config.py - Centralización de Configuración y Constantes Globales.

Proporciona el objeto AppConfig y exporta el diccionario unificado CATEGORIAS_EXT
para garantizar sincronización absoluta entre Backend y Frontend.
"""

import os
from pathlib import Path
from typing import Dict, List


class AppConfig:
    """Rutas y parámetros de configuración centralizados del sistema."""
    APP_NAME = "Memexicanisimos Files"
    APP_VERSION = "1.0"

    # Directorio de usuario e historial
    HOME_DIR = Path.home()
    CONFIG_FILE = HOME_DIR / ".organizador_config.json"
    PERFILES_FILE = HOME_DIR / ".organizador_perfiles.json"
    UNDO_FILE = HOME_DIR / ".organizador_undo.jsonl"

    # Timeouts y buffer
    BUFFER_SIZE = 8192  # 8 KB para cálculo MD5
    MAX_UNDO_HISTORY = 100


# Diccionario Unificado de Categorías de Extensiones (ÚNICA FUENTE DE VERDAD)
CATEGORIAS_EXT: Dict[str, List[str]] = {
    "Documentos": ["pdf", "docx", "txt", "xlsx", "pptx", "odt", "csv", "md"],
    "Imagen": ["jpg", "jpeg", "png", "gif", "bmp", "tiff", "svg", "webp", "heic"],
    "Audio": ["mp3", "wav", "flac", "aac", "ogg", "m4a", "wma", "opus"],
    "Video": ["mp4", "avi", "mkv", "mov", "wmv", "flv", "webm"],
    "Código": ["py", "js", "html", "css", "java", "c", "cpp", "go", "rs", "ts", "json", "sh"],
    "Comprimidos": ["zip", "rar", "7z", "tar", "gz", "bz2", "xz"]
}
