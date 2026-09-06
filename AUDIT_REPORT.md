# 📋 INFORME DE AUDITORÍA INTEGRAL DE ARQUITECTURA (5 VECTORES)
**Proyecto:** Memexicanisimos Files v1.0  
**Motor de Auditoría:** Motor Autónomo de Auditoría y Evolución de Software v3.1  
**Fecha de Evaluación:** Septiembre 2026  
**Entorno Analizado:** Linux x86_64 / Python 3.8+ / Tkinter Monolítico / CLI  

---

## 1. Resumen Ejecutivo y Estado General del Sistema

**Memexicanisimos Files** es una herramienta de escritorio y terminal para la organización masiva, renombrado, deduplicación y clonación incremental de archivos. Se encuentra en una fase de transición arquitectónica: se han introducido módulos desacoplados recientes (`app_types.py`, `config.py`, `logger.py`, `error_codes.py`, `i18n.py`) para reemplazar la arquitectura monolítica original (`legacy/gui.py`), pero persisten desincronizaciones severas entre la interfaz gráfica (`gui_wizard.py`), la CLI (`cli.py`), los contratos de respuesta y el núcleo de dominio (`core.py`).

### Calificación de Salud Global por Vector (Escala 1 a 10)
| Vector | Nombre | Calificación | Estado |
| :--- | :--- | :---: | :--- |
| **Vector 1** | Dominio, Invariantes & Marco Legal | **6.5 / 10** | ⚠️ Invariantes parciales; discrepancia README vs código real |
| **Vector 2** | Contratos de Datos, Esquema & Catálogo de Fallos | **6.0 / 10** | ⚠️ Contratos presentes pero divergentes de `ApiResponse<T>` |
| **Vector 3** | Lógica de Dominio, Concurrencia & Hardening | **5.5 / 10** | ⚠️ Syscalls excesivas en Undo; sin validación previa de disco |
| **Vector 4** | Superficie de Interfaz, Ergonomía & Mapeo de Estados | **4.5 / 10** | 🔴 Bug crítico: UI no consume `FIN_EJECUCION`; FSM incompleta |
| **Vector 5** | Infraestructura, Resiliencia & Auditoría Cruzada | **4.0 / 10** | 🔴 CLI rota; 6 tests únicamente; sin CI/CD; specs múltiples |

**Veredicto General:** **Requiere Remediación Inmediata de Brechas Críticas** antes de avanzar a nuevas funciones.

---

## 2. Evaluación Detallada por los 5 Vectores

### Vector 1: Dominio, Invariantes & Marco Legal
* **¿Existen invariantes de negocio documentadas? ¿Se respetan en el código?**
  * *Invariante de no sobreescritura:* Se respeta parcialmente con `generar_nombre_unico` y detección de duplicados.
  * *Invariante de reversibilidad (Undo):* Se registra en `~/.organizador_undo.jsonl`. Sin embargo, no existe concepto de "Sesión o Lote de Transacción" (Batch ID). Si una ejecución procesa 5,000 archivos, cada uno es un registro aislado, imposibilitando un "Deshacer Lote Completo" atómico en una sola acción sin iterar manualmente `n` operaciones.
  * *Discrepancia crítica documental vs código:* El `README.md` (línea 56) publicita: *"Clonación de discos/particiones a nivel de bloque con dd / ddrescue y verificación checksum MD5"*. Dicha funcionalidad **NO existe en el código fuente**.
* **¿Se identifican normativas legales/fiscales aplicables? ¿Hay cumplimiento?**
  * Licencia MIT documentada en `LICENSE` y `README.md`.
  * Privacidad (LFPDPPP / GDPR): Al procesar metadatos personales, la limpieza EXIF/ID3 es destructiva y no solicita confirmación con advertencia legal sobre pérdida irrevocable de metadatos de autoría y derechos de autor. Los logs registran rutas completas del sistema del usuario sin anonimización opcional.
