# 🏛️ REGISTRO DE DECISIONES ARQUITECTÓNICAS (ADR) & MATRIZ DE TRADE-OFFS
**Proyecto:** Memexicanisimos Files v1.0  
**Fecha:** Septiembre 2026  
**Estándar:** Motor Autónomo de Auditoría y Evolución v3.1  

---

## 1. Registro de Decisiones de Arquitectura

### ADR-01: Adopción del Contrato Estándar `ApiResponse<T>` con Retrocompatibilidad para `ServiceResult`
* **Contexto del Problema:**  
  La Ley Global 5 exige que las respuestas sigan la estructura:
  $$\text{ApiResponse}\langle T\rangle = \{\text{success}, \text{data}, \text{error\_code}, \text{message}\}$$
  Actualmente, el sistema utiliza `ServiceResult` con el campo `error: Optional[str]`, lo que crea inconsistencias en la integración cliente-servidor/IPC y rompe el estándar corporativo del ecosistema Memexicanisimos.
* **Decisión Adoptada:**  
  Extender `ServiceResult` para incluir el atributo `message` sincronizado bidireccionalmente con `error`, y definir `ApiResponse = ServiceResult` como tipo genérico exportado en `app_types.py`. Si se define `error`, automáticamente se asigna a `message` y viceversa.
* **Consecuencias:**  
  * *Positivas:* Adherencia al 100% con la Ley Global 5, cero regresiones en el código existente que consuma `res.error`, interfaz consistente para consumidores modernos.
  * *Negativas:* Pequeña duplicidad de campos en la serialización a diccionario (`to_dict()`).

---

### ADR-02: Desacoplamiento y Reactivación de la Línea de Comandos (`cli.py`)
* **Contexto del Problema:**  
  `cli.py` fallaba inmediatamente con `ImportError` debido a que intentaba importar funciones obsoletas (`generar_plan`, `simular_plan`, `ejecutar_plan`) eliminadas durante el desacoplamiento del core.
* **Decisión Adoptada:**  
  Reescribir `cli.py` para consumir la API oficial y moderna: `generar_plan_con_estructura` y `ejecutar_plan_con_modo`. Soportar tanto ejecución directa como modo `--simular` (dry-run) reportando a través de `ServiceResult`/`ApiResponse`.
* **Consecuencias:**  
  * *Positivas:* CLI completamente funcional y testeable; permite automatizaciones y scripts de administración sin GUI.
  * *Negativas:* Requiere mantener sincronizados los flags de la terminal con las opciones del asistente gráfico.

---

### ADR-03: Implementación del Manejador FSM para `FIN_EJECUCION` en `gui_wizard.py`
* **Contexto del Problema:**  
  La interfaz gráfica enviaba el mensaje `('FIN_EJECUCION', res)` a través de `cola_eventos` al terminar el Paso 4, pero el bucle de polling `_procesar_cola_eventos` no tenía implementada esa rama, provocando que la UI quedara indefinidamente congelada en estado pendiente.
* **Decisión Adoptada:**  
  Añadir el manejador de eventos `FIN_EJECUCION` en `gui_wizard.py` restaurando el estado `[IDLE]` de los botones, actualizando la etiqueta de estado a `[SUCCESS]` o `[FAULT]`, refrescando los contadores y presentando un diálogo de resumen interactivo.
* **Consecuencias:**  
  * *Positivas:* Corrige el bug bloqueante más grave de la aplicación; garantiza que el usuario reciba confirmación visual y registro completo del proceso.
  * *Negativas:* Ninguna; es una corrección mandatoria de arquitectura.

---

### ADR-04: Batching de Syscalls en Historial de Undo
* **Contexto del Problema:**  
  En operaciones masivas, `core.py` realizaba un `open()` y `close()` por cada archivo procesado para escribir en `.organizador_undo.jsonl`. En lotes de 10,000 archivos, esto provocaba 10,000 escrituras en disco y degradación de rendimiento I/O.
