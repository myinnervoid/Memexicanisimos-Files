"""
Modulo i18n.py - Sistema de Internacionalización (i18n) para Memexicanisimos Files.

Proporciona soporte multilenguaje mediante gettext con fallback automático a español.
Exporta la función global `_()` para envolver cadenas traducibles.
"""

import gettext
import os
from pathlib import Path

# Directorio raíz de traducciones
LOCALES_DIR = Path(__file__).parent / "locales"
DEFAULT_LANGUAGE = "es"

_translation = None

def init_i18n(lang: str = DEFAULT_LANGUAGE):
    """Inicializa el catálogo de traducciones para el idioma especificado."""
    global _translation
    try:
        if LOCALES_DIR.exists():
            _translation = gettext.translation(
                domain="messages",
                localedir=str(LOCALES_DIR),
                languages=[lang],
                fallback=True
            )
        else:
            _translation = gettext.NullTranslations()
    except Exception:
        _translation = gettext.NullTranslations()


def _(text: str) -> str:
    """Función de traducción global. Retorna la cadena traducida o la original."""
    if _translation is None:
        init_i18n()
    return _translation.gettext(text)


# Inicializar automáticamente al importar
init_i18n()
