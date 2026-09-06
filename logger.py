"""
Modulo logger.py - Logging Centralizado para Memexicanisimos Files.

Implementa un sistema de logging estructurado con soporte rotativo en disco
y redirección de eventos en tiempo real hacia colas de interfaz de usuario (GUI/CLI).
Soporta loguru si está disponible, o cae elegantemente a logging estándar.
"""

import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, Callable
import queue

from config import AppConfig

# Intento de importación de loguru
try:
    from loguru import logger as _loguru_logger
    HAS_LOGURU = True
except ImportError:
    HAS_LOGURU = False

# Cola global para redirección de logs a la GUI
gui_log_queue: Optional[queue.Queue] = None


class QueueHandler(logging.Handler):
    """Handler personalizado para emitir logs hacia una Queue de Tkinter."""
    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        log_entry = self.format(record)
        try:
            self.log_queue.put_nowait(('LOG_EJECUCION', log_entry))
        except Exception:
            pass


class AppLogger:
    """Administrador centralizado de Logs para toda la aplicación."""

    def __init__(self):
        self.log_file = AppConfig.HOME_DIR / ".organizador_app.log"
        self._setup_logging()

    def _setup_logging(self):
        if HAS_LOGURU:
            _loguru_logger.remove()
            # Consola
            _loguru_logger.add(sys.stdout, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level:10}</level> | <cyan>{message}</cyan>")
            # Archivo rotativo en Home (Max 10MB, retencion 10 dias)
            _loguru_logger.add(
                str(self.log_file),
                rotation="10 MB",
                retention="10 days",
                level="DEBUG",
                encoding="utf-8",
                enqueue=True
            )
            self.logger = _loguru_logger
        else:
            # Fallback a logging estándar de Python
            self.std_logger = logging.getLogger("MemexicanisimosFiles")
            self.std_logger.setLevel(logging.DEBUG)
            self.std_logger.handlers.clear()

            # Formateador
            fmt = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

            # Stream Handler (Consola)
            sh = logging.StreamHandler(sys.stdout)
            sh.setLevel(logging.INFO)
            sh.setFormatter(fmt)
            self.std_logger.addHandler(sh)

            # Rotating File Handler
            rfh = RotatingFileHandler(
                str(self.log_file),
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8"
            )
            rfh.setLevel(logging.DEBUG)
            rfh.setFormatter(fmt)
            self.std_logger.addHandler(rfh)

            self.logger = self.std_logger

    def registrar_gui_queue(self, log_queue: queue.Queue):
        """Conecta una cola de eventos GUI para enviar logs en tiempo real."""
        global gui_log_queue
        gui_log_queue = log_queue

        if HAS_LOGURU:
            def _gui_sink(message):
                if gui_log_queue:
                    gui_log_queue.put(('LOG_EJECUCION', message.strip()))
            _loguru_logger.add(_gui_sink, level="INFO", format="{time:HH:mm:ss} | {message}")
        else:
            qh = QueueHandler(log_queue)
            qh.setFormatter(logging.Formatter("%(asctime)s | %(message)s", datefmt="%H:%M:%S"))
            self.std_logger.addHandler(qh)

    def debug(self, msg: str):
        if HAS_LOGURU:
            self.logger.debug(msg)
        else:
            self.logger.debug(msg)

    def info(self, msg: str):
        if HAS_LOGURU:
            self.logger.info(msg)
        else:
            self.logger.info(msg)

    def warning(self, msg: str):
        if HAS_LOGURU:
            self.logger.warning(msg)
        else:
            self.logger.warning(msg)

    def error(self, msg: str, exc_info: bool = False):
        if HAS_LOGURU:
            self.logger.error(msg)
        else:
            self.logger.error(msg, exc_info=exc_info)


# Instancia única reutilizable
app_logger = AppLogger()