* **¿Están definidos los ciclos de vida de las entidades?**
  * Entidades `PlanArchivo`, `FiltrosAvanzados` y `UndoRecord` son tratadas como diccionarios planos sin máquina de estados formal (e.g., `PLANIFICADO` ➔ `EN_PROCESO` ➔ `EJECUTADO` / `FALLIDO` / `REVERTIDO`).

---

### Vector 2: Contratos de Datos, Esquema & Catálogo de Fallos
* **¿Hay definiciones formales de tipos/interfaces? ¿Son consistentes entre capas?**
  * Existen `TypedDict` (`PlanArchivo`, `FiltrosAvanzados`, `EstructuraConfig`, `UndoRecord`) y `@dataclass ServiceResult`.
  * *Brecha con Ley Global 5:* El contrato estándar especificado es:
    $$\text{ApiResponse}\langle T\rangle = \{\text{success: bool, data: } T, \text{error\_code: Optional[str], message: Optional[str]}\}$$
    Actualmente `ServiceResult` emplea `error: Optional[str]` en vez de `message`, o carece del alias `ApiResponse` / compatibilidad estandarizada.
  * En `core.py`, funciones principales reciben parámetros tipados como `Dict[str, Any]` en lugar de requerir estrictamente `EstructuraConfig` o `FiltrosAvanzados`.
* **¿El esquema de base de datos está optimizado?**
  * No hay base de datos relacional (SQLite). Se utilizan archivos planos: `.organizador_config.json`, `.organizador_perfiles.json` y `.organizador_undo.jsonl`.
  * *Brecha de concurrencia:* `.organizador_undo.jsonl` carece de bloqueo de archivo (`file locking` tipo `fcntl`/`msvcrt`). Dos instancias concurrentes provocan escrituras corruptas en el log de reversión.
* **¿Existe un catálogo de `error_code`? ¿Está completo y es usado por el backend?**
  * `error_codes.py` define 18 códigos (`ErrorCode`).
  * *Brecha:* `gui_wizard.py` únicamente evalúa de forma explícita `ErrorCode.ERR_EXECUTION_CANCELLED` (línea 669). Todas las demás excepciones se diluyen en mensajes genéricos sin aprovechar el catálogo para guiar al usuario.

---

### Vector 3: Lógica de Dominio, Concurrencia & Hardening
* **¿La lógica de negocio es atómica e idempotente donde corresponde?**
  * En `ejecutar_plan_con_modo` y `clonar_carpeta`, no se valida previamente el espacio disponible en disco (`shutil.disk_usage`). Si un lote de 40 GB sobrepasa la capacidad disponible a la mitad del proceso, aborta en crudo dejando una transacción incompleta.
* **¿Se minimizan syscalls?**
  * *Fallo de rendimiento I/O:* En `core.py` (líneas 437-444), para cada archivo procesado individualmente se invoca `registrar_operacion_undo`, que ejecuta un `open(path, 'a')` individual. Procesar 10,000 archivos dispara 10,000 aperturas y cierres de archivo. Debe usarse escritura por lotes (buffering) o transacción única al final del batch.
* **¿Hay medidas de seguridad y hardening?**
  * No hay validación de Path Traversal ni contención de Symlinks circulares/externos (`follow_symlinks=False` no está forzado en copias).
  * Excepciones personalizadas en `app_types.py` (`DiskFullError`, `PathTooLongError`, `FileLockedError`, `PermissionDeniedError`) están definidas pero **nunca son lanzadas** en `core.py`. Se capturan excepciones genéricas de Python (`OSError`, `PermissionError`).

---

