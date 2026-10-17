"""
core/checkpoint.py - Ledger de transferencias y control de reanudación (Checkpointing).

Permite pausar, reanudar y auditar transferencias masivas en <destino>/.memex/checkpoint.jsonl:
- Soporta OpRecord estructurado.
- make_op_id() con prefijo de namespace (ej. "backup|...", "clone|...").
- Escribe por lotes (batch_size=16) con fsync para garantizar persistencia sin cuellos de botella I/O.
- Detección de completado en O(1) con set en memoria.
"""

import hashlib
import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

MAX_LEDGER_BYTES = 64 * 1024 * 1024  # 64 MB para activar compactación


@dataclass(slots=True)
class OpRecord:
    """Representa el registro de una operación de transferencia.
    
    Attributes:
        op_id (str): Identificador único de la operación.
        origen (str): Ruta de origen.
        destino (str): Ruta de destino.
        size (int): Tamaño del archivo en bytes.
        mtime_ns (int): Tiempo de modificación en nanosegundos.
        estado (str): Estado de la operación ('copiando', 'completado', 'error', 'omitido').
        error (Optional[str]): Mensaje de error si la operación falló. Por defecto None.
        timestamp (str): Marca de tiempo de la operación. Por defecto "".
        job_id (Optional[str]): Identificador del trabajo. Por defecto None.
    """
    op_id: str
    origen: str
    destino: str
    size: int
    mtime_ns: int
    estado: str  # 'copiando', 'completado', 'error', 'omitido'
    error: Optional[str] = None
    timestamp: str = ""
    job_id: Optional[str] = None

    def __post_init__(self) -> None:
        """Inicializa los valores por defecto después de la creación."""
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Convierte el registro a un diccionario.
        
        Returns:
            Dict[str, Any]: Representación del registro en formato de diccionario.
        """
        return asdict(self)


def make_op_id(tipo: str, ruta_relativa: str, size: int, mtime_ns: int) -> str:
    """Genera un op_id determinista con prefijo de operación.
    
    Args:
        tipo (str): Prefijo del tipo de operación (ej. "backup", "clone").
        ruta_relativa (str): Ruta relativa del archivo.
        size (int): Tamaño del archivo en bytes.
        mtime_ns (int): Tiempo de modificación en nanosegundos.
        
    Returns:
        str: Identificador único generado para la operación.
    """
    payload = f"{tipo}|{ruta_relativa}|{size}|{mtime_ns}".encode("utf-8")
    hash_hex = hashlib.md5(payload).hexdigest()
    return f"{tipo}:{hash_hex}"


# Alias de retrocompatibilidad
def generar_op_id(ruta_relativa: str, size: int, mtime_ns: int) -> str:
    """Genera un op_id determinista usando 'op' como tipo. Alias de retrocompatibilidad.
    
    Args:
        ruta_relativa (str): Ruta relativa del archivo.
        size (int): Tamaño del archivo en bytes.
        mtime_ns (int): Tiempo de modificación en nanosegundos.
        
    Returns:
        str: Identificador único generado para la operación.
    """
    return make_op_id("op", ruta_relativa, size, mtime_ns)


class CheckpointLedger:
    """Gestor del libro contable de transferencias con checkpoint en destino.
    
    Attributes:
        raiz_destino (Path): Directorio raíz del destino.
        memex_dir (Path): Directorio oculto `.memex` en el destino.
        archivo_ledger (Path): Archivo de registro `.memex/checkpoint.jsonl`.
        batch_size (int): Tamaño del lote para guardar registros.
        job_id (str): Identificador del trabajo asociado al gestor.
    """

    def __init__(self, raiz_destino: Union[str, Path], batch_size: int = 16, job_id: Optional[str] = None) -> None:
        """Inicializa el CheckpointLedger.
        
        Args:
            raiz_destino (Union[str, Path]): Directorio raíz de destino donde se guardarán los archivos.
            batch_size (int): Cantidad de registros a almacenar en buffer antes de volcar a disco. Por defecto 16.
            job_id (Optional[str]): ID de trabajo único. Si no se provee, se genera uno nuevo. Por defecto None.
        """
        self.raiz_destino: Path = Path(raiz_destino)
        self.memex_dir: Path = self.raiz_destino / ".memex"
        self.archivo_ledger: Path = self.memex_dir / "checkpoint.jsonl"
        self.batch_size: int = max(1, batch_size)
        self.job_id: str = job_id or uuid.uuid4().hex[:12]

        self._completados: Set[str] = set()
        self._buffer: List[Dict[str, Any]] = []

        self._cargar_existente()

    def _cargar_existente(self) -> None:
        """Carga en memoria los op_ids completados previamente en este destino.
        
        Lee el archivo ledger y almacena los identificadores de operación que 
        están marcados como 'completado'.
        """
        if not self.archivo_ledger.exists():
            return

        try:
            with open(self.archivo_ledger, "r", encoding="utf-8") as f:
                for line in f:
                    line_str = line.strip()
                    if not line_str:
                        continue
                    try:
                        record = json.loads(line_str)
                        if record.get("estado") == "completado" and "op_id" in record:
                            self._completados.add(record["op_id"])
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass

    def tiene_errores_pendientes(self) -> List[Dict[str, Any]]:
        """Devuelve las entradas 'error' que no tengan un 'completado' posterior para el mismo op_id.
        
        Utilizado para --checkpoint-strict.
        
        Returns:
            List[Dict[str, Any]]: Lista de diccionarios representando los errores pendientes.
        """
        if not self.archivo_ledger.exists():
            return []

        errores: Dict[str, Dict[str, Any]] = {}
        try:
            with open(self.archivo_ledger, "r", encoding="utf-8") as f:
                for line in f:
                    line_str = line.strip()
                    if not line_str:
                        continue
                    try:
                        record = json.loads(line_str)
                        op_id = record.get("op_id")
                        estado = record.get("estado")
                        if not op_id:
                            continue
                        if estado == "error":
                            errores[op_id] = record
                        elif estado == "completado" and op_id in errores:
                            del errores[op_id]
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass
        return list(errores.values())

    def ya_completado(self, op_id: str) -> bool:
        """Verifica en O(1) si la operación ya fue finalizada con éxito.
        
        Args:
            op_id (str): Identificador de la operación.
            
        Returns:
            bool: True si está completada, False en caso contrario.
        """
        return op_id in self._completados

    def esta_completado(self, op_id: str) -> bool:
        """Alias de ya_completado.
        
        Args:
            op_id (str): Identificador de la operación.
            
        Returns:
            bool: True si está completada, False en caso contrario.
        """
        return self.ya_completado(op_id)

    def registrar(self, record: OpRecord) -> None:
        """Registra un OpRecord en el buffer y realiza flush con fsync al alcanzar batch_size.
        
        Args:
            record (OpRecord): Registro de la operación a guardar.
        """
        if not record.job_id:
            record.job_id = self.job_id

        if record.estado == "completado":
            self._completados.add(record.op_id)

        self._buffer.append(record.to_dict())
        if len(self._buffer) >= self.batch_size:
            self.flush()

    def registrar_completado(
        self,
        op_id: str,
        origen: str,
        destino_final: str,
        size: int,
        mtime_ns: int
    ) -> None:
        """Método de conveniencia para registrar una operación completada.
        
        Args:
            op_id (str): Identificador único de la operación.
            origen (str): Ruta de origen.
            destino_final (str): Ruta de destino final.
            size (int): Tamaño del archivo.
            mtime_ns (int): Tiempo de modificación en nanosegundos.
        """
        rec = OpRecord(
            op_id=op_id,
            origen=str(origen),
            destino=str(destino_final),
            size=size,
            mtime_ns=mtime_ns,
            estado="completado",
            job_id=self.job_id
        )
        self.registrar(rec)

    def flush(self) -> None:
        """Vuelca el buffer a disco y fuerza fsync.
        
        Asegura que las operaciones en buffer se persistan en el archivo
        físico del ledger.
        """
        if not self._buffer:
            return

        try:
            self.memex_dir.mkdir(parents=True, exist_ok=True)
            with open(self.archivo_ledger, "a", encoding="utf-8") as f:
                for rec in self._buffer:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                try:
                    os.fsync(f.fileno())
                except (OSError, PermissionError):
                    pass
            self._buffer.clear()
        except OSError:
            pass

    def compactar_si_necesario(self, umbral_bytes: int = MAX_LEDGER_BYTES) -> bool:
        """Compacta el archivo ledger si supera el umbral_bytes.
        
        Conserva solo la última entrada por op_id, eliminando 'copiando' y 'error' resueltos.
        
        Args:
            umbral_bytes (int): Tamaño máximo en bytes antes de iniciar la compactación.
                Por defecto MAX_LEDGER_BYTES (64 MB).
                
        Returns:
            bool: True si se realizó la compactación, False en caso contrario.
        """
        if not self.archivo_ledger.exists():
            return False

        try:
            if self.archivo_ledger.stat().st_size < umbral_bytes:
                return False

            ultimos: Dict[str, Dict[str, Any]] = {}
            with open(self.archivo_ledger, "r", encoding="utf-8") as f:
                for line in f:
                    line_str = line.strip()
                    if not line_str:
                        continue
                    try:
                        record = json.loads(line_str)
                        op = record.get("op_id")
                        if op:
                            ultimos[op] = record
                    except json.JSONDecodeError:
                        continue

            tmp_path = self.archivo_ledger.with_suffix(".jsonl.tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                for rec in ultimos.values():
                    if rec.get("estado") == "completado":
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                try:
                    os.fsync(f.fileno())
                except (OSError, PermissionError):
                    pass

            os.replace(tmp_path, self.archivo_ledger)
            return True
        except OSError:
            return False

    def cerrar(self) -> None:
        """Fuerza un flush de los datos en buffer y compacta si es necesario."""
        self.flush()
        self.compactar_si_necesario()

    @property
    def total_completados(self) -> int:
        """Obtiene el número total de operaciones completadas exitosamente.
        
        Returns:
            int: Cantidad de operaciones completadas.
        """
        return len(self._completados)