* **Decisión Adoptada:**  
  Modificar la recolección de operaciones de undo dentro de `ejecutar_plan_con_modo` para acumularlas en memoria y realizar una sola escritura en bloque al finalizar la ejecución, o escribir en fragmentos de búfer configurable.
* **Consecuencias:**  
  * *Positivas:* Reducción de llamadas al sistema de archivos de $O(N)$ a $O(1)$; aumento sustancial en la velocidad de ejecución.
  * *Negativas:* Si el proceso sufre un corte de energía abrupto a la mitad, los registros no escritos en disco de los archivos ya movidos no quedarían registrados en el historial de deshacer. (Mitigación: flush periódico cada 100 archivos).

---

### ADR-05: Verificación Preventiva de Espacio en Disco (Guard-Check)
* **Contexto del Problema:**  
  Si el disco de destino no cuenta con espacio suficiente para un lote o clonación, el sistema copiaba hasta que el disco se llenaba, lanzando un `OSError` no recuperable y dejando el destino en estado corrupto e inconsistente.
* **Decisión Adoptada:**  
  Antes de ejecutar cualquier operación en modo `Copiar` o `clonar_carpeta`, calcular el tamaño total proyectado en bytes y contrastarlo contra `shutil.disk_usage(destino).free`. Si el espacio es insuficiente, abortar preventivamente retornando `ErrorCode.ERR_DISK_FULL`.
* **Consecuencias:**  
  * *Positivas:* Idempotencia y seguridad transaccional; previene desbordamiento y corrupción de particiones.
  * *Negativas:* Ligera latencia inicial requerida para calcular el tamaño acumulado de los archivos en el árbol de origen.

---

## 2. Matriz de Trade-offs Técnica

| Decisión Técnica | Beneficio Directo | Costo / Penalización | Alternativa Descartada | Razón del Rechazo |
| :--- | :--- | :--- | :--- | :--- |
| **Persistencia Undo en JSONL con Flush por Lotes** | Simplicidad, compatibilidad Unix (`tail`/`grep`), cero dependencias adicionales. | Carece de transacciones ACID y recuperación ante fallos de alimentación durante el flush. | Migrar inmediatamente a base de datos relacional SQLite con WAL. | Descartada en esta fase para evitar incompatibilidad con el formato de usuario existente `~/.organizador_undo.jsonl`. |
| **Contrato Híbrido `ServiceResult` + `ApiResponse`** | Cumple Ley Global 5 sin alterar firmas de llamadas existentes en `gui_wizard.py` y `core.py`. | Duplicidad de alias semánticos (`error` y `message`). | Reemplazo abrupto renombrando todos los usos de `.error` a `.message`. | Riesgo elevado de generar regresiones no detectadas en componentes legacy no cubiertos por pruebas. |
| **Guard Preventivo de Espacio en Disco** | Evita operaciones abortivas a mitad de camino y previene corrupción de particiones del usuario. | Tiempo de cálculo previo de tamaños en árboles de carpetas profundos. | Copia reactiva capturando `OSError: [Errno 28]`. | La falla reactiva deja archivos parcialmente escritos y consume cuota de disco sin posibilidad de recuperación limpia. |
| **Cola de Mensajería GUI basada en `queue.Queue`** | Hilo desacoplado, sin bloqueos del bucle de eventos Tkinter, compatible con el modelo de concurrencia Python. | Polling periódico con `root.after(100, ...)` consume ciclos mínimos de CPU en reposo. | Ejecución síncrona en el hilo principal de Tkinter. | Descartada categóricamente porque congela la ventana durante la transferencia de archivos pesados. |
| **Consolidación a único `.spec` (`memexicanisimos-files.spec`)** | Unifica el empaquetado y elimina confusión en el build automatizado en Linux y Windows. | Requiere actualizar documentación y scripts de despliegue `build_unix.sh`. | Mantener 4 archivos `.spec` para compatibilidad con compilaciones antiguas. | Descartada por inducir a errores humanos de despliegue y deuda técnica innecesaria. |
