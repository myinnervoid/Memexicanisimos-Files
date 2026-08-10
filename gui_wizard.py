#!/usr/bin/env python3
"""
Modulo gui_wizard.py - Ventana de Asistente (Wizard) en 4 Pasos con Tkinter y Multihilo (Threading)
para organizacion de archivos con opciones avanzadas de estructura, copia/movimiento y cancelacion.
"""

import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox, simpledialog
import re
import threading
import queue
import os
import shutil
import json
from datetime import date

from pathlib import Path
from typing import Dict, List, Any

from core import (
    generar_plan, generar_plan_con_estructura, generar_ruta_destino,
    RutaNoValidaError, generar_nombre_unico, ejecutar_plan_con_modo,
    renombrar_archivo, limpiar_carpetas_vacias, analizar_estructura_destino,
    guardar_estructura_como_perfil, deshacer_n_operaciones, obtener_historial_undo,
    limpiar_metadatos_audio, clonar_carpeta, clonar_disco, detectar_carpetas_usuario,
    detectar_dispositivos_multimedia
)


class ToolTip:
    """Clase auxiliar para crear mensajes flotantes (Tooltips) de ayuda en widgets de Tkinter."""
    def __init__(self, widget: tk.Widget, texto: str):
        self.widget = widget
        self.texto = texto
        self.tip_window = None

        self.widget.bind("<Enter>", self.mostrar_tip)
        self.widget.bind("<Leave>", self.ocultar_tip)

    def mostrar_tip(self, event=None):
        if self.tip_window or not self.texto:
            return
        x, y, cx, cy = self.widget.bbox("insert") if hasattr(self.widget, "bbox") and self.widget.bbox("insert") else (0, 0, 0, 0)
        x = x + self.widget.winfo_rootx() + 25
        y = y + self.widget.winfo_rooty() + 20

        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")

        label = tk.Label(
            tw,
            text=self.texto,
            justify=tk.LEFT,
            background="#FFFFE1",
            relief=tk.SOLID,
            borderwidth=1,
            font=("tahoma", "8", "normal"),
            padx=5,
            pady=3
        )
        label.pack(ipadx=1)

    def ocultar_tip(self, event=None):
        tw = self.tip_window
        self.tip_window = None
        if tw:
            tw.destroy()