### Vector 4: Superficie de Interfaz, Ergonomía & Mapeo de Estados
* **Autómata Finito de Interfaz (Ley Global 6):**
  * La interfaz no implementa formalmente los 5 estados `[IDLE]`, `[PENDING]`, `[SUCCESS]`, `[EMPTY]`, `[FAULT]`.
  * **HALLAZGO CRÍTICO EN UI (`gui_wizard.py`):**
    En `gui_wizard.py` (línea 616), el hilo de trabajo del Paso 4 envía a la cola:
    `self.cola_eventos.put(('FIN_EJECUCION', res))`
    Sin embargo, en el consumidor `_procesar_cola_eventos` (líneas 620-692), **NO EXISTE la rama `elif tipo == 'FIN_EJECUCION':`**. Solo existen `FIN_GENERAR_PLAN`, `PROGRESO_PROCESADO`, `PROGRESO_CLONACION` y `FIN_CLONACION`.
    **Consecuencia directa:** Al finalizar la organización de archivos, la UI se queda colgada para siempre en estado ocupado (`self.ejecutando = True`), el botón de ejecución no se reactiva y no se muestra retroalimentación de éxito o resumen final al usuario.
* **Accesibilidad (WCAG 2.2 AA) y Ergonomía:**
  * La paleta de colores (`#FAF7F2`, `#111827`, `#4B5563`, `#B91C1C`) tiene contrastes adecuados para texto (ratios > 4.5:1).
  * Sin embargo, falta navegación completa por teclado (tab index ordenado, mnemonics Alt+N / Alt+P en botones del asistente).
  * No hay soporte para lectores de pantalla ni anunciadores de accesibilidad en eventos asíncronos.
* **Mapeo 1:1 entre errores del backend y mensajes de UI:**
  * Ausente. Los errores se muestran pasando `res.error` en un `messagebox.showerror` sin guía prescriptiva de resolución.

---

### Vector 5: Infraestructura, Resiliencia & Auditoría Cruzada
* **¿Hay pruebas automatizadas? ¿Qué cobertura tienen?**
  * Existen únicamente 2 suites de pruebas: `tests/test_core.py` (5 métodos) y `tests/test_integration_gui.py` (1 método). Cobertura estimada: ~25-30%.
  * El script `probar_estructuras.py` contiene validaciones críticas pero está aislado como script en la raíz, sin integrarse a la suite de pruebas automatizadas.
* **¿Existe estrategia de despliegue reproducible?**
  * Hay 4 archivos `.spec` divergentes en la raíz (`OrganizadorArchivos.spec`, `OrganizadorArchivosWizard.spec`, `organizador_archivos.spec`, `memexicanisimos-files.spec`), generando ambigüedad sobre cuál es el archivo canónico de compilación.
  * No existe integración continua (CI) en GitHub Actions que valide las pruebas unitarias en Linux, Windows y macOS.
* **Validación Cruzada entre Vectores (Auditoría Cruzada):**
  * **HALLAZGO CRÍTICO EN CLI (`cli.py`):**
    El archivo `cli.py` (línea 12) realiza:
    `from core import generar_plan, simular_plan, ejecutar_plan, RutaNoValidaError`
    Dichas funciones fueron renombradas a `generar_plan_con_estructura` y `ejecutar_plan_con_modo` en `core.py`. Al ejecutar `python3 cli.py --help` o invocar el CLI, el programa arroja un **`ImportError` fatal inmediato**, inutilizando por completo el modo de línea de comandos.

---

## 3. Matriz de Hallazgos Clasificados por Criticidad y Vector

