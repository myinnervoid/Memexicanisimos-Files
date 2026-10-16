# Changelog

Todos los cambios notables de este proyecto se documentan en este archivo.

El formato está basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/),
y este proyecto sigue [Semantic Versioning](https://semver.org/lang/es/).

## [Unreleased]

## [1.1.0] - 2026-10-09

### Añadido — Motor
- Copia atómica con escritura a `.memex.partial`, `fsync` y `os.replace`.
- `copy_file_range` con fallback a stream de 8 MB (zero-copy en mismo FS).
- `CheckpointLedger` con `op_id` determinista (`{tipo}:{blake2b}`) y batching con `fsync`.
- Reanudación O(1) tras SIGINT, SIGKILL o caída de energía.
- Auto-sanación de `.partial` huérfanos y `.lock` con PID reciclado.
- Versionado en `.historial/` con rotación configurable (`MAX_VERSIONES_HISTORIAL = 5`).
- `--durabilidad {archivo,lote,none}` con batching de fsync.
- Streaming por generadores (`iterar_archivos`, `iterar_directorios`) con RAM constante.
- Prefiltro por tamaño antes del hashing de duplicados (evita 90–99 % de I/O innecesaria).
- `--checkpoint-strict` para abortar ante errores sin resolver.
- `job_id` con índice dual: `~/.memex/jobs.jsonl` + `<destino>/.memex/jobs/{job_id}.json`.
- `memex_resume` con `parent_job_id` para trazabilidad genealógica.
- Borrado seguro con sandbox inmutable (config, no parámetro).
- `shutil.copystat` para preservar permisos Unix, xattrs y timestamps.

### Añadido — MCP
- Servidor MCP con transporte stdio (JSON-RPC 2.0) y HTTP/SSE.
- Doble endpoint HTTP: `POST /mcp` (canónico) y `POST /tools/call` (REST simplificado).
- 8 herramientas MCP:
  - `memex_clonar`, `memex_respaldo`, `memex_status`, `memex_cancel`
  - `memex_resume`, `memex_jobs_list`, `memex_verify`, `memex_borrar_seguro`
- Modelo B asíncrono con `ThreadPoolExecutor`.
- Rate limiter sliding-window por token: 60 lecturas/min, 5 escrituras/min.
- Audit log con redacción de `$HOME` → `~`.
- Endpoint `/notify` con rotación automática de `notifications.jsonl`.
- Auto-recuperación de jobs huérfanos al arrancar (`recuperar_huerfanos`).
- Verificación de PID por `/proc/<pid>/stat` (evita falsos positivos por PID recycling).

### Añadido — CLI
- Subcomandos nuevos: `clonar`, `respaldo`, `borrar-seguro`, `deshacer`.
- Flags: `--durabilidad`, `--reanudar`, `--incremental`, `--simular`, `--checkpoint-strict`.
- Comando `memex` disponible tras `pip install`.

### Añadido — Tests
- 62 pruebas unitarias (61 OK, 1 skip por ausencia de servidor X11).
- Cobertura: atomicidad, checkpointing, seguridad, cancelación, resume, SIGKILL, rate limiting, redacción, MCP handshake.

### Añadido — Documentación
- `AGENTS.md`: guía para agentes con semántica de cancel/resume y cuotas.
- `MANIFEST.md`: especificación técnica con curva real de throughput.
- `DECISIONS.md`: registro de decisiones arquitectónicas.
- `AUDIT_REPORT.md`: auditoría técnica del estado del código.

### Cambiado
- `core.py` monolítico refactorizado a paquete `core/` manteniendo `core/__init__.py` retrocompatible.
- `logger.py` con fallback a `tempfile` si `$HOME` es de solo lectura.
- Throughput documentado por tamaño de archivo:
  - >50 MB: 80–100 MB/s
  - 10–50 MB: 50–65 MB/s
  - <5 MB: 25–30 MB/s
  - <500 KB: <15 MB/s

### Corregido
- `copy_file_range` con `EXDEV` rebobina el descriptor antes del fallback.
- `copia_atomica` captura `BaseException` (KeyboardInterrupt/SIGTERM) y limpia `.partial`.
- `registrar_operacion_undo` con `fsync` por lote (evita pérdida de traza ante corte).
- `unlink` en `deshacer_n_operaciones` verifica `size` y `mtime_ns` antes de borrar.
- `obtener_archivos` migrado a generador puro (evita materializar listas en RAM).
- Race condition en `generar_nombre_unico` mitigada con verificación defensiva.

## [1.0.0] - 2024-09-01

### Añadido
- GUI Tkinter con wizard de 5 pasos.
- Motor de organización por fecha/tipo/nombre.
- Desduplicación por MD5 y por nombre.
- Undo con historial JSONL.
- Clonación y respaldo inteligente.
- Empaquetado PyInstaller para Linux/Windows.
