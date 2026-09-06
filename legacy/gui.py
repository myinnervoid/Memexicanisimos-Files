#!/usr/bin/env python3
"""
Modulo gui.py - Interfaz Grafica de Usuario (GUI) con Hilos (Threading)
para organizacion masiva de archivos sin congelar la aplicacion.
"""

import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
import threading
import queue
import shutil
from pathlib import Path
from typing import List, Dict, Any

from core import generar_plan, RutaNoValidaError, generar_nombre_unico


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Organizador de Archivos por Fecha")
        self.root.geometry("950x700")
        self.root.minsize(800, 600)

        # Almacenamiento del plan generado
        self.planes_actuales: List[Dict[str, Any]] = []

        # Flag para control de ejecucion de hilos secundarios
        self.ejecutando = False

        # Cola segura entre hilos para enviar eventos a la GUI principal
        self.cola_eventos = queue.Queue()

        # Configurar evento al cerrar la ventana principal
        self.root.protocol("WM_DELETE_WINDOW", self._al_cerrar_ventana)

        self._crear_menu()
        self._crear_interfaz()

        # Iniciar polling recurrente en el hilo principal de Tkinter
        self.root.after(100, self._procesar_cola_eventos)

    def _crear_menu(self):
        """Crea la barra de menu principal."""
        barra_menu = tk.Menu(self.root)
        
        # Menu Archivo
        menu_archivo = tk.Menu(barra_menu, tearoff=0)
        menu_archivo.add_command(label="Guardar log...", command=self._guardar_log)
        menu_archivo.add_separator()
        menu_archivo.add_command(label="Salir", command=self._al_cerrar_ventana)
        
        barra_menu.add_cascade(label="Archivo", menu=menu_archivo)
        self.root.config(menu=barra_menu)

    def _crear_interfaz(self):
        """Construye la disposicion visual de los widgets en la ventana."""
        style = ttk.Style()
        style.theme_use("clam")

        # ---------------------------------------------------------
        # 1. FRAME SUPERIOR (Parametros de Configuracion)
        # ---------------------------------------------------------
        frame_top = ttk.LabelFrame(self.root, text=" Configuración de Parámetros ", padding=10)
        frame_top.pack(fill="x", padx=10, pady=5)

        # Ruta Origen
        ttk.Label(frame_top, text="Ruta Origen:").grid(row=0, column=0, sticky="w", pady=2)
        self.entry_origen = ttk.Entry(frame_top, width=55)
        self.entry_origen.grid(row=0, column=1, padx=5, pady=2, sticky="ew")
        self.btn_exam_origen = ttk.Button(frame_top, text="Examinar...", command=self._examinar_origen)
        self.btn_exam_origen.grid(row=0, column=2, padx=5, pady=2)

        # Ruta Destino
        ttk.Label(frame_top, text="Ruta Destino:").grid(row=1, column=0, sticky="w", pady=2)
        self.entry_destino = ttk.Entry(frame_top, width=55)
        self.entry_destino.grid(row=1, column=1, padx=5, pady=2, sticky="ew")
        self.btn_exam_destino = ttk.Button(frame_top, text="Examinar...", command=self._examinar_destino)
        self.btn_exam_destino.grid(row=1, column=2, padx=5, pady=2)

        # Extensiones
        ttk.Label(frame_top, text="Extensiones:").grid(row=2, column=0, sticky="w", pady=2)
        self.entry_extensiones = ttk.Entry(frame_top, width=55)
        self.entry_extensiones.insert(0, ".jpg, .png, .pdf")
        self.entry_extensiones.grid(row=2, column=1, padx=5, pady=2, sticky="ew")
        ttk.Label(frame_top, text="(Vacío para todas)").grid(row=2, column=2, sticky="w", padx=5)

        # Checkbuttons
        frame_checks = ttk.Frame(frame_top)
        frame_checks.grid(row=3, column=0, columnspan=3, sticky="w", pady=5)

        self.var_subcarpetas = tk.BooleanVar(value=True)
        self.var_exif = tk.BooleanVar(value=True)
        self.var_hash = tk.BooleanVar(value=False)

        ttk.Checkbutton(frame_checks, text="Incluir subcarpetas", variable=self.var_subcarpetas).pack(side="left", padx=5)
        ttk.Checkbutton(frame_checks, text="Usar metadatos EXIF", variable=self.var_exif).pack(side="left", padx=5)
        ttk.Checkbutton(frame_checks, text="Detección de duplicados por hash", variable=self.var_hash).pack(side="left", padx=5)

        frame_top.columnconfigure(1, weight=1)

        # ---------------------------------------------------------
        # 2. FRAME MEDIO (Treeview / Tabla de Vista Previa)
        # ---------------------------------------------------------
        frame_mid = ttk.LabelFrame(self.root, text=" Vista Previa del Plan ", padding=10)
        frame_mid.pack(fill="both", expand=True, padx=10, pady=5)

        columnas = ("archivo", "accion", "destino", "fecha")
        self.tree = ttk.Treeview(frame_mid, columns=columnas, show="headings", selectmode="browse")

        self.tree.heading("archivo", text="Archivo")
        self.tree.heading("accion", text="Acción")
        self.tree.heading("destino", text="Destino")
        self.tree.heading("fecha", text="Fecha Detectada")

        self.tree.column("archivo", width=180, anchor="w")
        self.tree.column("accion", width=100, anchor="center")
        self.tree.column("destino", width=420, anchor="w")
        self.tree.column("fecha", width=120, anchor="center")

        scrollbar = ttk.Scrollbar(frame_mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Configurar colores de filas en el Treeview
        self.tree.tag_configure("MOVER", foreground="#006600")
        self.tree.tag_configure("DUPLICADO", foreground="#CC6600")
        self.tree.tag_configure("ERROR", foreground="#CC0000")

        # ---------------------------------------------------------
        # 3. FRAME INFERIOR (Acciones, Barra de Progreso y Log)
        # ---------------------------------------------------------
        frame_bot = ttk.Frame(self.root, padding=10)
        frame_bot.pack(fill="both", padx=10, pady=5)

        frame_botones = ttk.Frame(frame_bot)
        frame_botones.pack(fill="x", pady=2)

        self.btn_analizar = ttk.Button(frame_botones, text="🔍 Analizar y Previsualizar", command=self.analizar)
        self.btn_analizar.pack(side="left", padx=5)

        self.btn_ejecutar = ttk.Button(frame_botones, text="🚀 Ejecutar Movimientos", command=self.ejecutar, state="disabled")
        self.btn_ejecutar.pack(side="left", padx=5)

        # Barra de progreso
        self.progressbar = ttk.Progressbar(frame_bot, orient="horizontal", mode="indeterminate")
        self.progressbar.pack(fill="x", pady=5)

        # ScrolledText para log de auditoria
        ttk.Label(frame_bot, text="Registro de Actividad (Log):").pack(anchor="w", pady=(5, 2))
        self.log_text = scrolledtext.ScrolledText(frame_bot, height=7, state="normal")
        self.log_text.pack(fill="both", expand=True)

    # ---------------------------------------------------------
    # GESTION DE EVENTOS CON QUEUE Y ROOT.AFTER
    # ---------------------------------------------------------
    def _procesar_cola_eventos(self):
        """Metodo que se ejecuta periodicamente en el Hilo Principal para procesar eventos de los hilos."""
        try:
            while True:
                tipo, datos = self.cola_eventos.get_nowait()
                if tipo == 'FIN_ANALISIS':
                    planes, lista_errores, error_fatal = datos
                    self._finalizar_analizar_gui(planes, lista_errores, error_fatal)
                elif tipo == 'PROGRESO_EJECUCION':
                    paso_actual, msg_log = datos
                    self._actualizar_progreso_gui(paso_actual, msg_log)
                elif tipo == 'FIN_EJECUCION':
                    exitos, errores = datos
                    self._finalizar_ejecutar_gui(exitos, errores)
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._procesar_cola_eventos)

    # ---------------------------------------------------------
    # METODOS DE NAVEGACION Y ARCHIVO
    # ---------------------------------------------------------
    def _examinar_origen(self):
        directorio = filedialog.askdirectory(title="Seleccionar Carpeta Origen")
        if directorio:
            self.entry_origen.delete(0, tk.END)
            self.entry_origen.insert(0, directorio)

    def _examinar_destino(self):
        directorio = filedialog.askdirectory(title="Seleccionar Carpeta Destino")
        if directorio:
            self.entry_destino.delete(0, tk.END)
            self.entry_destino.insert(0, directorio)

    def _log(self, mensaje: str):
        """Agrega texto al ScrolledText en el hilo principal."""
        self.log_text.insert(tk.END, mensaje + "\n")
        self.log_text.see(tk.END)

    def _guardar_log(self):
        """Exporta el contenido del cuadro de log a un archivo .txt mediante filedialog."""
        contenido = self.log_text.get("1.0", tk.END).strip()
        if not contenido:
            messagebox.showinfo("Log Vacío", "No hay registros para guardar.")
            return

        filepath = filedialog.asksaveasfilename(
            title="Guardar Log de Operaciones",
            defaultextension=".txt",
            filetypes=[("Archivos de Texto", "*.txt"), ("Todos los Archivos", "*.*")]
        )

        if filepath:
            try:
                Path(filepath).write_text(contenido, encoding="utf-8")
                messagebox.showinfo("Éxito", f"Log guardado exitosamente en:\n{filepath}")
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo guardar el archivo de log:\n{e}")

    def _al_cerrar_ventana(self):
        """Maneja el cierre seguro de la aplicacion deteniendo hilos en segundo plano."""
        if self.ejecutando:
            if not messagebox.askyesno("Operación en Curso", "Hay un proceso ejecutándose. ¿Desea forzar la salida?"):
                return
        self.ejecutando = False
        self.root.destroy()

    def _cambiar_estado_botones(self, estado: str):
        """Habilita o deshabilita botones durante procesos pesados."""
        st = tk.DISABLED if estado in ("disabled", tk.DISABLED) else tk.NORMAL
        self.btn_analizar.config(state=st)
        self.btn_exam_origen.config(state=st)
        self.btn_exam_destino.config(state=st)

    # ---------------------------------------------------------
    # 1. METODO ANALIZAR CON THREADING
    # ---------------------------------------------------------
    def analizar(self):
        origen_str = self.entry_origen.get().strip()
        destino_str = self.entry_destino.get().strip()

        if not origen_str or not destino_str:
            messagebox.showwarning("Campos Requeridos", "Por favor seleccione las rutas de Origen y Destino.")
            return

        # Limpiar interfaz previa
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.log_text.delete("1.0", tk.END)

        # Deshabilitar botones y arrancar la barra de progreso indeterminada
        self._cambiar_estado_botones("disabled")
        self.btn_ejecutar.config(state="disabled")
        self.progressbar.config(mode="indeterminate")
        self.progressbar.start(10)

        # Parsear extensiones
        ext_raw = self.entry_extensiones.get().strip()
        lista_ext = [ext.strip() for ext in ext_raw.split(",") if ext.strip()] if ext_raw else None

        self.ejecutando = True
        self._log(f"🔎 Iniciando análisis en segundo plano de: {origen_str}")

        # PASO DE THREADING: Iniciar un nuevo hilo de ejecucion secundario para no congelar la GUI
        hilo_analisis = threading.Thread(
            target=self._hilo_tarea_analizar,
            args=(origen_str, destino_str, lista_ext, self.var_subcarpetas.get(), self.var_exif.get(), self.var_hash.get()),
            daemon=True
        )
        hilo_analisis.start()

    def _hilo_tarea_analizar(self, origen, destino, extensiones, subcarpetas, exif, hash_dups):
        """Tarea pesada de analisis que se ejecuta en el hilo secundario."""
        try:
            planes, lista_errores = generar_plan(
                origen=origen,
                destino_base=destino,
                extensiones=extensiones,
                incluir_subcarpetas=subcarpetas,
                usar_exif=exif,
                usar_hash_duplicados=hash_dups
            )

            if not self.ejecutando:
                return

            # Encolar resultado para ser procesado por el hilo principal de Tkinter
            self.cola_eventos.put(('FIN_ANALISIS', (planes, lista_errores, None)))

        except Exception as e:
            if self.ejecutando:
                self.cola_eventos.put(('FIN_ANALISIS', ([], [], e)))

    def _finalizar_analizar_gui(self, planes: List[Dict[str, Any]], lista_errores: List[Dict[str, Any]], error_fatal: Exception):
        """Metodo invocado en el Hilo Principal para volcar los resultados en los widgets."""
        self.progressbar.stop()
        self._cambiar_estado_botones("normal")
        self.ejecutando = False

        if error_fatal:
            messagebox.showerror("Error de Análisis", str(error_fatal))
            self._log(f"❌ ERROR EN ANALISIS: {error_fatal}")
            return

        self.planes_actuales = planes

        # Llenar la tabla Treeview
        for p in planes:
            accion_str = p['accion'].upper()
            fecha_str = str(p['fecha']) if p['fecha'] else "SIN FECHA"
            self.tree.insert(
                "",
                "end",
                values=(p['origen'].name, accion_str, str(p['destino']), fecha_str),
                tags=(accion_str,)
            )

        # Notificar errores individuales
        if lista_errores:
            for err in lista_errores:
                arch_path = err['archivo']
                msg = err['error']
                self._log(f"⚠️ Error en '{arch_path.name}': {msg}")
                self.tree.insert(
                    "",
                    "end",
                    values=(arch_path.name, "ERROR", msg, "N/A"),
                    tags=("ERROR",)
                )

        total_mov = sum(1 for p in planes if p['accion'] == 'mover')
        total_dup = sum(1 for p in planes if p['accion'] == 'duplicado')
        self._log(f"✅ Análisis completado. Planes: {len(planes)} (A mover: {total_mov} | Duplicados: {total_dup})")

        if planes:
            self.btn_ejecutar.config(state="normal")
        else:
            self._log("ℹ️ No se encontraron archivos para procesar.")

    # ---------------------------------------------------------
    # 2. METODO EJECUTAR CON THREADING Y PROGRESSBAR DETERMINADA
    # ---------------------------------------------------------
    def ejecutar(self):
        if not self.planes_actuales:
            messagebox.showinfo("Sin Planes", "No hay ningún plan cargado para ejecutar.")
            return

        total_mov = sum(1 for p in self.planes_actuales if p['accion'] == 'mover')
        total_dup = sum(1 for p in self.planes_actuales if p['accion'] == 'duplicado')

        # Confirmacion previa con desglose
        confirmacion = messagebox.askyesno(
            "Confirmar Operación",
            f"¿Desea proceder a organizar los archivos en disco?\n\n"
            f"• Archivos a mover: {total_mov}\n"
            f"• Archivos duplicados: {total_dup}\n"
            f"• Total de operaciones: {len(self.planes_actuales)}"
        )

        if not confirmacion:
            self._log("ℹ️ Operación cancelada por el usuario.")
            return

        total_archivos = len(self.planes_actuales)
        self.progressbar.config(mode="determinate", maximum=total_archivos, value=0)

        self._cambiar_estado_botones("disabled")
        self.btn_ejecutar.config(state="disabled")

        self.ejecutando = True
        self._log("\n🚀 Iniciando movimiento de archivos en segundo plano...")

        # PASO DE THREADING: Iniciar un nuevo hilo secundario para el movimiento fisico en disco
        hilo_ejecucion = threading.Thread(
            target=self._hilo_tarea_ejecutar,
            args=(self.planes_actuales,),
            daemon=True
        )
        hilo_ejecucion.start()

    def _hilo_tarea_ejecutar(self, planes: List[Dict[str, Any]]):
        """Tarea de movimiento de archivos ejecutada en segundo plano."""
        exitos = 0
        errores = 0

        for i, plan in enumerate(planes, start=1):
            if not self.ejecutando:
                break

            origen: Path = plan['origen']
            destino: Path = plan['destino']
            accion: str = plan['accion'].lower()

            msg_log = ""

            try:
                if not origen.exists():
                    raise FileNotFoundError(f"El archivo origen no existe: {origen.name}")

                destino.parent.mkdir(parents=True, exist_ok=True)
                destino_final = destino
                if destino_final.exists():
                    destino_final = generar_nombre_unico(destino, nombres_reservados=set())

                shutil.move(str(origen), str(destino_final))
                exitos += 1
                msg_log = f"[{i}/{len(planes)}] OK [{accion.upper()}]: '{origen.name}' -> '{destino_final}'"

            except Exception as e:
                errores += 1
                msg_log = f"[{i}/{len(planes)}] ERROR en '{origen.name}': {e}"

            # Enviar evento de progreso al hilo principal a traves de la cola
            self.cola_eventos.put(('PROGRESO_EJECUCION', (i, msg_log)))

        # Al finalizar todo el recorrido, notificar finalizacion
        if self.ejecutando:
            self.cola_eventos.put(('FIN_EJECUCION', (exitos, errores)))

    def _actualizar_progreso_gui(self, paso_actual: int, mensaje: str):
        """Callback ejecutado en Hilo Principal para refrescar la barra e historial."""
        self.progressbar.config(value=paso_actual)
        self._log(mensaje)

    def _finalizar_ejecutar_gui(self, exitos: int, errores: int):
        """Metodo invocado en Hilo Principal al culminar la ejecucion."""
        self._cambiar_estado_botones("normal")
        self.ejecutando = False

        self._log("=" * 80)
        self._log(f"INFORME FINAL: Operaciones exitosas: {exitos} | Errores: {errores}")
        self._log("=" * 80)

        messagebox.showinfo(
            "Proceso Concluido",
            f"Organización finalizada.\n\n• Operaciones exitosas: {exitos}\n• Errores: {errores}"
        )

        self.planes_actuales = []


def main():
    root = tk.Tk()
    app = App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