| ID | Vector | Hallazgo | Criticidad | Evidencia | Acción Sugerida |
| :--- | :---: | :--- | :---: | :--- | :--- |
| **HAL-01** | V5 / V2 | `cli.py` falla con `ImportError` al iniciar; invoca funciones inexistentes en `core.py` | **Crítico** | `cli.py:12`: `from core import generar_plan, simular_plan...` | Refactorizar `cli.py` para consumir `generar_plan_con_estructura`, `ejecutar_plan_con_modo` y los contratos `ServiceResult`/`ApiResponse`. |
| **HAL-02** | V4 | Evento `FIN_EJECUCION` no se maneja en `_procesar_cola_eventos`, congelando la UI al terminar el Paso 4 | **Crítico** | `gui_wizard.py:616` vs `gui_wizard.py:620-692` | Agregar el manejador `elif tipo == 'FIN_EJECUCION':` en `_procesar_cola_eventos`, desbloquear controles y emitir feedback al usuario. |
| **HAL-03** | V3 / V1 | Ausencia de verificación previa de espacio en disco antes de mover/copiar/clonar archivos | **Mayor** | `core.py:377` y `core.py:571` no consultan `shutil.disk_usage` | Implementar guard-check previo que compare tamaño total requerido vs espacio libre en destino; disparar `DiskFullError` / `ERR_DISK_FULL`. |
| **HAL-04** | V3 | Excesivas Syscalls en registro de Undo: `open()`/`close()` en cada archivo de un bucle | **Mayor** | `core.py:437-444` dentro del ciclo `for` en `ejecutar_plan_con_modo` | Acumular registros en búfer de memoria y realizar un `append` en bloque o escritura atómica al concluir el lote. |
| **HAL-05** | V2 | Contrato de respuesta diverge del estándar `ApiResponse<T> = { success, data, error_code, message }` | **Mayor** | `app_types.py:115` (`ServiceResult` usa `error` en lugar de `message`) | Crear clase/alias estándar `ApiResponse` y adaptar `ServiceResult` para mantener retrocompatibilidad con `message` y `error`. |
| **HAL-06** | V1 / V5 | Funcionalidad `dd` / `ddrescue` prometida en `README.md` no existe en el código | **Mayor** | `README.md:56` menciona clonación de particiones con `dd`/`ddrescue` | Alinear documentación con la realidad del sistema o implementar el módulo con las debidas salvaguardas de seguridad. |
| **HAL-07** | V4 / V2 | Catálogo `ErrorCode` casi no se consume en UI; mapeo de errores 1:1 inexistente | **Mayor** | `gui_wizard.py:17` solo usa `ErrorCode` en 1 lugar | Crear un diccionario unificado de traducción de `ErrorCode` a instrucciones de resolución amigables para el usuario. |
| **HAL-08** | V5 | Cobertura de pruebas extremadamente baja (solo 6 tests); `probar_estructuras.py` desintegrado | **Mayor** | `tests/test_core.py` (5), `tests/test_integration_gui.py` (1) | Migrar `probar_estructuras.py` a `tests/test_estructuras.py`, añadir tests de CLI y pruebas de error/disco. |
| **HAL-09** | V5 | Múltiples archivos `.spec` de PyInstaller desactualizados en la raíz | **Menor** | 4 archivos `.spec` presentes en la raíz | Consolidar en un único `memexicanisimos-files.spec` canónico y eliminar los obsoletos. |
| **HAL-10** | V3 / V2 | Excepciones personalizadas (`DiskFullError`, `FileLockedError`, etc.) definidas pero no usadas | **Menor** | `app_types.py:20-63` vs `core.py` | Vincular las excepciones del sistema en `core.py` con mapeo a sus respectivos `ErrorCode`. |

---

## 4. Matriz de Brechas de Artefactos