class WizardApp:

    CATEGORIAS_EXT = {
        "Documentos": ["pdf", "docx", "txt", "xlsx", "pptx", "odt"],
        "Imagen": ["jpg", "jpeg", "png", "gif", "bmp", "tiff", "svg"],
        "Audio": ["mp3", "wav", "flac", "aac"],
        "Video": ["mp4", "avi", "mkv", "mov", "wmv"],
        "Código": ["py", "js", "html", "css", "java", "c", "cpp", "go", "rs"],
        "Comprimidos": ["zip", "rar", "7z", "tar", "gz"]
    }

    CONFIG_FILE = os.path.expanduser("~/.organizador_config.json")
    PERFILES_FILE = os.path.expanduser("~/.organizador_perfiles.json")

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Memexicanisimos Files v1.0 — Gestión y Respaldo de Archivos")
        self.root.geometry("900x720")
        self.root.minsize(800, 600)
        self.root.protocol("WM_DELETE_WINDOW", self._al_cerrar_ventana)

        try:
            temp_icon = tk.PhotoImage(width=16, height=16)
            self.root.iconphoto(True, temp_icon)
        except Exception:
            pass

        # Estado del paso actual (1 a 4)
        self.paso_actual = 1

        # Variables Paso 1
        self.origen = ""
        self.destino = ""
        self.var_modo = tk.StringVar(value="Copiar")

        # Variables Paso 2 (Filtros)
        self.ext_adicionales: List[str] = []
        self.filtros: Dict[str, Any] = {}

        # Variables Paso 3 (Estructura de organización)
        self.var_criterio_primario = tk.StringVar(value="Fecha")
        self.var_usar_secundario = tk.BooleanVar(value=True)
        self.var_criterio_secundario = tk.StringVar(value="Tipo de archivo")

        self.var_formato_fecha_combo = tk.StringVar(value="YYYY/MM")
        self.var_formato_fecha_custom = tk.StringVar(value="")
        self.var_org_tipo = tk.StringVar(value="extension")
        self.var_org_nombre = tk.StringVar(value="primera_letra")
        self.var_fuente_fecha = tk.StringVar(value="mtime")  # 'mtime' o 'ctime'

        self.estructura: Dict[str, Any] = {}

        # Variables Paso 2 (Filtros avanzados)
        self.var_tamano_min = tk.StringVar(value="")
        self.var_tamano_max = tk.StringVar(value="")
        self.var_dias_antiguedad = tk.IntVar(value=0)
        self.var_incluir_ocultos = tk.BooleanVar(value=False)
        self.var_patron_regex = tk.StringVar(value="")
        self.var_usar_creacion_filtro = tk.BooleanVar(value=False)

        # Variables Paso 3 (Renombrado de archivos)
        self.var_activar_renombrado = tk.BooleanVar(value=False)
        self.var_plantilla_nombre = tk.StringVar(value="{nombre}.{ext}")
        self.var_limpiar_metadatos_audio = tk.BooleanVar(value=False)

        # Variables Ejecucion (Limpieza post-procesamiento)
        self.var_limpiar_origen = tk.BooleanVar(value=False)
        self.var_limpiar_destino = tk.BooleanVar(value=False)

        # Variables Paso 4 (Planes y ejecución)
        self.planes_actuales: List[Dict[str, Any]] = []
        self.ejecutando = False
        self.cancelar = False
        self.cola_eventos = queue.Queue()

        self._crear_interfaz()
        self._cargar_configuracion()
        self._actualizar_estado_paso()

        self.root.after(100, self._procesar_cola_eventos)

    def _cargar_configuracion(self):
        if not os.path.exists(self.CONFIG_FILE):
            return

        try:
            with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                ultima_ruta = data.get("ultima_carpeta_origen", "").strip()

                if ultima_ruta:
                    p = Path(ultima_ruta)
                    if p.exists() and p.is_dir():
                        self.entry_origen.delete(0, tk.END)
                        self.entry_origen.insert(0, str(p))
                        self._validar_rutas_paso1()
        except Exception:
            pass

    def _guardar_configuracion(self):
        ruta_origen = self.entry_origen.get().strip()
        config = {
            "ultima_carpeta_origen": ruta_origen
        }
        try:
            with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _crear_menu(self):
        menubar = tk.Menu(self.root)
        
        menu_perfiles = tk.Menu(menubar, tearoff=0)
        menu_perfiles.add_command(label="💾 Guardar perfil actual...", command=self._guardar_perfil)
        menu_perfiles.add_command(label="📂 Cargar perfil guardado...", command=self._cargar_perfil)
        
        menu_undo = tk.Menu(menubar, tearoff=0)
        menu_undo.add_command(label="↩️ Deshacer última operación", command=self._dialogo_deshacer)
        menu_undo.add_command(label="📜 Historial de operaciones...", command=self._abrir_historial_undo)

        menubar.add_cascade(label="Perfiles", menu=menu_perfiles)
        menubar.add_cascade(label="Deshacer / Undo", menu=menu_undo)
        self.root.config(menu=menubar)

    def _obtener_perfiles_guardados(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.PERFILES_FILE):
            return []
        try:
            with open(self.PERFILES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _guardar_perfiles_disco(self, perfiles: List[Dict[str, Any]]):
        try:
            with open(self.PERFILES_FILE, "w", encoding="utf-8") as f:
                json.dump(perfiles, f, ensure_ascii=False, indent=2)
        except Exception as e:
            messagebox.showerror("Error al Guardar Perfiles", f"No se pudieron guardar los perfiles en disco:\n{e}")

    def _guardar_perfil(self):
        nombre_perfil = simpledialog.askstring(
            "Guardar Perfil de Configuración",
            "Escriba un nombre para identificar este perfil:"
        )
        if not nombre_perfil or not nombre_perfil.strip():
            return

        nombre_perfil = nombre_perfil.strip()

        # Guardar estados actuales de todos los pasos
        self._guardar_filtros_paso2()
        self._guardar_estructura_paso3()

        perfil_datos = {
            "nombre": nombre_perfil,
            "origen": self.entry_origen.get().strip(),
            "destino": self.entry_destino.get().strip(),
            "modo": self.var_modo.get(),
            "filtros": dict(self.filtros),
            "estructura": dict(self.estructura),
            "ext_adicionales": list(self.ext_adicionales)
        }

        perfiles = self._obtener_perfiles_guardados()
        # Reemplazar si ya existe un perfil con el mismo nombre
        perfiles = [p for p in perfiles if p.get("nombre") != nombre_perfil]
        perfiles.append(perfil_datos)

        self._guardar_perfiles_disco(perfiles)
        messagebox.showinfo("Perfil Guardado", f"El perfil '{nombre_perfil}' ha sido guardado exitosamente.")

    def _cargar_perfil(self):
        perfiles = self._obtener_perfiles_guardados()
        if not perfiles:
            messagebox.showinfo("Sin Perfiles", "No se encontraron perfiles guardados previamente.")
            return

        dlg_perfil = tk.Toplevel(self.root)
        dlg_perfil.title("Cargar Perfil Guardado")
        dlg_perfil.geometry("400x250")
        dlg_perfil.transient(self.root)
        dlg_perfil.grab_set()

        ttk.Label(dlg_perfil, text="Seleccione el perfil a cargar:", font=("Helvetica", 10, "bold")).pack(anchor="w", padx=15, pady=(15, 5))

        nombres_perfiles = [p["nombre"] for p in perfiles]
        var_perfil_sel = tk.StringVar(value=nombres_perfiles[0])

        cb_perfiles = ttk.Combobox(dlg_perfil, textvariable=var_perfil_sel, values=nombres_perfiles, state="readonly")
        cb_perfiles.pack(fill="x", padx=15, pady=5)

        lbl_info_perfil = ttk.Label(dlg_perfil, text="", font=("Helvetica", 9, "italic"), foreground="#444444")
        lbl_info_perfil.pack(anchor="w", padx=15, pady=5)

        def _al_seleccionar_cb(event=None):
            p_found = next((p for p in perfiles if p["nombre"] == var_perfil_sel.get()), None)
            if p_found:
                lbl_info_perfil.config(
                    text=f"Modo: {p_found.get('modo', 'Copiar')}\n"
                         f"Origen: {p_found.get('origen', '-')}\n"
                         f"Destino: {p_found.get('destino', '-')}"
                )

        cb_perfiles.bind("<<ComboboxSelected>>", _al_seleccionar_cb)
        _al_seleccionar_cb()

        def _confirmar_carga():
            p_found = next((p for p in perfiles if p["nombre"] == var_perfil_sel.get()), None)
            if p_found:
                self._aplicar_perfil(p_found)
                dlg_perfil.destroy()
                messagebox.showinfo("Perfil Cargado", f"El perfil '{p_found['nombre']}' se ha cargado correctamente.")

        btn_box = ttk.Frame(dlg_perfil)
        btn_box.pack(fill="x", padx=15, pady=15, side="bottom")

        ttk.Button(btn_box, text="Cancelar", command=dlg_perfil.destroy).pack(side="left")
        ttk.Button(btn_box, text="Cargar Perfil", command=_confirmar_carga).pack(side="right")

    def _aplicar_perfil(self, perfil: Dict[str, Any]):
        # 1. Cargar Paso 1 (Rutas y Modo)
        orig = perfil.get("origen", "")
        dest = perfil.get("destino", "")

        advertencias_rutas = []
        p_orig = Path(orig) if orig else None
        p_dest = Path(dest) if dest else None

        self.entry_origen.delete(0, tk.END)
        if p_orig and p_orig.exists() and p_orig.is_dir():
            self.entry_origen.insert(0, orig)
        else:
            if orig:
                advertencias_rutas.append(f"La carpeta origen del perfil '{orig}' ya no existe.")

        self.entry_destino.delete(0, tk.END)
        if p_dest and p_dest.exists() and p_dest.is_dir():
            self.entry_destino.insert(0, dest)
        else:
            if dest:
                advertencias_rutas.append(f"La carpeta destino del perfil '{dest}' ya no existe.")

        self.var_modo.set(perfil.get("modo", "Copiar"))
        self._al_cambiar_modo()
        self._validar_rutas_paso1()

        # 2. Cargar Paso 2 (Filtros)
        filtros_p = perfil.get("filtros", {})
        self.var_cat_todos.set(filtros_p.get("todos", True))

        cats_p = filtros_p.get("categorias", [])
        for cat_name, var_b in self.vars_categorias.items():
            var_b.set(cat_name in cats_p)

        self.ext_adicionales = list(perfil.get("ext_adicionales", []))
        self._actualizar_lbl_ext_adicionales()

        self.var_subcarpetas.set(filtros_p.get("incluir_subcarpetas", True))
        self.var_exif.set(filtros_p.get("usar_exif", True))
        self.var_hash.set(filtros_p.get("usar_hash", False))

        # Restaurar filtros avanzados del perfil
        def _bytes_a_mb(val) -> str:
            if val is None:
                return ""
            try:
                return str(round(val / (1024 * 1024), 3))
            except Exception:
                return ""

        self.var_tamano_min.set(_bytes_a_mb(filtros_p.get('tamano_min_bytes')))
        self.var_tamano_max.set(_bytes_a_mb(filtros_p.get('tamano_max_bytes')))
        self.var_dias_antiguedad.set(filtros_p.get('dias_antiguedad') or 0)
        self.var_incluir_ocultos.set(filtros_p.get('incluir_ocultos', False))
        self.var_patron_regex.set(filtros_p.get('patron_regex') or "")
        self.var_usar_creacion_filtro.set(filtros_p.get('usar_creacion_filtro', False))
        self.var_limpiar_origen.set(filtros_p.get('limpiar_origen', False))
        self.var_limpiar_destino.set(filtros_p.get('limpiar_destino', False))

        self._guardar_filtros_paso2()

        # 3. Cargar Paso 3 (Estructura)
        est_p = perfil.get("estructura", {})
        mapa_crit_inv = {
            'fecha': 'Fecha',
            'tipo': 'Tipo de archivo',
            'nombre': 'Nombre',
            'ninguno': 'Ninguno'
        }
        crit_p_str = mapa_crit_inv.get(est_p.get("criterio_primario", "fecha"), "Fecha")
        self.var_criterio_primario.set(crit_p_str)

        cs_val = est_p.get("criterio_secundario")
        if cs_val and cs_val != "ninguno":
            self.var_usar_secundario.set(True)
            self.var_criterio_secundario.set(mapa_crit_inv.get(cs_val, "Tipo de archivo"))
        else:
            self.var_usar_secundario.set(False)

        fmt = est_p.get("formato_fecha", "{YYYY}/{MM}")
        mapa_fmt_inv = {
            "{YYYY}/{MM}": "YYYY/MM",
            "{YYYY}-{MM}": "YYYY-MM",
            "{YYYY}/{MM}/{DD}": "YYYY/MM/DD",
            "{YYYY}-{MM}-{DD}": "YYYY-MM-DD",
            "{MM}/{YYYY}": "MM/YYYY",
            "{MES_NOMBRE} {YYYY}": "MMMM YYYY",
            "{MES_ABR} {YYYY}": "MMM YYYY",
            "{DD}/{MM}/{YYYY}": "DD/MM/YYYY"
        }
        if fmt in mapa_fmt_inv:
            self.var_formato_fecha_combo.set(mapa_fmt_inv[fmt])
            self.var_formato_fecha_custom.set("")
        else:
            self.var_formato_fecha_custom.set(fmt)

        self.var_org_tipo.set(est_p.get("organizacion_tipo", "extension"))
        self.var_org_nombre.set(est_p.get("organizacion_nombre", "primera_letra"))
        self.var_fuente_fecha.set("ctime" if est_p.get("usar_fecha_creacion", False) else "mtime")

        # Restaurar configuración de renombrado del perfil
        self.var_activar_renombrado.set(est_p.get('activar_renombrado', False))
        self.var_plantilla_nombre.set(est_p.get('plantilla_nombre') or "{nombre}.{ext}")
        self._al_cambiar_renombrado()

        self._al_cambiar_criterios_paso3()
        self._guardar_estructura_paso3()

        if advertencias_rutas:
            messagebox.showwarning("Advertencia de Rutas del Perfil", "\n".join(advertencias_rutas) + "\n\nSe han dejado vacíos los campos de ruta no válidos.")

    def _crear_interfaz(self):
        style = ttk.Style()
        style.theme_use("clam")

        COLOR_BG = "#F4F6FF"
        COLOR_PANEL = "#EAF0F8"
        style.configure("TFrame", background=COLOR_BG)
        style.configure("TLabel", background=COLOR_BG, foreground="#2C3E50")
        style.configure("TLabelframe", background=COLOR_BG, foreground="#1A252F")
        style.configure("TLabelframe.Label", background=COLOR_BG, foreground="#1A252F", font=("Helvetica", 9, "bold"))
        style.configure("TCheckbutton", background=COLOR_BG, foreground="#2C3E50")
        style.configure("TRadiobutton", background=COLOR_BG, foreground="#2C3E50")
        style.configure("Treeview", background="#FAFBFF", fieldbackground="#FAFBFF", foreground="#2C3E50")
        style.configure("Treeview.Heading", background="#D6E4F0", foreground="#1A252F", font=("Helvetica", 9, "bold"))
        style.map("Treeview", background=[("selected", "#AED6F1")])
        style.map("TButton", background=[("active", "#D6EAF8")])
        self.root.configure(bg=COLOR_BG)

        self._crear_menu()

        # ---------------------------------------------------------
        # 1. FRAME SUPERIOR (Encabezado y Barra de Progreso Global)
        # ---------------------------------------------------------
        self.frame_top = ttk.Frame(self.root, padding=15)
        self.frame_top.pack(fill="x")

        self.lbl_paso = ttk.Label(
            self.frame_top,
            text="Memexicanisimos Files v1.0 — Paso 1 de 5: Selección de carpetas y dispositivos",
            font=("Helvetica", 13, "bold")
        )
        self.lbl_paso.pack(anchor="w", pady=(0, 4))

        self.lbl_archivo_actual = ttk.Label(
            self.frame_top,
            text="",
            font=("Helvetica", 9, "italic"),
            foreground="#333333"
        )
        self.lbl_archivo_actual.pack(anchor="w", pady=(0, 4))

        self.progressbar_global = ttk.Progressbar(
            self.frame_top,
            orient="horizontal",
            mode="determinate",
            maximum=100
        )
        self.progressbar_global.pack(fill="x")

        ttk.Separator(self.root, orient="horizontal").pack(fill="x", padx=10, pady=5)

        # ---------------------------------------------------------
        # 2. FRAME CENTRAL CONTENEDOR
        # ---------------------------------------------------------
        self.container = ttk.Frame(self.root, padding=15)
        self.container.pack(fill="both", expand=True)

        self.frame_paso1 = ttk.Frame(self.container)
        self.frame_paso2 = ttk.Frame(self.container)
        self.frame_paso3 = ttk.Frame(self.container)
        self.frame_paso4 = ttk.Frame(self.container)
        self.frame_paso5 = ttk.Frame(self.container)

        self._construir_paso1()
        self._construir_paso2()
        self._construir_paso3()
        self._construir_paso4()
        self._construir_paso5()

        # ---------------------------------------------------------
        # 3. FRAME INFERIOR (Botones de Navegación)
        # ---------------------------------------------------------
        ttk.Separator(self.root, orient="horizontal").pack(fill="x", padx=10, pady=5)

        self.frame_bot = ttk.Frame(self.root, padding=10)
        self.frame_bot.pack(fill="x")

        self.btn_cancelar = ttk.Button(
            self.frame_bot,
            text="Cancelar",
            command=self._cancelar
        )
        self.btn_cancelar.pack(side="left", padx=5)

        self.btn_reiniciar = ttk.Button(
            self.frame_bot,
            text="🔄 Volver al inicio",
            command=self._reiniciar_asistente
        )

        self.btn_ejecutar = ttk.Button(
            self.frame_bot,
            text="🚀 Ejecutar",
            command=self._iniciar_ejecucion_hilo
        )

        self.btn_siguiente = ttk.Button(
            self.frame_bot,
            text="Siguiente ▶",
            command=self._siguiente
        )
        self.btn_siguiente.pack(side="right", padx=5)

        self.btn_anterior = ttk.Button(
            self.frame_bot,
            text="◀ Anterior",
            command=self._anterior
        )
        self.btn_anterior.pack(side="right", padx=5)

    # ---------------------------------------------------------
    # CONSTRUCCIÓN DEL PASO 1 (CARPETAS Y MODO)
    # ---------------------------------------------------------
    def _construir_paso1(self):
        ttk.Label(
            self.frame_paso1,
            text="Seleccione las carpetas de origen, destino y el modo de operación:",
            font=("Helvetica", 10, "bold")
        ).pack(anchor="w", pady=(0, 15))

        grid_frame = ttk.Frame(self.frame_paso1)
        grid_frame.pack(fill="x", pady=5)

        ttk.Label(grid_frame, text="Carpeta de origen:").grid(row=0, column=0, sticky="w", pady=5)
        self.entry_origen = ttk.Entry(grid_frame, width=50)
        self.entry_origen.grid(row=0, column=1, padx=5, sticky="ew")
        self.entry_origen.bind("<KeyRelease>", lambda e: self._validar_rutas_paso1())
        ToolTip(self.entry_origen, "Ruta del directorio fuente de donde se leerán los archivos.")

        btn_exam_orig = ttk.Button(grid_frame, text="Examinar...", command=self._examinar_origen)
        btn_exam_orig.grid(row=0, column=2, padx=5)

        ttk.Label(grid_frame, text="Carpeta de destino:").grid(row=1, column=0, sticky="w", pady=5)
        self.entry_destino = ttk.Entry(grid_frame, width=50)
        self.entry_destino.grid(row=1, column=1, padx=5, sticky="ew")
        self.entry_destino.bind("<KeyRelease>", lambda e: self._validar_rutas_paso1())
        ToolTip(self.entry_destino, "Directorio raíz donde se creará la nueva estructura de carpetas.")

        btn_exam_dest = ttk.Button(grid_frame, text="Examinar...", command=self._examinar_destino)
        btn_exam_dest.grid(row=1, column=2, padx=5)

        grid_frame.columnconfigure(1, weight=1)

        frame_det_btns = ttk.Frame(self.frame_paso1)
        frame_det_btns.pack(anchor="w", pady=10)

        btn_extraible = ttk.Button(
            frame_det_btns,
            text="🔍 Detectar unidad extraíble",
            command=self._detectar_unidad_extraible
        )
        btn_extraible.pack(side="left", padx=(0, 5))

        btn_media_dev = ttk.Button(
            frame_det_btns,
            text="📷 Detectar cámara / celular MTP",
            command=self._detectar_dispositivos_multimedia_gui
        )
        btn_media_dev.pack(side="left", padx=5)
        ToolTip(btn_media_dev, "Escanea teléfonos Android (MTP), cámaras y dispositivos de medios montados.")

        frame_modo = ttk.LabelFrame(self.frame_paso1, text=" Modo de operación ", padding=10)
        frame_modo.pack(fill="x", pady=10)

        rb_copiar = ttk.Radiobutton(
            frame_modo, text="Copiar archivos", value="Copiar",
            variable=self.var_modo, command=self._al_cambiar_modo
        )
        rb_copiar.pack(anchor="w", pady=2)

        rb_mover = ttk.Radiobutton(
            frame_modo, text="Mover archivos", value="Mover",
            variable=self.var_modo, command=self._al_cambiar_modo
        )
        rb_mover.pack(anchor="w", pady=2)

        self.lbl_precaucion = ttk.Label(
            frame_modo,
            text="⚠️ PRECAUCIÓN: Al seleccionar 'Mover', los archivos originales serán eliminados del directorio de origen.",
            font=("Helvetica", 9, "bold"), foreground="red"
        )

    # ---------------------------------------------------------
    # CONSTRUCCIÓN DEL PASO 2 (FILTROS DE ARCHIVOS)
    # ---------------------------------------------------------
    def _construir_paso2(self):
        ttk.Label(
            self.frame_paso2,
            text="Filtros por tipo de archivo y opciones de procesamiento:",
            font=("Helvetica", 10, "bold")
        ).pack(anchor="w", pady=(0, 10))

        lf_cats = ttk.LabelFrame(self.frame_paso2, text=" Categorías de archivos ", padding=10)
        lf_cats.pack(fill="x", pady=5)

        self.var_cat_todos = tk.BooleanVar(value=True)
        self.vars_categorias: Dict[str, tk.BooleanVar] = {}

        chk_todos = ttk.Checkbutton(
            lf_cats, text="Todos (sin filtro)", variable=self.var_cat_todos, command=self._al_cambiar_cat_todos
        )
        chk_todos.pack(anchor="w", pady=3)

        ttk.Separator(lf_cats, orient="horizontal").pack(fill="x", pady=5)

        grid_cats = ttk.Frame(lf_cats)
        grid_cats.pack(fill="x")

        nombres_cats = list(self.CATEGORIAS_EXT.keys())
        for idx, cat_nombre in enumerate(nombres_cats):
            var_b = tk.BooleanVar(value=False)
            self.vars_categorias[cat_nombre] = var_b

            chk = ttk.Checkbutton(
                grid_cats, text=cat_nombre, variable=var_b, command=self._al_cambiar_cat_individual
            )
            col = idx % 3
            row = idx // 3
            chk.grid(row=row, column=col, sticky="w", padx=15, pady=3)

        frame_ext_add = ttk.Frame(self.frame_paso2, padding=5)
        frame_ext_add.pack(fill="x", pady=5)

        ttk.Label(frame_ext_add, text="Extensiones adicionales (sin punto, separadas por comas):").pack(anchor="w")

        frame_input_ext = ttk.Frame(frame_ext_add)
        frame_input_ext.pack(fill="x", pady=2)

        self.entry_ext_add = ttk.Entry(frame_input_ext)
        self.entry_ext_add.pack(side="left", fill="x", expand=True, padx=(0, 5))

        btn_add_ext = ttk.Button(frame_input_ext, text="Añadir +", command=self._agregar_extensiones_adicionales)
        btn_add_ext.pack(side="right")

        self.lbl_status_ext_add = ttk.Label(frame_ext_add, text="", font=("Helvetica", 9, "bold"))
        self.lbl_status_ext_add.pack(anchor="w", pady=(2, 0))

        self.lbl_ext_add_lista = ttk.Label(
            frame_ext_add, text="Extensiones personalizadas: Ninguna",
            font=("Helvetica", 9, "italic"), foreground="#555555"
        )
        self.lbl_ext_add_lista.pack(anchor="w", pady=(2, 0))

        lf_avanzadas = ttk.LabelFrame(self.frame_paso2, text=" Opciones avanzadas ", padding=10)
        lf_avanzadas.pack(fill="x", pady=10)

        self.var_subcarpetas = tk.BooleanVar(value=True)
        self.var_exif = tk.BooleanVar(value=True)
        self.var_hash = tk.BooleanVar(value=False)

        ttk.Checkbutton(lf_avanzadas, text="Incluir subcarpetas", variable=self.var_subcarpetas).pack(anchor="w", pady=2)
        ttk.Checkbutton(lf_avanzadas, text="Usar metadatos EXIF", variable=self.var_exif).pack(anchor="w", pady=2)
        ttk.Checkbutton(lf_avanzadas, text="Detección de duplicados por hash", variable=self.var_hash).pack(anchor="w", pady=2)
        ttk.Checkbutton(lf_avanzadas, text="Eliminar carpetas vacías del origen al mover", variable=self.var_limpiar_origen).pack(anchor="w", pady=2)
        ttk.Checkbutton(lf_avanzadas, text="Eliminar carpetas vacías del destino tras la operación", variable=self.var_limpiar_destino).pack(anchor="w", pady=2)

        # LabelFrame: Filtros avanzados de tamaño, fecha y nombre
        lf_filt_av = ttk.LabelFrame(self.frame_paso2, text=" Filtros avanzados de tamaño y fecha ", padding=10)
        lf_filt_av.pack(fill="x", pady=10)

        frame_tamanos = ttk.Frame(lf_filt_av)
        frame_tamanos.pack(fill="x", pady=3)

        ttk.Label(frame_tamanos, text="Tamaño mínimo (MB):").grid(row=0, column=0, sticky="w", padx=5, pady=2)
        entry_tmin = ttk.Entry(frame_tamanos, textvariable=self.var_tamano_min, width=10)
        entry_tmin.grid(row=0, column=1, padx=5, pady=2)
        ToolTip(entry_tmin, "Excluye archivos más pequeños que este valor en MB. Dejar vacío para sin límite.")

        ttk.Label(frame_tamanos, text="Tamaño máximo (MB):").grid(row=0, column=2, sticky="w", padx=15, pady=2)
        entry_tmax = ttk.Entry(frame_tamanos, textvariable=self.var_tamano_max, width=10)
        entry_tmax.grid(row=0, column=3, padx=5, pady=2)
        ToolTip(entry_tmax, "Excluye archivos más grandes que este valor en MB. Dejar vacío para sin límite.")

        frame_ant = ttk.Frame(lf_filt_av)
        frame_ant.pack(fill="x", pady=3)

        ttk.Label(frame_ant, text="Antigüedad máxima (días, 0 = sin límite):").pack(side="left", padx=5)
        spin_ant = ttk.Spinbox(frame_ant, from_=0, to=9999, textvariable=self.var_dias_antiguedad, width=8)
        spin_ant.pack(side="left", padx=5)
        ToolTip(spin_ant, "Solo incluir archivos modificados/creados en los últimos N días. 0 = todos.")

        chk_ctime_filt = ttk.Checkbutton(
            frame_ant,
            text="Usar fecha de creación (ctime) para filtro de antigüedad",
            variable=self.var_usar_creacion_filtro
        )
        chk_ctime_filt.pack(side="left", padx=15)
        ToolTip(chk_ctime_filt, "Si está marcado, usa st_ctime; si no, st_mtime (fecha de modificación).")

        frame_opc_filt = ttk.Frame(lf_filt_av)
        frame_opc_filt.pack(fill="x", pady=3)

        ttk.Checkbutton(
            frame_opc_filt,
            text="Incluir archivos ocultos (nombre empieza con '.')",
            variable=self.var_incluir_ocultos
        ).pack(anchor="w", padx=5)

        frame_regex = ttk.Frame(lf_filt_av)
        frame_regex.pack(fill="x", pady=(5, 2))

        ttk.Label(frame_regex, text="Patrón regex del nombre (opcional, AND con extensiones):").pack(anchor="w", padx=5)
        entry_regex = ttk.Entry(frame_regex, textvariable=self.var_patron_regex)
        entry_regex.pack(fill="x", padx=5, pady=2)
        ToolTip(
            entry_regex,
            "Expresión regular para filtrar archivos por nombre.\n"
            "Se combina con las extensiones seleccionadas (lógica AND).\n"
            "Ej: '^IMG_' solo incluye archivos cuyo nombre empieza con IMG_"
        )

    # ---------------------------------------------------------
    # CONSTRUCCIÓN DEL PASO 3 (NUEVO: ESTRUCTURA DE ORGANIZACIÓN)
    # ---------------------------------------------------------
    def _construir_paso3(self):
        ttk.Label(
            self.frame_paso3,
            text="Configure cómo se organizarán las subcarpetas de destino:",
            font=("Helvetica", 10, "bold")
        ).pack(anchor="w", pady=(0, 10))

        frame_criterios = ttk.Frame(self.frame_paso3)
        frame_criterios.pack(fill="x", pady=5)

        # 1. Criterio primario
        lf_primario = ttk.LabelFrame(frame_criterios, text=" Criterio primario ", padding=10)
        lf_primario.pack(side="left", fill="both", expand=True, padx=(0, 5))

        opciones_criterio = ['Fecha', 'Tipo de archivo', 'Nombre', 'Ninguno']
        self.cb_criterio_primario = ttk.Combobox(
            lf_primario, textvariable=self.var_criterio_primario, values=opciones_criterio, state="readonly"
        )
        self.cb_criterio_primario.pack(fill="x", pady=5)
        self.cb_criterio_primario.bind("<<ComboboxSelected>>", lambda e: self._al_cambiar_criterios_paso3())

        # 2. Criterio secundario
        lf_secundario = ttk.LabelFrame(frame_criterios, text=" Criterio secundario ", padding=10)
        lf_secundario.pack(side="right", fill="both", expand=True, padx=(5, 0))

        chk_sec = ttk.Checkbutton(
            lf_secundario, text="Activar nivel secundario",
            variable=self.var_usar_secundario, command=self._al_cambiar_criterios_paso3
        )
        chk_sec.pack(anchor="w", pady=(0, 5))

        opciones_sec = ['Fecha', 'Tipo de archivo', 'Nombre']
        self.cb_criterio_secundario = ttk.Combobox(
            lf_secundario, textvariable=self.var_criterio_secundario, values=opciones_sec, state="readonly"
        )
        self.cb_criterio_secundario.pack(fill="x", pady=5)
        self.cb_criterio_secundario.bind("<<ComboboxSelected>>", lambda e: self._al_cambiar_criterios_paso3())

        # 3. LabelFrame Formato de fecha (Empacado dinámicamente)
        self.lf_formato_fecha = ttk.LabelFrame(self.frame_paso3, text=" Formato de carpeta de fecha ", padding=10)

        frame_combo_f = ttk.Frame(self.lf_formato_fecha)
        frame_combo_f.pack(fill="x", pady=2)

        ttk.Label(frame_combo_f, text="Patrón predefinido:").pack(side="left")
        formatos_pred = ["YYYY/MM", "YYYY-MM", "YYYY/MM/DD", "YYYY-MM-DD", "MM/YYYY", "MMMM YYYY", "MMM YYYY", "DD/MM/YYYY"]
        self.cb_formato_fecha = ttk.Combobox(
            frame_combo_f, textvariable=self.var_formato_fecha_combo, values=formatos_pred, state="readonly", width=25
        )
        self.cb_formato_fecha.pack(side="left", padx=10)
        self.cb_formato_fecha.bind("<<ComboboxSelected>>", lambda e: self._al_cambiar_formato_fecha())

        frame_custom_f = ttk.Frame(self.lf_formato_fecha)
        frame_custom_f.pack(fill="x", pady=5)

        ttk.Label(frame_custom_f, text="Formato personalizado ({YYYY}, {MM}, {DD}, {MES_NOMBRE}, {MES_ABR}):").pack(anchor="w")
        self.entry_formato_custom = ttk.Entry(frame_custom_f, textvariable=self.var_formato_fecha_custom)
        self.entry_formato_custom.pack(fill="x", pady=2)
        self.entry_formato_custom.bind("<KeyRelease>", lambda e: self._al_cambiar_formato_fecha())

        self.lbl_ejemplo_fecha = ttk.Label(
            self.lf_formato_fecha, text="Ejemplo de ruta: 2024/07",
            font=("Helvetica", 9, "bold"), foreground="#0066CC"
        )
        self.lbl_ejemplo_fecha.pack(anchor="w", pady=(5, 0))

        # 4. LabelFrame Organización por tipo (Empacado dinámicamente)
        self.lf_org_tipo = ttk.LabelFrame(self.frame_paso3, text=" Organización por tipo de archivo ", padding=10)

        rb_tipo_ext = ttk.Radiobutton(
            self.lf_org_tipo, text="Extensión exacta (ej. jpg, pdf, py)",
            value="extension", variable=self.var_org_tipo
        )
        rb_tipo_ext.pack(anchor="w", pady=2)

        rb_tipo_cat = ttk.Radiobutton(
            self.lf_org_tipo, text="Categoría agrupada (ej. Imagen, Documentos, Código)",
            value="categoria", variable=self.var_org_tipo
        )
        rb_tipo_cat.pack(anchor="w", pady=2)

        # 5. LabelFrame Organización por nombre (Empacado dinámicamente)
        self.lf_org_nombre = ttk.LabelFrame(self.frame_paso3, text=" Organización por nombre ", padding=10)

        rb_nom_letra = ttk.Radiobutton(
            self.lf_org_nombre, text="Primera letra (A-Z)",
            value="primera_letra", variable=self.var_org_nombre
        )
        rb_nom_letra.pack(anchor="w", pady=2)

        rb_nom_comp = ttk.Radiobutton(
            self.lf_org_nombre, text="Nombre completo del archivo sin extensión",
            value="nombre_completo", variable=self.var_org_nombre
        )
        rb_nom_comp.pack(anchor="w", pady=2)

        # 6. LabelFrame Fuente de fecha (Empacado dinámicamente)
        self.lf_fuente_fecha = ttk.LabelFrame(self.frame_paso3, text=" Fuente de fecha del sistema (Fallback sin EXIF/Regex) ", padding=10)

        rb_mtime = ttk.Radiobutton(
            self.lf_fuente_fecha, text="Fecha de modificación (mtime)",
            value="mtime", variable=self.var_fuente_fecha,
            command=self._actualizar_visor_paso3
        )
        rb_mtime.pack(anchor="w", pady=2)

        rb_ctime = ttk.Radiobutton(
            self.lf_fuente_fecha, text="Fecha de creación del archivo (ctime)",
            value="ctime", variable=self.var_fuente_fecha,
            command=self._actualizar_visor_paso3
        )
        rb_ctime.pack(anchor="w", pady=2)

        # Configurar commands para radiobuttons de tipo y nombre
        rb_tipo_ext.config(command=self._actualizar_visor_paso3)
        rb_tipo_cat.config(command=self._actualizar_visor_paso3)
        rb_nom_letra.config(command=self._actualizar_visor_paso3)
        rb_nom_comp.config(command=self._actualizar_visor_paso3)

        # 7. LabelFrame Renombrado de archivos (siempre visible, controla su contenido)
        self.lf_renombrado = ttk.LabelFrame(self.frame_paso3, text=" Renombrado de archivos (opcional) ", padding=10)

        frame_rename_chk = ttk.Frame(self.lf_renombrado)
        frame_rename_chk.pack(fill="x", pady=2)

        chk_renombrar = ttk.Checkbutton(
            frame_rename_chk,
            text="Activar renombrado de archivos al copiar/mover",
            variable=self.var_activar_renombrado,
            command=self._al_cambiar_renombrado
        )
        chk_renombrar.pack(side="left")
        ToolTip(chk_renombrar, "Si está activo, los archivos destino se renombrarán usando la plantilla especificada.")

        frame_plantilla = ttk.Frame(self.lf_renombrado)
        frame_plantilla.pack(fill="x", pady=3)

        ttk.Label(frame_plantilla, text="Plantilla:").pack(side="left")
        self.entry_plantilla = ttk.Entry(frame_plantilla, textvariable=self.var_plantilla_nombre, width=38)
        self.entry_plantilla.pack(side="left", padx=5, fill="x", expand=True)
        self.entry_plantilla.bind("<KeyRelease>", lambda e: self._al_cambiar_renombrado())
        ttk.Checkbutton(
            self.lf_renombrado,
            text="🧹 Limpiar metadatos de audio sensibles (comentarios/GPS) antes de renombrar",
            variable=self.var_limpiar_metadatos_audio
        ).pack(anchor="w", padx=5, pady=(2, 0))

        ToolTip(
            self.entry_plantilla,
            "Placeholders estándar disponibles:\n"
            "  {nombre}       → Nombre sin extensión\n"
            "  {ext}          → Extensión sin punto (ej: jpg)\n"
            "  {fecha}        → Fecha formateada según el formato elegido\n"
            "  {contador:03d} → Contador secuencial con 3 dígitos (001, 002...)\n\n"
            "Placeholders de metadatos de audio (MP3, FLAC, M4A, OGG):\n"
            "  {artista}      → Artista de la canción\n"
            "  {album}        → Nombre del álbum\n"
            "  {titulo}       → Título del tema\n"
            "  {ano}          → Año de lanzamiento\n"
            "  {genero}       → Género musical\n"
            "  {caratula}     → 'si' o 'no' si posee álbum art\n\n"
            "Ejemplo de audio:\n"
            "  {artista}/{album}/{contador:02d} - {titulo}.{ext}"
        )

        self.lbl_plantilla_ejemplo = ttk.Label(
            self.lf_renombrado, text="Vista previa: mi_foto.jpg",
            font=("Helvetica", 9, "bold"), foreground="#0055AA"
        )
        self.lbl_plantilla_ejemplo.pack(anchor="w", pady=(2, 0), padx=5)

        self.lbl_plantilla_validacion = ttk.Label(
            self.lf_renombrado, text="",
            font=("Helvetica", 9), foreground="red"
        )
        self.lbl_plantilla_validacion.pack(anchor="w", padx=5)

        # 8. LabelFrame Visor de estructura en vivo
        self.lf_visor_estructura = ttk.LabelFrame(self.frame_paso3, text=" Vista previa de la estructura de destino: ", padding=10)
        self.lf_visor_estructura.pack(fill="both", expand=True, pady=8)

        self.tree_visor = ttk.Treeview(self.lf_visor_estructura, show="tree", selectmode="none", height=6)
        self.tree_visor.pack(fill="both", expand=True)

        # Configurar observaciones / traces de variables
        self.var_criterio_primario.trace_add("write", lambda *args: self._actualizar_visor_paso3())
        self.var_usar_secundario.trace_add("write", lambda *args: self._actualizar_visor_paso3())
        self.var_criterio_secundario.trace_add("write", lambda *args: self._actualizar_visor_paso3())
        self.var_formato_fecha_combo.trace_add("write", lambda *args: self._actualizar_visor_paso3())
        self.var_formato_fecha_custom.trace_add("write", lambda *args: self._actualizar_visor_paso3())
        self.var_org_tipo.trace_add("write", lambda *args: self._actualizar_visor_paso3())
        self.var_org_nombre.trace_add("write", lambda *args: self._actualizar_visor_paso3())
        self.var_fuente_fecha.trace_add("write", lambda *args: self._actualizar_visor_paso3())
        self.var_plantilla_nombre.trace_add("write", lambda *args: self._al_cambiar_renombrado())
        self.var_activar_renombrado.trace_add("write", lambda *args: self._al_cambiar_renombrado())

        self._al_cambiar_criterios_paso3()
        self._al_cambiar_renombrado()

    # ---------------------------------------------------------
    # CONSTRUCCIÓN DEL PASO 4 (PREVISUALIZACIÓN Y EJECUCIÓN)
    # ---------------------------------------------------------
    def _construir_paso4(self):
        self.lf_resumen = ttk.LabelFrame(self.frame_paso4, text=" Resumen de configuración ", padding=8)
        self.lf_resumen.pack(fill="x", pady=(0, 5))

        self.lbl_resumen_origen = ttk.Label(self.lf_resumen, text="Origen: -")
        self.lbl_resumen_origen.pack(anchor="w", pady=1)

        self.lbl_resumen_destino = ttk.Label(self.lf_resumen, text="Destino: -")
        self.lbl_resumen_destino.pack(anchor="w", pady=1)

        self.lbl_resumen_modo = ttk.Label(self.lf_resumen, text="Modo: -")
        self.lbl_resumen_modo.pack(anchor="w", pady=1)

        self.lbl_resumen_filtros = ttk.Label(self.lf_resumen, text="Filtros: -")
        self.lbl_resumen_filtros.pack(anchor="w", pady=1)

        self.lbl_resumen_estructura = ttk.Label(self.lf_resumen, text="Estructura: -")
        self.lbl_resumen_estructura.pack(anchor="w", pady=1)

        self.lbl_resumen_opciones = ttk.Label(self.lf_resumen, text="Subcarpetas: - | EXIF: - | Hash: -")
        self.lbl_resumen_opciones.pack(anchor="w", pady=1)

        frame_accion_paso4 = ttk.Frame(self.frame_paso4)
        frame_accion_paso4.pack(fill="x", pady=5)

        self.btn_analizar = ttk.Button(
            frame_accion_paso4,
            text="🔍 Analizar y previsualizar",
            command=self._analizar_paso4
        )
        self.btn_analizar.pack(side="left")

        btn_detect_dest = ttk.Button(
            frame_accion_paso4,
            text="🎯 Detectar estructura en destino",
            command=self._detectar_estructura_destino_gui
        )
        btn_detect_dest.pack(side="left", padx=5)

        btn_undo = ttk.Button(
            frame_accion_paso4,
            text="↩️ Deshacer",
            command=self._dialogo_deshacer
        )
        btn_undo.pack(side="right")

        self.lbl_estado_analisis = ttk.Label(
            frame_accion_paso4,
            text="",
            font=("Helvetica", 9, "bold"),
            foreground="#0066CC"
        )
        self.lbl_estado_analisis.pack(side="left", padx=10)

        paned = ttk.PanedWindow(self.frame_paso4, orient="vertical")
        paned.pack(fill="both", expand=True, pady=5)

        frame_tree_container = ttk.Frame(paned)
        paned.add(frame_tree_container, weight=1)

        columnas = ("archivo", "accion", "destino", "fecha")
        self.tree = ttk.Treeview(frame_tree_container, columns=columnas, show="headings", selectmode="browse")

        self.tree.heading("archivo", text="Archivo")
        self.tree.heading("accion", text="Acción")
        self.tree.heading("destino", text="Destino")
        self.tree.heading("fecha", text="Fecha")

        self.tree.column("archivo", width=180, anchor="w")
        self.tree.column("accion", width=110, anchor="center")
        self.tree.column("destino", width=380, anchor="w")
        self.tree.column("fecha", width=110, anchor="center")

        scrollbar_tree = ttk.Scrollbar(frame_tree_container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar_tree.set)

        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar_tree.pack(side="right", fill="y")

        self.tree.tag_configure("MOVER", foreground="#006600")
        self.tree.tag_configure("DUPLICADO", foreground="#CC6600")
        self.tree.tag_configure("ERROR", foreground="#CC0000")

        frame_log_container = ttk.LabelFrame(paned, text=" Registro de Operaciones en Vivo (Log) ", padding=5)
        paned.add(frame_log_container, weight=1)

        self.log_text = scrolledtext.ScrolledText(frame_log_container, height=6, state="normal")
        self.log_text.pack(fill="both", expand=True)

    # ---------------------------------------------------------
    # CONSTRUCCIÓN DEL PASO 5 (NUEVO: RESPALDO Y CLONACIÓN)
    # ---------------------------------------------------------
    def _construir_paso5(self):
        ttk.Label(
            self.frame_paso5,
            text="Herramientas avanzadas de Respaldo y Clonación de Carpetas/Discos:",
            font=("Helvetica", 10, "bold")
        ).pack(anchor="w", pady=(0, 10))

        notebook_paso5 = ttk.Notebook(self.frame_paso5)
        notebook_paso5.pack(fill="both", expand=True)

        # Tab 1: Clonar Carpeta
        tab_carpeta = ttk.Frame(notebook_paso5, padding=10)
        notebook_paso5.add(tab_carpeta, text="📁 Clonar Carpeta")

        grid_c = ttk.Frame(tab_carpeta)
        grid_c.pack(fill="x", pady=5)

        ttk.Label(grid_c, text="Carpeta Origen:").grid(row=0, column=0, sticky="w", pady=5)
        self.entry_clone_orig = ttk.Entry(grid_c, width=45)
        self.entry_clone_orig.grid(row=0, column=1, padx=5, sticky="ew")
        btn_co = ttk.Button(grid_c, text="Examinar...", command=lambda: self._examinar_generico(self.entry_clone_orig))
        btn_co.grid(row=0, column=2, padx=5)

        ttk.Label(grid_c, text="Carpeta Destino:").grid(row=1, column=0, sticky="w", pady=5)
        self.entry_clone_dest = ttk.Entry(grid_c, width=45)
        self.entry_clone_dest.grid(row=1, column=1, padx=5, sticky="ew")
        btn_cd = ttk.Button(grid_c, text="Examinar...", command=lambda: self._examinar_generico(self.entry_clone_dest))
        btn_cd.grid(row=1, column=2, padx=5)
        grid_c.columnconfigure(1, weight=1)

        self.var_clone_inc = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            tab_carpeta,
            text="Modo Incremental (solo copiar archivos nuevos o modificados)",
            variable=self.var_clone_inc
        ).pack(anchor="w", pady=5)

        btn_ej_clone = ttk.Button(
            tab_carpeta,
            text="▶ Iniciar Clonación de Carpeta",
            command=self._ejecutar_clonacion_carpeta_gui
        )
        btn_ej_clone.pack(anchor="w", pady=5)

        self.frame_progreso_clonacion = ttk.Frame(tab_carpeta)
        self.frame_progreso_clonacion.pack(fill="x", pady=5)

        self.lbl_clon_porcentaje = ttk.Label(self.frame_progreso_clonacion, text="", font=("Helvetica", 14, "bold"), foreground="#0066CC")
        self.lbl_clon_porcentaje.pack(anchor="w")

        self.progressbar_clon = ttk.Progressbar(self.frame_progreso_clonacion, orient="horizontal", mode="determinate", maximum=100)
        self.progressbar_clon.pack(fill="x", pady=2)

        self.lbl_clon_info = ttk.Label(self.frame_progreso_clonacion, text="")
        self.lbl_clon_info.pack(anchor="w")

        self.lbl_clon_archivo = ttk.Label(self.frame_progreso_clonacion, text="", font=("Helvetica", 9, "italic"), foreground="#555555")
        self.lbl_clon_archivo.pack(anchor="w")

        self.btn_cancelar_clon = ttk.Button(self.frame_progreso_clonacion, text="⏹ Cancelar Clonación", command=self._cancelar_clonacion_gui)
        self.btn_cancelar_clon.pack(anchor="w", pady=5)
        self.frame_progreso_clonacion.pack_forget()

        # Tab 2: Respaldo de Usuario
        tab_user = ttk.Frame(notebook_paso5, padding=10)
        notebook_paso5.add(tab_user, text="👤 Respaldo de Usuario")

        ttk.Label(tab_user, text="Carpetas personales del sistema detectadas:").pack(anchor="w", pady=5)
        self.frame_user_check = ttk.Frame(tab_user)
        self.frame_user_check.pack(fill="x", pady=5)

        self.vars_carpetas_user: Dict[str, tk.BooleanVar] = {}
        carpetas_det = detectar_carpetas_usuario()
        for item in carpetas_det:
            var_b = tk.BooleanVar(value=True)
            self.vars_carpetas_user[item['ruta']] = var_b
            ttk.Checkbutton(
                self.frame_user_check,
                text=f"{item['nombre']} ({item['ruta']})",
                variable=var_b
            ).pack(anchor="w", pady=2)

        frame_dest_user = ttk.Frame(tab_user)
        frame_dest_user.pack(fill="x", pady=10)
        ttk.Label(frame_dest_user, text="Destino del respaldo:").pack(side="left")
        self.entry_user_dest = ttk.Entry(frame_dest_user, width=40)
        self.entry_user_dest.pack(side="left", padx=5, fill="x", expand=True)
        ttk.Button(frame_dest_user, text="Examinar...", command=lambda: self._examinar_generico(self.entry_user_dest)).pack(side="left")

        btn_ej_respaldo = ttk.Button(
            tab_user,
            text="🚀 Respaldar Carpetas Seleccionadas",
            command=self._ejecutar_respaldo_usuario_gui
        )
        btn_ej_respaldo.pack(anchor="w", pady=5)

        # Tab 3: Clonar Disco
        tab_disco = ttk.Frame(notebook_paso5, padding=10)
        notebook_paso5.add(tab_disco, text="💾 Clonar Disco (dd / ddrescue)")

        grid_d = ttk.Frame(tab_disco)
        grid_d.pack(fill="x", pady=5)

        ttk.Label(grid_d, text="Dispositivo Origen (ej: /dev/sdb):").grid(row=0, column=0, sticky="w", pady=5)
        self.entry_disk_orig = ttk.Entry(grid_d, width=30)
        self.entry_disk_orig.grid(row=0, column=1, padx=5, sticky="w")

        ttk.Label(grid_d, text="Dispositivo Destino (ej: /dev/sdc):").grid(row=1, column=0, sticky="w", pady=5)
        self.entry_disk_dest = ttk.Entry(grid_d, width=30)
        self.entry_disk_dest.grid(row=1, column=1, padx=5, sticky="w")

        self.var_ddrescue = tk.BooleanVar(value=False)
        self.var_check_md5 = tk.BooleanVar(value=True)

        ttk.Checkbutton(tab_disco, text="Usar 'ddrescue' (tolerante a sectores defectuosos)", variable=self.var_ddrescue).pack(anchor="w", pady=2)
        ttk.Checkbutton(tab_disco, text="Verificar Checksum MD5 post-clonación", variable=self.var_check_md5).pack(anchor="w", pady=2)

        ttk.Label(tab_disco, text="⚠️ ADVERTENCIA: La clonación de disco sobrescribirá todo el dispositivo destino. Requiere root/sudo.", foreground="red", font=("Helvetica", 9, "bold")).pack(anchor="w", pady=5)

        btn_ej_disco = ttk.Button(
            tab_disco,
            text="⚠️ Iniciar Clonación de Disco",
            command=self._ejecutar_clonacion_disco_gui
        )
        btn_ej_disco.pack(anchor="w", pady=5)

    # ---------------------------------------------------------
    # MANEJADORES EVENTOS PASO 3 (ESTRUCTURA)
    # ---------------------------------------------------------
    def _al_cambiar_criterios_paso3(self):
        crit_p = self.var_criterio_primario.get()
        crit_s = self.var_criterio_secundario.get() if self.var_usar_secundario.get() else None

        if crit_p == "Ninguno":
            self.var_usar_secundario.set(False)
            self.cb_criterio_secundario.config(state="disabled")
            crit_s = None
        else:
            self.cb_criterio_secundario.config(state="readonly" if self.var_usar_secundario.get() else "disabled")

        # Ocultar todos primero para reordenar dinámicamente
        self.lf_formato_fecha.pack_forget()
        self.lf_org_tipo.pack_forget()
        self.lf_org_nombre.pack_forget()
        self.lf_fuente_fecha.pack_forget()
        if hasattr(self, 'lf_renombrado'):
            self.lf_renombrado.pack_forget()

        # Visibilidad Formato Fecha
        if crit_p == "Fecha" or crit_s == "Fecha":
            self.lf_formato_fecha.pack(fill="x", pady=8)

        # Visibilidad Org Tipo
        if crit_p == "Tipo de archivo" or crit_s == "Tipo de archivo":
            self.lf_org_tipo.pack(fill="x", pady=5)

        # Visibilidad Org Nombre
        if crit_p == "Nombre" or crit_s == "Nombre":
            self.lf_org_nombre.pack(fill="x", pady=5)

        # Fuente de fecha siempre visible
        self.lf_fuente_fecha.pack(fill="x", pady=5)

        # Renombrado siempre visible al final (antes del visor)
        if hasattr(self, 'lf_renombrado'):
            self.lf_renombrado.pack(fill="x", pady=5)

        self._al_cambiar_formato_fecha()

    def _al_cambiar_formato_fecha(self):
        custom = self.var_formato_fecha_custom.get().strip()
        patron = custom if custom else self.var_formato_fecha_combo.get()

        # Mapear sintaxis legible a placeholders internos
        mapa_fmt = {
            "YYYY/MM": "{YYYY}/{MM}",
            "YYYY-MM": "{YYYY}-{MM}",
            "YYYY/MM/DD": "{YYYY}/{MM}/{DD}",
            "YYYY-MM-DD": "{YYYY}-{MM}-{DD}",
            "MM/YYYY": "{MM}/{YYYY}",
            "MMMM YYYY": "{MES_NOMBRE} {YYYY}",
            "MMM YYYY": "{MES_ABR} {YYYY}",
            "DD/MM/YYYY": "{DD}/{MM}/{YYYY}"
        }
        patron_inter = mapa_fmt.get(patron, patron)

        fecha_dem = date(2024, 7, 24)
        ej_str = patron_inter.replace("{YYYY}", "2024").replace("{MM}", "07").replace("{DD}", "24").replace("{MES_NOMBRE}", "julio").replace("{MES_ABR}", "jul")
        self.lbl_ejemplo_fecha.config(text=f"Ejemplo de subcarpeta: {ej_str}")

        self._actualizar_visor_paso3()

    def _actualizar_visor_paso3(self):
        if not hasattr(self, 'tree_visor'):
            return

        for item in self.tree_visor.get_children():
            self.tree_visor.delete(item)

        self._guardar_estructura_paso3()

        cp = self.estructura.get('criterio_primario', 'fecha')
        cs = self.estructura.get('criterio_secundario', None)

        if cp == 'ninguno' or (not cp and not cs):
            self.tree_visor.insert("", "end", text="destino/ (Sin estructura definida: todos los archivos en la raíz de destino)")
            return

        # Archivo simulado ficticio
        arch_ficticio = Path("mi_foto.jpg")
        fecha_ficticia = date(2024, 5, 10)
        destino_base = Path("destino")

        try:
            ruta_res = generar_ruta_destino(
                archivo_path=arch_ficticio,
                fecha=fecha_ficticia,
                carpeta_raiz_destino=destino_base,
                estructura=self.estructura
            )

            # Aplicar plantilla de renombrado si está activa
            if self.estructura.get('activar_renombrado') and self.estructura.get('plantilla_nombre'):
                plantilla = self.estructura['plantilla_nombre']
                fmt = self.estructura.get('formato_fecha', '{YYYY}-{MM}-{DD}')
                try:
                    nuevo_nombre = renombrar_archivo(arch_ficticio, plantilla, fecha_ficticia, 1, fmt)
                    ruta_res = ruta_res.parent / nuevo_nombre
                except Exception:
                    pass

            rel = ruta_res.relative_to(destino_base)
            partes = list(rel.parts)
        except Exception:
            self.tree_visor.insert("", "end", text="destino/ (No se puede generar la vista previa)")
            return

        # Construir árbol jerárquico en el Treeview
        parent = self.tree_visor.insert("", "end", text="destino/", open=True)

        for i, part in enumerate(partes):
            if i == len(partes) - 1:
                self.tree_visor.insert(parent, "end", text=f"📄 {part}", open=True)
            else:
                parent = self.tree_visor.insert(parent, "end", text=f"📁 {part}/", open=True)

    def _al_cambiar_renombrado(self):
        """Actualiza el ejemplo de renombrado y valida la plantilla."""
        if not hasattr(self, 'lbl_plantilla_ejemplo'):
            return

        activo = self.var_activar_renombrado.get()
        plantilla = self.var_plantilla_nombre.get().strip()

        # Activar/desactivar el entry de plantilla
        estado_entry = "normal" if activo else "disabled"
        if hasattr(self, 'entry_plantilla'):
            self.entry_plantilla.config(state=estado_entry)

        if not activo or not plantilla:
            self.lbl_plantilla_ejemplo.config(text="Vista previa: renombrado desactivado")
            self.lbl_plantilla_validacion.config(text="")
            self._actualizar_visor_paso3()
            return

        # Validación: la plantilla debe contener {nombre} o {fecha}
        if '{nombre}' not in plantilla and '{fecha}' not in plantilla:
            self.lbl_plantilla_validacion.config(
                text="⚠️ La plantilla debe contener {nombre} o {fecha} para evitar nombres vacíos.",
                foreground="red"
            )
        else:
            self.lbl_plantilla_validacion.config(text="✅ Plantilla válida.", foreground="#006600")

        # Generar ejemplo con archivo ficticio
        arch_ej = Path("mi_foto.jpg")
        fecha_ej = date(2024, 5, 10)
        self._guardar_estructura_paso3()
        fmt = self.estructura.get('formato_fecha', '{YYYY}-{MM}-{DD}')
        try:
            nombre_ej = renombrar_archivo(arch_ej, plantilla, fecha_ej, 1, fmt)
            self.lbl_plantilla_ejemplo.config(
                text=f"Vista previa: {nombre_ej}", foreground="#0055AA"
            )
        except Exception as ex:
            self.lbl_plantilla_ejemplo.config(
                text=f"Error en plantilla: {ex}", foreground="red"
            )

        self._actualizar_visor_paso3()

    def _guardar_estructura_paso3(self):
        mapa_crit = {
            'Fecha': 'fecha',
            'Tipo de archivo': 'tipo',
            'Nombre': 'nombre',
            'Ninguno': 'ninguno'
        }
        crit_p = mapa_crit.get(self.var_criterio_primario.get(), 'fecha')
        crit_s = mapa_crit.get(self.var_criterio_secundario.get(), None) if self.var_usar_secundario.get() else None

        custom = self.var_formato_fecha_custom.get().strip()
        patron_elegido = custom if custom else self.var_formato_fecha_combo.get()

        mapa_fmt = {
            "YYYY/MM": "{YYYY}/{MM}",
            "YYYY-MM": "{YYYY}-{MM}",
            "YYYY/MM/DD": "{YYYY}/{MM}/{DD}",
            "YYYY-MM-DD": "{YYYY}-{MM}-{DD}",
            "MM/YYYY": "{MM}/{YYYY}",
            "MMMM YYYY": "{MES_NOMBRE} {YYYY}",
            "MMM YYYY": "{MES_ABR} {YYYY}",
            "DD/MM/YYYY": "{DD}/{MM}/{YYYY}"
        }
        patron_final = mapa_fmt.get(patron_elegido, patron_elegido)

        activar_ren = self.var_activar_renombrado.get()
        plantilla_ren = self.var_plantilla_nombre.get().strip() if activar_ren else None

        self.estructura = {
            'criterio_primario': crit_p,
            'criterio_secundario': crit_s,
            'formato_fecha': patron_final,
            'organizacion_tipo': self.var_org_tipo.get(),
            'organizacion_nombre': self.var_org_nombre.get(),
            'usar_fecha_creacion': (self.var_fuente_fecha.get() == "ctime"),
            'activar_renombrado': activar_ren,
            'plantilla_nombre': plantilla_ren,
        }

    # ---------------------------------------------------------
    # EJECUCIÓN MULTIHILO PASO 4
    # ---------------------------------------------------------
    def _iniciar_ejecucion_hilo(self):
        if not self.planes_actuales:
            messagebox.showinfo("Sin Archivos", "Por favor analice y genere un plan primero en el Paso 4.")
            return

        p_origen = Path(self.origen)
        p_destino = Path(self.destino)

        if not p_origen.exists() or not p_destino.exists():
            messagebox.showerror("Directorio No Encontrado", "La carpeta de origen o destino ya no existe en el sistema.")
            return

        modo_actual = self.var_modo.get()

        if modo_actual == "Mover":
            try:
                st_orig = p_origen.stat()
                st_dest = p_destino.stat()
                if hasattr(st_orig, "st_dev") and hasattr(st_dest, "st_dev"):
                    if st_orig.st_dev == st_dest.st_dev:
                        resp = messagebox.askyesno(
                            "Advertencia de Eliminación de Origen",
                            f"La carpeta origen y destino están en la misma unidad.\n\n"
                            "⚠️ Al seleccionar 'Mover', los archivos originales serán ELIMINADOS del directorio fuente.\n\n"
                            "¿Desea continuar?"
                        )
                        if not resp:
                            return
            except Exception:
                pass

        total_archivos = len(self.planes_actuales)

        confirmacion = messagebox.askyesno(
            "Confirmar Proceso",
            f"¿Desea iniciar la operación de {modo_actual.lower()} para {total_archivos} archivos?\n\n"
            f"• Modo de operación: {modo_actual}\n"
            f"• Archivos totales: {total_archivos}"
        )

        if not confirmacion:
            return

        self.ejecutando = True
        self.cancelar = False

        self.btn_anterior.config(state="disabled")
        self.btn_siguiente.config(state="disabled")
        self.btn_analizar.config(state="disabled")
        self.btn_ejecutar.config(state="disabled")
        self.btn_reiniciar.config(state="disabled")

        self.progressbar_global.config(mode="determinate", maximum=total_archivos, value=0)

        self._log(f"\n🚀 Iniciando procesamiento ({modo_actual}) de {total_archivos} archivos...")

        # Capturar flags de limpieza antes de lanzar el hilo (no acceder a tk.Var desde hilos)
        limpiar_orig = self.var_limpiar_origen.get()
        limpiar_dest = self.var_limpiar_destino.get()

        hilo_ejecucion = threading.Thread(
            target=self._hilo_tarea_ejecutar,
            args=(self.planes_actuales, modo_actual, self.origen, self.destino, limpiar_orig, limpiar_dest),
            daemon=True
        )
        hilo_ejecucion.start()

    def _hilo_tarea_ejecutar(
        self,
        planes: List[Dict[str, Any]],
        modo: str,
        origen_str: str = "",
        destino_str: str = "",
        limpiar_origen: bool = False,
        limpiar_destino: bool = False
    ):
        exitos = 0
        errores = 0
        duplicados = 0
        fue_cancelado = False

        es_copia = (modo == "Copiar")
        verbo = "COPIAR" if es_copia else "MOVER"

        # Conjunto de destinos reservados para prevenir colisiones de nombre en tiempo real
        nombres_reservados: set = {p['destino'] for p in planes}

        for i, plan in enumerate(planes, start=1):
            if self.cancelar:
                self.cola_eventos.put(('LOG_EJECUCION', f"⚠️ OPERACIÓN CANCELADA POR EL USUARIO EN EL ARCHIVO {i}/{len(planes)}."))
                fue_cancelado = True
                break

            origen: Path = plan['origen']
            destino: Path = plan['destino']
            accion: str = plan['accion'].lower()

            if accion == 'duplicado':
                duplicados += 1

            self.cola_eventos.put(('PROGRESO_PROCESADO', (i, origen.name)))

            try:
                if not origen.exists():
                    raise FileNotFoundError(f"El archivo origen no existe: {origen.name}")

                destino.parent.mkdir(parents=True, exist_ok=True)

                # Resolución de colisiones: aplicar sufijo incremental si el destino ya existe
                destino_final = destino
                if destino_final.exists() or destino_final in nombres_reservados:
                    nombres_reservados.discard(destino_final)
                    destino_final = generar_nombre_unico(destino, nombres_reservados)
                    nombres_reservados.add(destino_final)

                if es_copia:
                    shutil.copy2(str(origen), str(destino_final))
                else:
                    shutil.move(str(origen), str(destino_final))

                exitos += 1
                msg_log = f"[{i}/{len(planes)}] OK [{verbo}]: '{origen.name}' -> '{destino_final}'"
                self.cola_eventos.put(('LOG_EJECUCION', msg_log))

            except OSError as e:
                errores += 1
                msg_log = f"[{i}/{len(planes)}] 🔴 ERROR I/O CRÍTICO (Unidad desconectada/Error de disco) en '{origen.name}': {e}"
                self.cola_eventos.put(('LOG_EJECUCION', msg_log))
                self.cola_eventos.put(('ERROR_DISCO', f"Error crítico de almacenamiento:\n{e}"))
                break

            except Exception as e:
                errores += 1
                msg_log = f"[{i}/{len(planes)}] ❌ ERROR al procesar '{origen.name}': {e}"
                self.cola_eventos.put(('LOG_EJECUCION', msg_log))

        # Limpieza de carpetas vacías post-operación
        if not fue_cancelado:
            if not es_copia and limpiar_origen and origen_str:
                try:
                    eliminadas_o = limpiar_carpetas_vacias(origen_str, dry_run=False)
                    if eliminadas_o:
                        self.cola_eventos.put(('LOG_EJECUCION',
                            f"🗑️ Carpetas vacías eliminadas del origen: {len(eliminadas_o)}"))
                except Exception as e:
                    self.cola_eventos.put(('LOG_EJECUCION', f"⚠️ Error al limpiar carpetas del origen: {e}"))

            if limpiar_destino and destino_str:
                try:
                    eliminadas_d = limpiar_carpetas_vacias(destino_str, dry_run=False)
                    if eliminadas_d:
                        self.cola_eventos.put(('LOG_EJECUCION',
                            f"🗑️ Carpetas vacías eliminadas del destino: {len(eliminadas_d)}"))
                except Exception as e:
                    self.cola_eventos.put(('LOG_EJECUCION', f"⚠️ Error al limpiar carpetas del destino: {e}"))

        self.cola_eventos.put(('FIN_EJECUCION', (exitos, errores, duplicados, fue_cancelado or self.cancelar)))

    def _procesar_cola_eventos(self):
        try:
            while True:
                tipo, datos = self.cola_eventos.get_nowait()

                if tipo == 'FIN_GENERAR_PLAN':
                    planes, lista_errores, error_fatal = datos
                    self.ejecutando = False
                    self.btn_analizar.config(state="normal")

                    if error_fatal:
                        self.lbl_estado_analisis.config(text="Error al generar plan", foreground="red")
                        messagebox.showerror("Error de Análisis", f"Ocurrió un error al analizar los archivos:\n{error_fatal}")
                    else:
                        self.planes_actuales = planes

                        if not planes and not lista_errores:
                            self.lbl_estado_analisis.config(text="Sin coincidencias", foreground="#CC6600")
                            messagebox.showinfo(
                                "Sin Coincidencias",
                                "No se encontraron archivos en la carpeta origen que cumplan con los filtros de categoría y extensión seleccionados."
                            )
                        else:
                            self.lbl_estado_analisis.config(text=f"Plan generado: {len(planes)} archivos", foreground="#0066CC")

                        for p in planes:
                            accion_str = p['accion'].upper()
                            fecha_str = str(p['fecha']) if p['fecha'] else "SIN FECHA"
                            self.tree.insert("", "end", values=(p['origen'].name, accion_str, str(p['destino']), fecha_str), tags=(accion_str,))

                        if lista_errores:
                            for err in lista_errores:
                                arch_p = err['archivo']
                                self.tree.insert("", "end", values=(arch_p.name, "ERROR", err['error'], "N/A"), tags=("ERROR",))

                        if planes:
                            self.btn_ejecutar.config(state="normal")

                elif tipo == 'PROGRESO_PROCESADO':
                    i, nombre_arch = datos
                    total = len(self.planes_actuales)
                    porcentaje_base = 75
                    porcentaje = porcentaje_base + int((i / total) * 25)
                    self.progressbar_global.config(value=porcentaje)
                    self.lbl_archivo_actual.config(text=f"Procesando ({i}/{total}): {nombre_arch}")

                elif tipo == 'LOG_EJECUCION':
                    self._log(datos)

                elif tipo == 'ERROR_DISCO':
                    messagebox.showerror("Error de Dispositivo", datos)

                elif tipo == 'PROGRESO_CLONACION':
                    indice, total, nombre, bytes_copiados, bytes_totales = datos

                    pct = 0.0
                    if bytes_totales > 0:
                        pct = (bytes_copiados / bytes_totales) * 100
                    elif total > 0:
                        pct = (indice / total) * 100

                    self.progressbar_clon.config(value=pct)
                    self.lbl_clon_porcentaje.config(text=f"{pct:.1f}%")

                    gb_copiados = bytes_copiados / (1024**3)
                    gb_totales = bytes_totales / (1024**3)
                    self.lbl_clon_info.config(text=f"[{indice} / {total} archivos] ({gb_copiados:.2f} GB / {gb_totales:.2f} GB)")
                    self.lbl_clon_archivo.config(text=nombre)

                    # Update global progress bar too
                    self.progressbar_global.config(value=pct)

                elif tipo == 'FIN_CLONACION':
                    res = datos
                    self.frame_progreso_clonacion.pack_forget()
                    self.progressbar_global.config(value=100)
                    messagebox.showinfo("Clonación Finalizada", res)

                elif tipo == 'FIN_EJECUCION':
                    exitos, errores, duplicados, fue_cancelado = datos
                    self.ejecutando = False

                    self.lbl_archivo_actual.config(text="")
                    self.btn_anterior.config(state="normal")
                    self.btn_ejecutar.config(state="disabled")
                    self.btn_reiniciar.config(state="normal")
                    self.btn_reiniciar.pack(side="right", padx=5)

                    estado_str = "Cancelada" if fue_cancelado else "Completada"
                    self._log("=" * 80)
                    self._log(f"RESUMEN FINAL ({estado_str}): Éxitos: {exitos} | Errores: {errores} | Duplicados: {duplicados}")
                    self._log("=" * 80)

                    msg_resumen = (
                        f"Organización de archivos {estado_str.lower()}.\n\n"
                        f"• Archivos procesados con éxito: {exitos}\n"
                        f"• Duplicados gestionados: {duplicados}\n"
                        f"• Errores registrados: {errores}"
                    )
                    if fue_cancelado:
                        messagebox.showwarning("Operación Cancelada", msg_resumen + "\n\nSe conservaron los archivos procesados hasta el momento.")
                    else:
                        messagebox.showinfo("Proceso Finalizado", msg_resumen)

        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._procesar_cola_eventos)

    # ---------------------------------------------------------
    # RESUMEN Y ANÁLISIS EN PASO 4
    # ---------------------------------------------------------
    def _actualizar_resumen_paso4(self):
        self.lbl_resumen_origen.config(text=f"Origen: {self.origen}")
        self.lbl_resumen_destino.config(text=f"Destino: {self.destino}")
        self.lbl_resumen_modo.config(text=f"Modo: {self.var_modo.get()}")

        exts_totales = self._obtener_lista_extensiones_resultante()
        exts_str = ", ".join([f".{e}" for e in exts_totales]) if exts_totales else "Todas (sin filtro)"
        self.lbl_resumen_filtros.config(text=f"Filtros (extensiones): {exts_str}")

        # Formatear representación legible de la estructura seleccionada
        if not self.estructura:
            est_str = "Fecha (YYYY/MM) [Por defecto]"
        else:
            def _describir_criterio(crit: str) -> str:
                if crit == 'fecha':
                    fmt = self.estructura.get('formato_fecha', '{YYYY}/{MM}')
                    # Limpiar llaves para mostrar sintaxis legible
                    fmt_limpio = fmt.replace("{YYYY}", "YYYY").replace("{MM}", "MM").replace("{DD}", "DD").replace("{MES_NOMBRE}", "MesNombre").replace("{MES_ABR}", "MesAbr")
                    return f"Fecha ({fmt_limpio})"
                elif crit == 'tipo':
                    org_t = self.estructura.get('organizacion_tipo', 'extension')
                    tipo_desc = "categoría" if org_t == 'categoria' else "extensión"
                    return f"Tipo ({tipo_desc})"
                elif crit == 'nombre':
                    org_n = self.estructura.get('organizacion_nombre', 'primera_letra')
                    nom_desc = "primera letra" if org_n == 'primera_letra' else "nombre completo"
                    return f"Nombre ({nom_desc})"
                elif crit == 'ninguno':
                    return "Ninguno"
                return str(crit)

            cp_desc = _describir_criterio(self.estructura.get('criterio_primario', 'fecha'))
            cs = self.estructura.get('criterio_secundario')
            if cs:
                cs_desc = _describir_criterio(cs)
                est_str = f"Organización: {cp_desc} → {cs_desc}"
            else:
                est_str = f"Organización: {cp_desc}"

        self.lbl_resumen_estructura.config(text=est_str)

        sub_str = "Sí" if self.filtros.get("incluir_subcarpetas", True) else "No"
        exif_str = "Sí" if self.filtros.get("usar_exif", True) else "No"
        hash_str = "Sí" if self.filtros.get("usar_hash", False) else "No"

        self.lbl_resumen_opciones.config(text=f"Subcarpetas: {sub_str} | EXIF: {exif_str} | Hash: {hash_str}")

    def _obtener_lista_extensiones_resultante(self) -> List[str]:
        if self.filtros.get("todos", True):
            return []

        resultado = set()
        for cat in self.filtros.get("categorias", []):
            if cat in self.CATEGORIAS_EXT:
                resultado.update(self.CATEGORIAS_EXT[cat])

        for ext_add in self.filtros.get("ext_adicionales", []):
            resultado.add(ext_add)

        return sorted(list(resultado))

    def _analizar_paso4(self):
        if not self.origen or not self.destino:
            messagebox.showerror("Carpetas Faltantes", "Por favor seleccione carpetas de origen y destino en el Paso 1.")
            return

        for item in self.tree.get_children():
            self.tree.delete(item)

        self.progressbar_global.config(value=100)
        self.lbl_estado_analisis.config(text="Generando plan...", foreground="#0066CC")
        self.btn_analizar.config(state="disabled")
        self.btn_ejecutar.config(state="disabled")

        exts_resultantes = self._obtener_lista_extensiones_resultante()
        exts_arg = exts_resultantes if exts_resultantes else None

        self.ejecutando = True

        # Construir diccionario de filtros avanzados
        filtros_avanzados = {
            'tamano_min_bytes': self.filtros.get('tamano_min_bytes'),
            'tamano_max_bytes': self.filtros.get('tamano_max_bytes'),
            'dias_antiguedad': self.filtros.get('dias_antiguedad'),
            'incluir_ocultos': self.filtros.get('incluir_ocultos', False),
            'patron_regex': self.filtros.get('patron_regex'),
            'usar_creacion_filtro': self.filtros.get('usar_creacion_filtro', False),
        }

        hilo = threading.Thread(
            target=self._hilo_generar_plan,
            args=(
                self.origen,
                self.destino,
                exts_arg,
                self.filtros.get("incluir_subcarpetas", True),
                self.filtros.get("usar_exif", True),
                self.filtros.get("usar_hash", False),
                self.estructura,
                filtros_avanzados
            ),
            daemon=True
        )
        hilo.start()

    def _hilo_generar_plan(self, origen, destino, extensiones, subcarpetas, exif, hash_dups, estructura, filtros_avanzados=None):
        try:
            sub_msg = "recursivamente (incluyendo subcarpetas)" if subcarpetas else "solo en el directorio raíz (sin subcarpetas)"
            self.cola_eventos.put(('LOG_EJECUCION', f"🔍 Iniciando escaneo de archivos en '{origen}' {sub_msg}..."))

            # Registrar filtros avanzados activos para el log
            fa = filtros_avanzados or {}
            filtros_activos = []
            if fa.get('tamano_min_bytes'):
                filtros_activos.append(f"Tamaño mín: {fa['tamano_min_bytes'] / (1024*1024):.2f} MB")
            if fa.get('tamano_max_bytes'):
                filtros_activos.append(f"Tamaño máx: {fa['tamano_max_bytes'] / (1024*1024):.2f} MB")
            if fa.get('dias_antiguedad'):
                filtros_activos.append(f"Antigüedad: últimos {fa['dias_antiguedad']} días")
            if fa.get('patron_regex'):
                filtros_activos.append(f"Regex: {fa['patron_regex']}")
            if fa.get('incluir_ocultos'):
                filtros_activos.append("Incluir ocultos")
            if filtros_activos:
                self.cola_eventos.put(('LOG_EJECUCION', f"🔧 Filtros avanzados activos: {', '.join(filtros_activos)}"))

            planes, lista_errores = generar_plan_con_estructura(
                origen=origen,
                destino_base=destino,
                extensiones=extensiones,
                incluir_subcarpetas=subcarpetas,
                usar_exif=exif,
                usar_hash_duplicados=hash_dups,
                estructura=estructura,
                filtros_avanzados=filtros_avanzados
            )
            if self.ejecutando:
                self.cola_eventos.put(('FIN_GENERAR_PLAN', (planes, lista_errores, None)))
        except Exception as e:
            if self.ejecutando:
                self.cola_eventos.put(('FIN_GENERAR_PLAN', ([], [], e)))

    def _log(self, mensaje: str):
        self.log_text.insert(tk.END, mensaje + "\n")
        self.log_text.see(tk.END)

    def _reiniciar_asistente(self):
        if messagebox.askyesno("Reiniciar Asistente", "¿Desea volver al inicio y reiniciar las opciones elegidas?"):
            self.entry_origen.delete(0, tk.END)
            self.entry_destino.delete(0, tk.END)
            self.origen = ""
            self.destino = ""
            self.var_modo.set("Copiar")
            self._al_cambiar_modo()

            self.var_cat_todos.set(True)
            self._al_cambiar_cat_todos()
            self.ext_adicionales.clear()
            self.entry_ext_add.delete(0, tk.END)
            self.lbl_status_ext_add.config(text="")
            self._actualizar_lbl_ext_adicionales()

            self.var_subcarpetas.set(True)
            self.var_exif.set(True)
            self.var_hash.set(False)

            # Resetear filtros avanzados
            self.var_tamano_min.set("")
            self.var_tamano_max.set("")
            self.var_dias_antiguedad.set(0)
            self.var_incluir_ocultos.set(False)
            self.var_patron_regex.set("")
            self.var_usar_creacion_filtro.set(False)
            self.var_limpiar_origen.set(False)
            self.var_limpiar_destino.set(False)

            self.var_criterio_primario.set("Fecha")
            self.var_usar_secundario.set(True)
            self.var_criterio_secundario.set("Tipo de archivo")
            self.var_formato_fecha_combo.set("YYYY/MM")
            self.var_formato_fecha_custom.set("")
            self.var_org_tipo.set("extension")
            self.var_org_nombre.set("primera_letra")
            self.var_fuente_fecha.set("mtime")

            # Resetear renombrado
            self.var_activar_renombrado.set(False)
            self.var_plantilla_nombre.set("{nombre}.{ext}")
            self._al_cambiar_renombrado()

            self._al_cambiar_criterios_paso3()

            self.planes_actuales.clear()
            for item in self.tree.get_children():
                self.tree.delete(item)

            self.log_text.delete("1.0", tk.END)
            self.paso_actual = 1
            self._actualizar_estado_paso()

    def _cancelar(self):
        if self.ejecutando:
            if messagebox.askyesno("Detener Operación", "¿Desea cancelar el proceso en ejecución? Los archivos procesados hasta el momento se mantendrán."):
                self.cancelar = True
        else:
            if messagebox.askyesno("Salir del Asistente", "¿Desea salir de la aplicación?"):
                self._guardar_configuracion()
                self.root.destroy()

    def _al_cerrar_ventana(self):
        if self.ejecutando:
            if not messagebox.askyesno("Salir", "Hay una tarea de archivos en ejecución. ¿Desea forzar la salida?"):
                return
            self.cancelar = True
        self.ejecutando = False

        # Preguntar opcionalmente si desea guardar el perfil de configuración actual
        if messagebox.askyesno("Guardar Perfil", "¿Desea guardar la configuración actual como un Perfil antes de salir?"):
            self._guardar_perfil()

        self._guardar_configuracion()
        self.root.destroy()

    # ---------------------------------------------------------
    # MANEJADORES DE CATEGORÍAS PASO 2
    # ---------------------------------------------------------
    def _al_cambiar_cat_todos(self):
        if self.var_cat_todos.get():
            for v in self.vars_categorias.values():
                v.set(False)

    def _al_cambiar_cat_individual(self):
        alguno_activo = any(v.get() for v in self.vars_categorias.values())
        if alguno_activo:
            self.var_cat_todos.set(False)
        else:
            self.var_cat_todos.set(True)

    def _agregar_extensiones_adicionales(self):
        raw_text = self.entry_ext_add.get().strip()
        if not raw_text:
            self.lbl_status_ext_add.config(text="⚠️ Escriba al menos una extensión.", foreground="#CC6600")
            return

        partes = [p.strip().lower() for p in raw_text.split(",") if p.strip()]
        nuevas = 0
        invalidas = 0

        for ext in partes:
            ext_limpia = ext.lstrip(".")
            if not re.match(r'^[a-zA-Z0-9]+$', ext_limpia):
                invalidas += 1
                continue
            if ext_limpia not in self.ext_adicionales:
                self.ext_adicionales.append(ext_limpia)
                nuevas += 1

        if nuevas > 0:
            self.entry_ext_add.delete(0, tk.END)
            self._actualizar_lbl_ext_adicionales()
            if invalidas > 0:
                self.lbl_status_ext_add.config(text=f"✅ Añadidas {nuevas} extensión(es). Se ignoraron {invalidas} inválida(s).", foreground="#006600")
            else:
                self.lbl_status_ext_add.config(text=f"✅ Añadidas {nuevas} extensión(es) correctamente.", foreground="#006600")
        else:
            if invalidas > 0:
                self.lbl_status_ext_add.config(text="❌ Formato inválido. Solo use letras y números.", foreground="red")
            else:
                self.lbl_status_ext_add.config(text="ℹ️ La(s) extensión(es) ya estaban incluidas.", foreground="#555555")

    def _actualizar_lbl_ext_adicionales(self):
        if not self.ext_adicionales:
            self.lbl_ext_add_lista.config(text="Extensiones personalizadas: Ninguna")
        else:
            lista_str = ", ".join([f".{e}" for e in self.ext_adicionales])
            self.lbl_ext_add_lista.config(text=f"Extensiones personalizadas: {lista_str}")

    def _guardar_filtros_paso2(self):
        cats_seleccionadas = [cat for cat, var in self.vars_categorias.items() if var.get()]

        # Convertir MB a bytes (None si el campo está vacío o es cero)
        def _parse_mb(val: str):
            try:
                v = float(val.strip())
                return int(v * 1024 * 1024) if v > 0 else None
            except (ValueError, AttributeError):
                return None

        tamano_min_bytes = _parse_mb(self.var_tamano_min.get())
        tamano_max_bytes = _parse_mb(self.var_tamano_max.get())

        try:
            dias = int(self.var_dias_antiguedad.get())
        except (ValueError, tk.TclError):
            dias = 0

        patron_rx = self.var_patron_regex.get().strip() or None

        self.filtros = {
            "todos": self.var_cat_todos.get(),
            "categorias": cats_seleccionadas,
            "ext_adicionales": list(self.ext_adicionales),
            "incluir_subcarpetas": self.var_subcarpetas.get(),
            "usar_exif": self.var_exif.get(),
            "usar_hash": self.var_hash.get(),
            # Filtros avanzados
            "tamano_min_bytes": tamano_min_bytes,
            "tamano_max_bytes": tamano_max_bytes,
            "dias_antiguedad": dias if dias > 0 else None,
            "incluir_ocultos": self.var_incluir_ocultos.get(),
            "patron_regex": patron_rx,
            "usar_creacion_filtro": self.var_usar_creacion_filtro.get(),
        }

    # ---------------------------------------------------------
    # MANEJADORES PASO 1 (ORIGEN / DESTINO)
    # ---------------------------------------------------------
    def _examinar_origen(self):
        directorio = filedialog.askdirectory(title="Seleccionar Carpeta Origen")
        if directorio:
            self.entry_origen.delete(0, tk.END)
            self.entry_origen.insert(0, directorio)
            self._validar_rutas_paso1()

    def _examinar_destino(self):
        directorio = filedialog.askdirectory(title="Seleccionar Carpeta Destino")
        if directorio:
            self.entry_destino.delete(0, tk.END)
            self.entry_destino.insert(0, directorio)
            self._validar_rutas_paso1()

    def _detectar_unidad_extraible(self):
        orig = self.entry_origen.get().strip()
        if not orig:
            messagebox.showinfo("Selección Faltante", "Por favor seleccione una carpeta de origen en el formulario.")
            return

        path_orig = Path(orig).resolve()
        str_path = str(path_orig)

        if str_path.startswith("/media/") or str_path.startswith("/mnt/"):
            messagebox.showinfo(
                "Unidad Extraíble Detectada",
                f"La carpeta origen se encuentra en un dispositivo externo ('{str_path}').\n\n"
                "Se sugiere mantener el modo 'Copiar archivos' para evitar pérdidas en medios extraíbles."
            )
            self.var_modo.set("Copiar")
            self._al_cambiar_modo()
        else:
            messagebox.showinfo(
                "Dispositivo Local",
                "La carpeta de origen seleccionada reside en el almacenamiento interno principal."
            )

    def _al_cambiar_modo(self):
        if self.var_modo.get() == "Mover":
            self.lbl_precaucion.pack(anchor="w", pady=(5, 0))
        else:
            self.lbl_precaucion.pack_forget()

    def _validar_rutas_paso1(self) -> bool:
        o_str = self.entry_origen.get().strip()
        d_str = self.entry_destino.get().strip()

        p_origen = Path(o_str) if o_str else None
        p_destino = Path(d_str) if d_str else None

        valido = (
            p_origen is not None and p_origen.exists() and p_origen.is_dir() and
            p_destino is not None and p_destino.exists() and p_destino.is_dir()
        )

        if valido:
            self.origen = str(p_origen)
            self.destino = str(p_destino)
            self.modo = self.var_modo.get()
            if self.paso_actual == 1:
                self.btn_siguiente.config(state="normal")
        else:
            if self.paso_actual == 1:
                self.btn_siguiente.config(state="disabled")

        return valido

    # ---------------------------------------------------------
    # NUEVOS MANEJADORES DE FUNCIONALIDADES AVANZADAS (PASOS 1-5)
    # ---------------------------------------------------------
    def _detectar_dispositivos_multimedia_gui(self):
        dispositivos = detectar_dispositivos_multimedia()
        if not dispositivos:
            messagebox.showinfo("Sin Dispositivos Multimedia", "No se detectaron teléfonos MTP ni cámaras conectadas en las rutas de montaje estándar (/media, /run/media, /run/user/.../gvfs).")
            return

        dlg = tk.Toplevel(self.root)
        dlg.title("Dispositivos Multimedia Detectados")
        dlg.geometry("520x300")
        dlg.transient(self.root)
        dlg.grab_set()

        ttk.Label(dlg, text="Seleccione un dispositivo multimedia para usar como origen:", font=("Helvetica", 10, "bold")).pack(anchor="w", padx=15, pady=(15, 5))

        listbox = tk.Listbox(dlg, height=8)
        listbox.pack(fill="both", expand=True, padx=15, pady=5)

        for d in dispositivos:
            listbox.insert(tk.END, f"{d['etiqueta']} [{d['tipo']}] - {d['espacio']} ({d['ruta']})")

        def _usar_seleccionado():
            sel = listbox.curselection()
            if sel:
                idx = sel[0]
                dev_path = dispositivos[idx]['ruta']
                self.entry_origen.delete(0, tk.END)
                self.entry_origen.insert(0, dev_path)
                self._validar_rutas_paso1()
                dlg.destroy()
                messagebox.showinfo("Origen Establecido", f"Se estableció '{dev_path}' como carpeta de origen.")

        ttk.Button(dlg, text="Usar como origen", command=_usar_seleccionado).pack(pady=10)

    def _detectar_estructura_destino_gui(self):
        dest = self.entry_destino.get().strip()
        if not dest or not Path(dest).exists():
            messagebox.showwarning("Destino Inválido", "Por favor seleccione una carpeta de destino existente en el Paso 1.")
            return

        info = analizar_estructura_destino(dest)
        if not info['existe'] or info['tipo'] in ('vacio', 'desconocido'):
            messagebox.showinfo("Análisis de Destino", f"La carpeta de destino no tiene una estructura previa identificable (Estado: {info['tipo']}).")
            return

        msg = (
            f"Se detectó una estructura existente en el destino:\n\n"
            f"• Tipo detectado: {info['tipo'].upper()}\n"
            f"• Ejemplo de ruta: {info['ejemplo']}\n"
            f"• Carpetas principales: {', '.join(info['carpetas'])}\n\n"
            f"¿Desea ajustar el Paso 3 para INTEGRAR los archivos en esta estructura existente?"
        )

        resp = messagebox.askyesnocancel("Estructura Detectada en Destino", msg)
        if resp is True:  # Aceptar: Integrar
            sug = info.get('estructura_sugerida', {})
            if sug.get('criterio_primario') == 'fecha':
                self.var_criterio_primario.set("Fecha")
                fmt = sug.get('formato_fecha', 'YYYY/MM')
                self.var_formato_fecha_combo.set(fmt if fmt in ("YYYY/MM", "YYYY-MM", "YYYY/MM/DD") else "YYYY/MM")
            elif sug.get('criterio_primario') == 'tipo':
                self.var_criterio_primario.set("Tipo de archivo")
                self.var_org_tipo.set(sug.get('organizacion_tipo', 'extension'))
            elif sug.get('criterio_primario') == 'nombre':
                self.var_criterio_primario.set("Nombre")
                self.var_org_nombre.set(sug.get('organizacion_nombre', 'primera_letra'))

            self._al_cambiar_criterios_paso3()
            self._guardar_estructura_paso3()

            if messagebox.askyesno("Guardar como Perfil", "¿Desea guardar esta estructura detectada como un Perfil para futuras ejecuciones?"):
                nom = simpledialog.askstring("Nombre de Perfil", "Escriba un nombre para el perfil:", initialvalue=f"Perfil_{info['tipo'].capitalize()}")
                if nom:
                    guardar_estructura_como_perfil(self.estructura, nom)
                    messagebox.showinfo("Perfil Guardado", f"Perfil '{nom}' guardado con éxito.")

            messagebox.showinfo("Estructura Ajustada", "Se ha actualizado la configuración del Paso 3 con la estructura detectada. Vuelva a hacer clic en 'Analizar y previsualizar'.")

    def _dialogo_deshacer(self):
        historial = obtener_historial_undo(limite=50)
        if not historial:
            messagebox.showinfo("Deshacer / Undo", "No hay operaciones registradas en el historial para deshacer.")
            return

        msg = (
            f"Historial Undo encontrado: {len(historial)} operaciones registradas.\n\n"
            f"Última operación:\n"
            f"• Fecha/Hora: {historial[-1].get('timestamp', 'N/A')}\n"
            f"• Modo: {historial[-1].get('modo', 'N/A')}\n"
            f"• Archivo: {historial[-1].get('nombre_final', 'N/A')}\n\n"
            f"¿Desea deshacer la ÚLTIMA operación?"
        )

        resp = messagebox.askyesno("Confirmar Deshacer", msg)
        if resp:
            exitos, errores, logs = deshacer_n_operaciones(n=1, dry_run=False)
            messagebox.showinfo("Resultado Undo", "\n".join(logs))

    def _abrir_historial_undo(self):
        historial = obtener_historial_undo(limite=50)
        if not historial:
            messagebox.showinfo("Historial Undo", "El historial de operaciones está vacío.")
            return

        dlg = tk.Toplevel(self.root)
        dlg.title("Historial de Operaciones (Undo)")
        dlg.geometry("650x400")
        dlg.transient(self.root)
        dlg.grab_set()

        ttk.Label(dlg, text="Últimas 50 operaciones ejecutadas:", font=("Helvetica", 10, "bold")).pack(anchor="w", padx=10, pady=5)

        cols = ("fecha", "modo", "origen", "destino")
        tree_u = ttk.Treeview(dlg, columns=cols, show="headings", selectmode="browse")
        tree_u.heading("fecha", text="Fecha/Hora")
        tree_u.heading("modo", text="Modo")
        tree_u.heading("origen", text="Origen")
        tree_u.heading("destino", text="Destino")

        tree_u.column("fecha", width=140)
        tree_u.column("modo", width=70)
        tree_u.column("origen", width=200)
        tree_u.column("destino", width=200)

        for op in reversed(historial):
            tree_u.insert("", "end", values=(
                op.get('timestamp', '')[:19],
                op.get('modo', ''),
                op.get('origen', ''),
                op.get('destino', '')
            ))

        tree_u.pack(fill="both", expand=True, padx=10, pady=5)

        frame_btns = ttk.Frame(dlg)
        frame_btns.pack(fill="x", padx=10, pady=10)

        def _deshacer_seleccionados():
            num = simpledialog.askinteger("Deshacer Múltiple", "¿Cuántas últimas operaciones desea revertir?", initialvalue=1, minvalue=1, maxvalue=len(historial))
            if num:
                exitos, errores, logs = deshacer_n_operaciones(n=num, dry_run=False)
                messagebox.showinfo("Resultado Undo", "\n".join(logs))
                dlg.destroy()

        def _simular_undo():
            num = simpledialog.askinteger("Simulación Undo", "¿Cuántas operaciones desea simular (Dry-Run)?", initialvalue=1, minvalue=1, maxvalue=len(historial))
            if num:
                exitos, errores, logs = deshacer_n_operaciones(n=num, dry_run=True)
                messagebox.showinfo("Simulación Dry-Run Undo", "\n".join(logs))

        ttk.Button(frame_btns, text="🔍 Simular reversión (Dry-Run)", command=_simular_undo).pack(side="left", padx=5)
        ttk.Button(frame_btns, text="↩️ Revertir N operaciones", command=_deshacer_seleccionados).pack(side="right", padx=5)

    def _examinar_generico(self, entry_widget: ttk.Entry):
        d = filedialog.askdirectory()
        if d:
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, d)

    def _ejecutar_clonacion_carpeta_gui(self):
        orig = self.entry_clone_orig.get().strip()
        dest = self.entry_clone_dest.get().strip()
        inc = self.var_clone_inc.get()

        if not orig or not dest or not Path(orig).exists():
            messagebox.showerror("Error de Clonación", "Por favor seleccione carpetas válidas de origen y destino.")
            return

        self.cancelar_clon = False
        self.frame_progreso_clonacion.pack(fill="x", pady=5)
        self.progressbar_clon.config(value=0)
        self.lbl_clon_porcentaje.config(text="0.0%")
        self.lbl_clon_info.config(text="Iniciando...")
        self.lbl_clon_archivo.config(text="")

        def _progreso(indice, total, nombre, bytes_copiados, bytes_totales):
            self.cola_eventos.put(('PROGRESO_CLONACION', (indice, total, nombre, bytes_copiados, bytes_totales)))

        def _cancelar_flag():
            return getattr(self, 'cancelar_clon', False)

        def _tarea():
            res = clonar_carpeta(
                orig,
                dest,
                incremental=inc,
                callback_progreso=_progreso,
                cancelar_flag=_cancelar_flag
            )
            self.cola_eventos.put(('FIN_CLONACION', res))

        threading.Thread(target=_tarea, daemon=True).start()

    def _cancelar_clonacion_gui(self):
        if messagebox.askyesno("Cancelar Clonación", "¿Desea cancelar la clonación actual?"):
            self.cancelar_clon = True

    def _ejecutar_respaldo_usuario_gui(self):
        dest = self.entry_user_dest.get().strip()
        if not dest:
            messagebox.showerror("Error de Respaldo", "Seleccione una carpeta de destino para el respaldo.")
            return

        rutas_sel = [r for r, var in self.vars_carpetas_user.items() if var.get()]
        if not rutas_sel:
            messagebox.showwarning("Selección Vacía", "Seleccione al menos una carpeta personal para respaldar.")
            return

        def _tarea():
            tot = len(rutas_sel)
            ex = 0
            for r in rutas_sel:
                p_r = Path(r)
                dest_sub = Path(dest) / p_r.name
                clonar_carpeta(p_r, dest_sub, incremental=True)
                ex += 1
            self.root.after(0, lambda: messagebox.showinfo("Respaldo Finalizado", f"Respaldo de {ex}/{tot} carpetas personales completado en '{dest}'."))

        threading.Thread(target=_tarea, daemon=True).start()
        messagebox.showinfo("Respaldo en Proceso", "El respaldo de carpetas de usuario ha comenzado en segundo plano...")

    def _ejecutar_clonacion_disco_gui(self):
        d_orig = self.entry_disk_orig.get().strip()
        d_dest = self.entry_disk_dest.get().strip()
        ddr = self.var_ddrescue.get()
        chk = self.var_check_md5.get()

        if not d_orig or not d_dest:
            messagebox.showerror("Campos Incompletos", "Especifique dispositivos válidos de origen y destino (ej: /dev/sdb y /dev/sdc).")
            return

        if not messagebox.askyesno("CONFIRMACIÓN DE SEGURIDAD CRÍTICA", f"⚠️ ADVERTENCIA: Esta acción borra completamente todo el contenido de '{d_dest}'.\n\n¿Está absolutamente seguro de continuar?"):
            return

        def _tarea():
            res = clonar_disco(d_orig, d_dest, usar_ddrescue=ddr, verificar_checksum=chk)
            self.root.after(0, lambda: messagebox.showinfo("Clonación de Disco", res))

        threading.Thread(target=_tarea, daemon=True).start()
        messagebox.showinfo("Clonación de Disco Lanzada", "Se ha iniciado la clonación de disco a nivel de bloque.")

    # ---------------------------------------------------------
    # NAVEGACIÓN Y ACTUALIZACIÓN DE ESTADOS PASOS 1-5
    # ---------------------------------------------------------
    def _actualizar_estado_paso(self):
        self.frame_paso1.pack_forget()
        self.frame_paso2.pack_forget()
        self.frame_paso3.pack_forget()
        self.frame_paso4.pack_forget()
        self.frame_paso5.pack_forget()

        if self.paso_actual == 1:
            self.lbl_paso.config(text="Paso 1 de 5: Selección de carpetas y dispositivos")
            self.progressbar_global.config(value=20)
            self.frame_paso1.pack(fill="both", expand=True)

            self.btn_anterior.config(state="disabled")
            self.btn_siguiente.config(state="normal")
            self.btn_siguiente.pack(side="right", padx=5)
            self.btn_ejecutar.pack_forget()
            self.btn_reiniciar.pack_forget()

            self._validar_rutas_paso1()

        elif self.paso_actual == 2:
            self.lbl_paso.config(text="Paso 2 de 5: Filtros de categorías y opciones")
            self.progressbar_global.config(value=40)
            self.frame_paso2.pack(fill="both", expand=True)

            self.btn_anterior.config(state="normal")
            self.btn_siguiente.config(state="normal")
            self.btn_siguiente.pack(side="right", padx=5)
            self.btn_ejecutar.pack_forget()
            self.btn_reiniciar.pack_forget()

        elif self.paso_actual == 3:
            self.lbl_paso.config(text="Paso 3 de 5: Estructura de organización y renombrado")
            self.progressbar_global.config(value=60)
            self.frame_paso3.pack(fill="both", expand=True)

            self.btn_anterior.config(state="normal")
            self.btn_siguiente.config(state="normal")
            self.btn_siguiente.pack(side="right", padx=5)
            self.btn_ejecutar.pack_forget()
            self.btn_reiniciar.pack_forget()

        elif self.paso_actual == 4:
            self.lbl_paso.config(text="Paso 4 de 5: Previsualización y ejecución")
            self.progressbar_global.config(value=80)
            self.frame_paso4.pack(fill="both", expand=True)

            self.btn_anterior.config(state="normal")
            self.btn_siguiente.config(state="normal")
            self.btn_siguiente.pack(side="right", padx=5)
            self.btn_reiniciar.pack_forget()

            self.btn_ejecutar.pack(side="right", padx=5)
            self.btn_ejecutar.config(state="normal" if self.planes_actuales else "disabled")

            self._actualizar_resumen_paso4()

        elif self.paso_actual == 5:
            self.lbl_paso.config(text="Paso 5 de 5: Respaldo y Clonación avanzada")
            self.progressbar_global.config(value=100)
            self.frame_paso5.pack(fill="both", expand=True)

            self.btn_anterior.config(state="normal")
            self.btn_siguiente.config(state="disabled")
            self.btn_siguiente.pack_forget()

            self.btn_ejecutar.pack_forget()
            self.btn_reiniciar.pack(side="right", padx=5)

    def _siguiente(self):
        if self.paso_actual == 1:
            if not self._validar_rutas_paso1():
                messagebox.showwarning("Carpetas Inválidas", "Por favor seleccione carpetas de origen y destino existentes.")
                return

        elif self.paso_actual == 2:
            self._guardar_filtros_paso2()

        elif self.paso_actual == 3:
            self._guardar_estructura_paso3()

        if self.paso_actual < 5:
            self.paso_actual += 1
            self._actualizar_estado_paso()

    def _anterior(self):
        if self.paso_actual == 5:
            self.btn_siguiente.pack(side="right", padx=5)

        if self.paso_actual > 1:
            self.paso_actual -= 1
            self._actualizar_estado_paso()


def main():
    root = tk.Tk()
    app = WizardApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