| Artefacto Esperado | Estado Actual | Brecha Detectada | Prioridad |
| :--- | :--- | :--- | :---: |
| **Contrato Estándar `ApiResponse<T>`** | Existe `ServiceResult` parcial | No implementa `message` estándar ni genéricos de respuesta | **Alta** |
| **Mapeador de Errores UI (`UIErrorMapper`)** | Inexistente | UI muestra texto de error crudo sin acciones sugeridas | **Alta** |
| **Manejador de Cola `FIN_EJECUCION`** | Inexistente | Bloquea la UI tras ejecutar la tarea principal | **Crítica** |
| **CLI Funcional (`cli.py`)** | Roto (`ImportError`) | No funciona en terminal; desalineado con `core.py` | **Crítica** |
| **Guard de Capacidad de Almacenamiento** | Inexistente | Riesgo de I/O abortivo a mitad de transferencia | **Alta** |
| **Suite de Pruebas Unificadas** | 6 tests aislados | Falta integración de estructuras, CLI y pruebas de fallo | **Alta** |
| **FSM de Interfaz de Usuario** | Estados implícitos no controlados | No gestiona formalmente `[IDLE, PENDING, SUCCESS, EMPTY, FAULT]` | **Media** |
| **Registro de Decisiones (`DECISIONS.md`)** | Inexistente | Falta historial de decisiones arquitectónicas y trade-offs | **Media** |
| **Pipeline CI/CD (.github/workflows)** | Inexistente | No se ejecutan pruebas automáticas al hacer push | **Baja** |

---

## 5. Métricas de Aptitud y Evaluación de Salud (Ley Global 7)

| Métrica de Aptitud | Estado Actual | Umbral Ideal | Brecha / Diagnóstico |
| :--- | :---: | :---: | :--- |
| **Disponibilidad de CLI** | 0% (Falla al importar) | 100% | ❌ Roto por desincronización de API |
| **Finalización de Flujo GUI (Paso 4)** | 0% (UI se cuelga en cola) | 100% | ❌ Roto por omisión de `FIN_EJECUCION` |
| **Cobertura de Pruebas Automatizadas** | ~28% | $\ge 80\%$ | ⚠️ Riesgo alto de regresión |
| **Syscalls en Registro de Undo (N archivos)** | $O(N)$ operaciones de apertura | $O(1)$ batch write | ⚠️ Penalización severa de I/O |
| **Adherencia a Contrato `ApiResponse`** | Parcial (`ServiceResult`) | 100% | ⚠️ Desincronizado con Ley Global 5 |
| **Resiliencia ante Desbordamiento de Disco** | Nula (Falla reactiva `OSError`) | Preventiva pre-ejecución | ⚠️ Riesgo de pérdida de datos / corrupción |

---

## 6. Plan de Mejoras Priorizado (Fase 2)

### Bloque 1: Correcciones Críticas Inmediatas (P0 - Quick Wins de Alto Impacto)
1. **Corregir `gui_wizard.py`:** Implementar el manejo del evento `FIN_EJECUCION` en `_procesar_cola_eventos` para desbloquear la UI, actualizar contadores y mostrar feedback adecuado.
2. **Reparar `cli.py`:** Actualizar imports y adaptar el flujo a `generar_plan_con_estructura` y `ejecutar_plan_con_modo`, consumiendo `ApiResponse`.
3. **Estandarizar `ApiResponse<T>` en `app_types.py`:** Añadir alias y atributo `message` con retrocompatibilidad bidireccional sobre `ServiceResult`.

### Bloque 2: Resiliencia y Hardening de Dominio (P1)
4. **Guard de Capacidad de Almacenamiento:** Calcular tamaño total antes de procesar y verificar `shutil.disk_usage` en destino tanto en organización como en clonación.
5. **Optimización de Syscalls en Undo:** Modificar `registrar_operacion_undo` para aceptar un lote completo de operaciones y persistirlo en una única apertura de archivo.
6. **Mapeador de Errores UI:** Crear función/módulo de traducción entre `ErrorCode` y mensajes explicativos para el usuario con acciones recomendadas.

### Bloque 3: Infraestructura, Calidad y Pruebas (P2)
7. **Integración de Pruebas:** Mover `probar_estructuras.py` a `tests/test_estructuras.py` e incorporar pruebas unitarias completas para `cli.py` y manejo de errores.
8. **Limpieza de Archivos `.spec`:** Eliminar los 3 `.spec` obsoletos y mantener únicamente `memexicanisimos-files.spec`.
9. **Generación de `DECISIONS.md`:** Formalizar las decisiones técnicas y su matriz de trade-offs.
