#!/usr/bin/env python3
"""
Modulo gui_wizard.py - Interfaz Gráfica "Memexicanisimos Files v1.0" Desacoplada.
Consume estrictamente los contratos app_types.py y las funciones de core.py.
"""

import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox, simpledialog
import threading
import queue
import json
from pathlib import Path
from datetime import date
from typing import Dict, List, Any, Optional

from app_types import ServiceResult, PlanArchivo, FiltrosAvanzados, EstructuraConfig
from error_codes import ErrorCode
from config import AppConfig, CATEGORIAS_EXT
from logger import app_logger
from i18n import _

from core import (
    generar_plan_con_estructura, generar_ruta_destino,
    generar_nombre_unico, ejecutar_plan_con_modo,
    limpiar_carpetas_vacias, analizar_estructura_destino,
    deshacer_n_operaciones, obtener_historial_undo,
    clonar_carpeta, detectar_carpetas_usuario,
    detectar_dispositivos_multimedia, obtener_archivos
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
            tw, text=self.texto, justify=tk.LEFT, background="#FFF8E7",
            foreground="#111827", relief=tk.SOLID, borderwidth=1,
            font=("Helvetica", 9, "normal"), padx=8, pady=4
        )
        label.pack(ipadx=1)

    def ocultar_tip(self, event=None):
        tw = self.tip_window
        self.tip_window = None
        if tw:
            tw.destroy()


class WizardApp:
    COLOR_BG = "#FAF7F2"       # Marfil cálido
    COLOR_PANEL = "#FFFFFF"    # Blanco puro tarjetas
    COLOR_HEADER = "#1F2937"   # Carbón elegante
    COLOR_PRIMARY = "#B91C1C"  # Rojo mexicano
    COLOR_SUCCESS = "#059669"  # Verde jade
    COLOR_ACCENT = "#D97706"   # Dorado acento
    COLOR_TEXT = "#111827"     # Texto principal
    COLOR_SUBTEXT = "#4B5563"  # Texto secundario
    COLOR_BORDER = "#E5E7EB"   # Gris borde suave

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{AppConfig.APP_NAME} v{AppConfig.APP_VERSION} — Gestión y Respaldo de Archivos")
        self.root.geometry("960x740")
        self.root.minsize(860, 640)
        self.root.protocol("WM_DELETE_WINDOW", self._al_cerrar_ventana)

        self.logo_header_img = None
        self._cargar_imagenes_logo()

        self.paso_actual = 0  # 0 = Bienvenida, 1 a 5 = Pasos

        # Variables Paso 1
        self.origen = ""
        self.destino = ""
        self.var_modo = tk.StringVar(value="Copiar")

        # Variables Paso 2 (Filtros)
        self.var_cat_todos = tk.BooleanVar(value=True)
        self.vars_categorias: Dict[str, tk.BooleanVar] = {
            cat: tk.BooleanVar(value=False) for cat in CATEGORIAS_EXT
        }
        self.ext_adicionales: List[str] = []
        self.filtros: FiltrosAvanzados = {}

        self.var_subcarpetas = tk.BooleanVar(value=True)
        self.var_exif = tk.BooleanVar(value=True)
        self.var_hash = tk.BooleanVar(value=False)
        self.var_incluir_ocultos = tk.BooleanVar(value=False)
        self.var_usar_creacion_filtro = tk.BooleanVar(value=False)

        # Variables Paso 3 (Estructura de organización)
        self.var_criterio_primario = tk.StringVar(value="Fecha")
        self.var_usar_secundario = tk.BooleanVar(value=True)
        self.var_criterio_secundario = tk.StringVar(value="Tipo de archivo")

        self.var_formato_fecha_combo = tk.StringVar(value="YYYY/MM")
        self.var_formato_fecha_custom = tk.StringVar(value="")
        self.var_org_tipo = tk.StringVar(value="extension")
        self.var_org_nombre = tk.StringVar(value="primera_letra")
        self.var_fuente_fecha = tk.StringVar(value="mtime")

        self.estructura: EstructuraConfig = {}

        self.var_tamano_min = tk.StringVar(value="")
        self.var_tamano_max = tk.StringVar(value="")
        self.var_dias_antiguedad = tk.IntVar(value=0)
        self.var_patron_regex = tk.StringVar(value="")

        self.var_activar_renombrado = tk.BooleanVar(value=False)
        self.var_plantilla_nombre = tk.StringVar(value="{nombre}.{ext}")

        self.var_limpiar_origen = tk.BooleanVar(value=False)
        self.var_limpiar_destino = tk.BooleanVar(value=False)

        self.planes_actuales: List[PlanArchivo] = []
        self.ejecutando = False
        self.cancelar = False
        self.cola_eventos = queue.Queue()
        app_logger.registrar_gui_queue(self.cola_eventos)

        self._crear_interfaz()
        self._cargar_configuracion()
        self._actualizar_estado_paso()

        self.root.after(100, self._procesar_cola_eventos)

    def _cargar_imagenes_logo(self):
        try:
            path_logo = Path("icon/logo_memexicanisimos.png")
            if path_logo.exists():
                self.logo_header_img = tk.PhotoImage(file=str(path_logo))
                self.root.iconphoto(True, self.logo_header_img)
        except Exception:
            pass

    def _crear_interfaz(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("TFrame", background=self.COLOR_BG)
        style.configure("TLabel", background=self.COLOR_BG, foreground=self.COLOR_TEXT, font=("Helvetica", 10))
        style.configure("TLabelframe", background=self.COLOR_PANEL, borderwidth=1, relief="solid")
        style.configure("TLabelframe.Label", background=self.COLOR_PANEL, foreground=self.COLOR_TEXT, font=("Helvetica", 10, "bold"))
        style.configure("TCheckbutton", background=self.COLOR_BG, foreground=self.COLOR_TEXT, font=("Helvetica", 9))

        style.configure("Treeview", background="#FFFFFF", fieldbackground="#FFFFFF", foreground=self.COLOR_TEXT, rowheight=24)
        style.configure("Treeview.Heading", background="#EAF0F8", foreground=self.COLOR_TEXT, font=("Helvetica", 9, "bold"))
        style.map("Treeview", background=[("selected", "#D1FAE5")], foreground=[("selected", "#065F46")])

        self.root.configure(bg=self.COLOR_BG)
        self._crear_menu()

        # Header Bar
        self.frame_top = tk.Frame(self.root, bg=self.COLOR_HEADER, height=75)
        self.frame_top.pack(fill="x")

        frame_brand = tk.Frame(self.frame_top, bg=self.COLOR_HEADER)
        frame_brand.pack(side="left", padx=15, pady=10)

        if self.logo_header_img:
            lbl_logo = tk.Label(frame_brand, image=self.logo_header_img, bg=self.COLOR_HEADER)
            lbl_logo.pack(side="left", padx=(0, 10))
        else:
            lbl_brand = tk.Label(frame_brand, text=f"🇲🇽 {AppConfig.APP_NAME}", font=("Helvetica", 12, "bold"), fg="#FFFFFF", bg=self.COLOR_HEADER)
            lbl_brand.pack(side="top", anchor="w")
            lbl_subbrand = tk.Label(frame_brand, text=f"v{AppConfig.APP_VERSION}", font=("Helvetica", 9, "bold"), fg=self.COLOR_ACCENT, bg=self.COLOR_HEADER)
            lbl_subbrand.pack(side="top", anchor="w")

        self.frame_steps = tk.Frame(self.frame_top, bg=self.COLOR_HEADER)
        self.frame_steps.pack(side="right", padx=20, pady=15)

        self.lbl_step_trackers: List[tk.Label] = []
        pasos_nombres = ["❶ Origen", "❷ Filtros", "❸ Reglas", "❹ Ejecutar", "❺ Respaldo"]

        for nombre_step in pasos_nombres:
            lbl_st = tk.Label(
                self.frame_steps, text=nombre_step, font=("Helvetica", 9, "bold"),
                fg="#9CA3AF", bg=self.COLOR_HEADER, padx=8, pady=4
            )
            lbl_st.pack(side="left", padx=2)
            self.lbl_step_trackers.append(lbl_st)

        # Contenedor central
        self.container = ttk.Frame(self.root, padding=15)
        self.container.pack(fill="both", expand=True)

        self.frame_paso0 = ttk.Frame(self.container)
        self.frame_paso1 = ttk.Frame(self.container)
        self.frame_paso2 = ttk.Frame(self.container)
        self.frame_paso3 = ttk.Frame(self.container)
        self.frame_paso4 = ttk.Frame(self.container)
        self.frame_paso5 = ttk.Frame(self.container)

        self._construir_paso0_bienvenida()
        self._construir_paso1()
        self._construir_paso2()
        self._construir_paso3()
        self._construir_paso4()
        self._construir_paso5()

        # Footer Bar
        ttk.Separator(self.root, orient="horizontal").pack(fill="x", padx=10, pady=2)
        self.frame_bot = ttk.Frame(self.root, padding=10)
        self.frame_bot.pack(fill="x")

        self.btn_cancelar = ttk.Button(self.frame_bot, text="Cancelar", command=self._cancelar)
        self.btn_cancelar.pack(side="left", padx=5)

        self.btn_reiniciar = ttk.Button(self.frame_bot, text="🏠 Inicio", command=self._volver_a_bienvenida)

        self.btn_ejecutar = tk.Button(
            self.frame_bot, text="🚀 EJECUTAR AHORA", font=("Helvetica", 10, "bold"),
            bg=self.COLOR_SUCCESS, fg="#FFFFFF", activebackground="#047857",
            relief="flat", padx=15, pady=4, command=self._iniciar_ejecucion_hilo
        )

        self.btn_siguiente = tk.Button(
            self.frame_bot, text="Siguiente ▶", font=("Helvetica", 9, "bold"),
            bg=self.COLOR_PRIMARY, fg="#FFFFFF", activebackground="#991B1B",
            relief="flat", padx=12, pady=4, command=self._siguiente
        )
        self.btn_siguiente.pack(side="right", padx=5)

        self.btn_anterior = ttk.Button(self.frame_bot, text="◀ Anterior", command=self._anterior)
        self.btn_anterior.pack(side="right", padx=5)

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

    def _construir_paso0_bienvenida(self):
        lbl_welcome_title = tk.Label(
            self.frame_paso0, text="🇲🇽 MEMEXICANÍSIMOS FILES — ¿Qué deseas hacer hoy?",
            font=("Helvetica", 14, "bold"), fg=self.COLOR_TEXT, bg=self.COLOR_BG
        )
        lbl_welcome_title.pack(pady=(15, 5))

        lbl_welcome_sub = tk.Label(
            self.frame_paso0, text="Selecciona un modo para comenzar a gestionar o respaldar tus archivos:",
            font=("Helvetica", 10), fg=self.COLOR_SUBTEXT, bg=self.COLOR_BG
        )
        lbl_welcome_sub.pack(pady=(0, 25))

        frame_cards = tk.Frame(self.frame_paso0, bg=self.COLOR_BG)
        frame_cards.pack(fill="both", expand=True, padx=10)

        # Tarjeta 1
        card1 = tk.Frame(frame_cards, bg=self.COLOR_PANEL, highlightbackground=self.COLOR_BORDER, highlightthickness=1, padx=15, pady=20)
        card1.pack(side="left", fill="both", expand=True, padx=8)
        tk.Label(card1, text="📁", font=("Helvetica", 32), bg=self.COLOR_PANEL).pack(pady=(0, 10))
        tk.Label(card1, text="Organizar Archivos", font=("Helvetica", 12, "bold"), fg=self.COLOR_TEXT, bg=self.COLOR_PANEL).pack(pady=(0, 5))
        tk.Label(card1, text="Wizard guiado para clasificar fotos y documentos por fecha, tipo o patrones.", font=("Helvetica", 9), fg=self.COLOR_SUBTEXT, bg=self.COLOR_PANEL, wraplength=200, justify="center").pack(fill="y", expand=True, pady=(0, 15))
        tk.Button(card1, text="Comenzar Wizard ▶", font=("Helvetica", 9, "bold"), bg=self.COLOR_PRIMARY, fg="#FFFFFF", relief="flat", padx=10, pady=6, command=self._iniciar_wizard_modo).pack(side="bottom")

        # Tarjeta 2
        card2 = tk.Frame(frame_cards, bg=self.COLOR_PANEL, highlightbackground=self.COLOR_BORDER, highlightthickness=1, padx=15, pady=20)
        card2.pack(side="left", fill="both", expand=True, padx=8)
        tk.Label(card2, text="🚀", font=("Helvetica", 32), bg=self.COLOR_PANEL).pack(pady=(0, 10))
        tk.Label(card2, text="Clonar / Respaldo Rápido", font=("Helvetica", 12, "bold"), fg=self.COLOR_TEXT, bg=self.COLOR_PANEL).pack(pady=(0, 5))
        tk.Label(card2, text="Copia exacta o incremental de carpetas completas y personales.", font=("Helvetica", 9), fg=self.COLOR_SUBTEXT, bg=self.COLOR_PANEL, wraplength=200, justify="center").pack(fill="y", expand=True, pady=(0, 15))
        tk.Button(card2, text="Clonar Ahora 🚀", font=("Helvetica", 9, "bold"), bg=self.COLOR_SUCCESS, fg="#FFFFFF", relief="flat", padx=10, pady=6, command=self._iniciar_clonador_modo).pack(side="bottom")

        # Tarjeta 3
        card3 = tk.Frame(frame_cards, bg=self.COLOR_PANEL, highlightbackground=self.COLOR_BORDER, highlightthickness=1, padx=15, pady=20)
        card3.pack(side="left", fill="both", expand=True, padx=8)
        tk.Label(card3, text="🧹", font=("Helvetica", 32), bg=self.COLOR_PANEL).pack(pady=(0, 10))
        tk.Label(card3, text="Limpieza Rápida", font=("Helvetica", 12, "bold"), fg=self.COLOR_TEXT, bg=self.COLOR_PANEL).pack(pady=(0, 5))
        tk.Label(card3, text="Detecta y elimina carpetas vacías en directorios seleccionados.", font=("Helvetica", 9), fg=self.COLOR_SUBTEXT, bg=self.COLOR_PANEL, wraplength=200, justify="center").pack(fill="y", expand=True, pady=(0, 15))
        tk.Button(card3, text="Limpiar Directorio 🧹", font=("Helvetica", 9, "bold"), bg=self.COLOR_ACCENT, fg="#FFFFFF", relief="flat", padx=10, pady=6, command=self._iniciar_limpieza_modo).pack(side="bottom")

    def _construir_paso1(self):
        card_rutas = tk.Frame(self.frame_paso1, bg=self.COLOR_PANEL, highlightbackground=self.COLOR_BORDER, highlightthickness=1, padx=15, pady=15)
        card_rutas.pack(fill="x", pady=(5, 10))

        tk.Label(card_rutas, text="Carpeta de Origen:", font=("Helvetica", 10, "bold"), bg=self.COLOR_PANEL).grid(row=0, column=0, sticky="w", pady=5)
        self.entry_origen = ttk.Entry(card_rutas, width=50)
        self.entry_origen.grid(row=0, column=1, padx=8, sticky="ew")
        self.entry_origen.bind("<KeyRelease>", lambda e: self._validar_rutas_paso1())

        btn_exam_orig = tk.Button(card_rutas, text="📁 Examinar...", bg="#ECFDF5", fg="#059669", font=("Helvetica", 9, "bold"), relief="flat", command=self._examinar_origen)
        btn_exam_orig.grid(row=0, column=2, padx=5)

        tk.Label(card_rutas, text="Carpeta de Destino:", font=("Helvetica", 10, "bold"), bg=self.COLOR_PANEL).grid(row=1, column=0, sticky="w", pady=5)
        self.entry_destino = ttk.Entry(card_rutas, width=50)
        self.entry_destino.grid(row=1, column=1, padx=8, sticky="ew")
        self.entry_destino.bind("<KeyRelease>", lambda e: self._validar_rutas_paso1())

        btn_exam_dest = tk.Button(card_rutas, text="📁 Examinar...", bg="#ECFDF5", fg="#059669", font=("Helvetica", 9, "bold"), relief="flat", command=self._examinar_destino)
        btn_exam_dest.grid(row=1, column=2, padx=5)
        card_rutas.columnconfigure(1, weight=1)

        frame_det_btns = tk.Frame(self.frame_paso1, bg=self.COLOR_BG)
        frame_det_btns.pack(anchor="w", pady=8)
        tk.Button(frame_det_btns, text="🔌 Detectar USB Extraíble", bg="#FEF3C7", fg="#B45309", font=("Helvetica", 9, "bold"), relief="flat", command=self._detectar_unidad_extraible).pack(side="left", padx=(0, 8))
        tk.Button(frame_det_btns, text="📷 Detectar Cámara / Celular (MTP)", bg="#EFF6FF", fg="#2563EB", font=("Helvetica", 9, "bold"), relief="flat", command=self._detectar_dispositivos_multimedia_gui).pack(side="left", padx=5)

        card_modo = tk.Frame(self.frame_paso1, bg=self.COLOR_PANEL, highlightbackground=self.COLOR_BORDER, highlightthickness=1, padx=15, pady=15)
        card_modo.pack(fill="x", pady=10)
        tk.Label(card_modo, text="Selecciona el Modo de Operación:", font=("Helvetica", 10, "bold"), bg=self.COLOR_PANEL).pack(anchor="w", pady=(0, 10))

        frame_modo_cards = tk.Frame(card_modo, bg=self.COLOR_PANEL)
        frame_modo_cards.pack(fill="x")

        self.btn_modo_copiar = tk.Button(
            frame_modo_cards, text="📋 Copiar Archivos\n(Recomendado: Preserva originales)",
            font=("Helvetica", 9, "bold"), bg="#D1FAE5", fg="#065F46", relief="solid", borderwidth=2,
            padx=15, pady=10, command=lambda: self._seleccionar_modo_tarjeta("Copiar")
        )
        self.btn_modo_copiar.pack(side="left", fill="both", expand=True, padx=(0, 8))

        self.btn_modo_mover = tk.Button(
            frame_modo_cards, text="🚚 Mover Archivos\n(⚠️ Precaución: Borra del origen)",
            font=("Helvetica", 9, "bold"), bg="#F3F4F6", fg="#374151", relief="solid", borderwidth=1,
            padx=15, pady=10, command=lambda: self._seleccionar_modo_tarjeta("Mover")
        )
        self.btn_modo_mover.pack(side="left", fill="both", expand=True, padx=(8, 0))

    def _seleccionar_modo_tarjeta(self, modo: str):
        self.var_modo.set(modo)
        if modo == "Copiar":
            self.btn_modo_copiar.config(bg="#D1FAE5", fg="#065F46", borderwidth=2)
            self.btn_modo_mover.config(bg="#F3F4F6", fg="#374151", borderwidth=1)
        else:
            self.btn_modo_copiar.config(bg="#F3F4F6", fg="#374151", borderwidth=1)
            self.btn_modo_mover.config(bg="#FEE2E2", fg="#991B1B", borderwidth=2)

    def _construir_paso2(self):
        # Categorías en 3 columnas
        lf_cats = ttk.LabelFrame(self.frame_paso2, text=" Categorías de archivos a incluir ", padding=12)
        lf_cats.pack(fill="x", pady=5)
        ttk.Checkbutton(lf_cats, text="✓ Todos los archivos (sin filtro)", variable=self.var_cat_todos, command=self._al_cambiar_cat_todos).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        col_idx, row_idx = 0, 1
        for cat_nombre, var_cat in self.vars_categorias.items():
            chk = ttk.Checkbutton(lf_cats, text=cat_nombre, variable=var_cat, command=self._al_cambiar_cat_individual)
            chk.grid(row=row_idx, column=col_idx, sticky="w", padx=15, pady=4)
            col_idx += 1
            if col_idx > 2:
                col_idx, row_idx = 0, row_idx + 1

        # Opciones avanzadas con Checkboxes corregidos (T2.3)
        lf_avanzadas = ttk.LabelFrame(self.frame_paso2, text=" Opciones de procesamiento ", padding=12)
        lf_avanzadas.pack(fill="x", pady=8)
        ttk.Checkbutton(lf_avanzadas, text="Incluir subcarpetas (recursivo)", variable=self.var_subcarpetas).pack(anchor="w", pady=2)
        ttk.Checkbutton(lf_avanzadas, text="Usar metadatos EXIF para fechas de fotos", variable=self.var_exif).pack(anchor="w", pady=2)
        ttk.Checkbutton(lf_avanzadas, text="Detección inteligente de duplicados por hash MD5", variable=self.var_hash).pack(anchor="w", pady=2)
        # Checkboxes agregados T2.3
        ttk.Checkbutton(lf_avanzadas, text="Incluir archivos y carpetas ocultas", variable=self.var_incluir_ocultos).pack(anchor="w", pady=2)
        ttk.Checkbutton(lf_avanzadas, text="Usar fecha de creación (ctime) en lugar de modificación (mtime)", variable=self.var_usar_creacion_filtro).pack(anchor="w", pady=2)

        lf_filt_av = ttk.LabelFrame(self.frame_paso2, text=" Filtros por tamaño, fecha y nombre (Regex) ", padding=12)
        lf_filt_av.pack(fill="x", pady=5)
        frame_tamanos = ttk.Frame(lf_filt_av)
        frame_tamanos.pack(fill="x", pady=3)
        ttk.Label(frame_tamanos, text="Tamaño mín (MB):").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame_tamanos, textvariable=self.var_tamano_min, width=8).grid(row=0, column=1, padx=5)
        ttk.Label(frame_tamanos, text="Tamaño máx (MB):").grid(row=0, column=2, sticky="w", padx=(15, 0))
        ttk.Entry(frame_tamanos, textvariable=self.var_tamano_max, width=8).grid(row=0, column=3, padx=5)
        ttk.Label(frame_tamanos, text="Antigüedad máx (días):").grid(row=0, column=4, sticky="w", padx=(15, 0))
        ttk.Spinbox(frame_tamanos, from_=0, to=9999, textvariable=self.var_dias_antiguedad, width=6).grid(row=0, column=5, padx=5)

        frame_regex = tk.Frame(lf_filt_av, bg=self.COLOR_PANEL)
        frame_regex.pack(fill="x", pady=(10, 2))
        tk.Label(frame_regex, text="Patrón Regex para filtrar por nombre (opcional):", font=("Helvetica", 9, "bold"), bg=self.COLOR_PANEL).pack(anchor="w")
        ttk.Entry(frame_regex, textvariable=self.var_patron_regex).pack(fill="x", pady=3)

        # Atajos Regex Completados para los 12 meses (T2.5)
        frame_regex_shortcuts = tk.Frame(frame_regex, bg=self.COLOR_PANEL)
        frame_regex_shortcuts.pack(fill="x", pady=2)
        tk.Button(frame_regex_shortcuts, text="[ Solo Imágenes ]", font=("Helvetica", 8), bg="#EFF6FF", fg="#2563EB", relief="flat", command=lambda: self.var_patron_regex.set(r"\.(jpg|jpeg|png|gif)$")).pack(side="left", padx=(0, 4))
        tk.Button(frame_regex_shortcuts, text="[ Fotos WhatsApp ]", font=("Helvetica", 8), bg="#EFF6FF", fg="#2563EB", relief="flat", command=lambda: self.var_patron_regex.set(r"^IMG-?[0-9]{8}-WA")).pack(side="left", padx=4)
        tk.Button(frame_regex_shortcuts, text="[ Documentos 12 Meses ]", font=("Helvetica", 8), bg="#EFF6FF", fg="#2563EB", relief="flat", command=lambda: self.var_patron_regex.set(r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)")).pack(side="left", padx=4)
        tk.Button(frame_regex_shortcuts, text="[ Limpiar Regex ]", font=("Helvetica", 8), bg="#FEE2E2", fg="#991B1B", relief="flat", command=lambda: self.var_patron_regex.set("")).pack(side="left", padx=4)

    def _construir_paso3(self):
        frame_left = ttk.Frame(self.frame_paso3)
        frame_left.pack(side="left", fill="both", expand=True, padx=(0, 5))

        lf_crit = ttk.LabelFrame(frame_left, text=" Criterios de organización ", padding=10)
        lf_crit.pack(fill="x", pady=(0, 5))
        ttk.Combobox(lf_crit, textvariable=self.var_criterio_primario, values=["Fecha", "Tipo de archivo", "Nombre", "Ninguno"], state="readonly").pack(fill="x", pady=3)
        ttk.Checkbutton(lf_crit, text="Activar nivel secundario", variable=self.var_usar_secundario, command=self._al_cambiar_criterios_paso3).pack(anchor="w", pady=2)
        self.cb_criterio_secundario = ttk.Combobox(lf_crit, textvariable=self.var_criterio_secundario, values=["Fecha", "Tipo de archivo", "Nombre"], state="readonly")
        self.cb_criterio_secundario.pack(fill="x", pady=3)

        # CORRECCIÓN DE BUG T2.3: Se agrega .pack() explícito a los LabelFrames
        self.lf_formato_fecha = ttk.LabelFrame(frame_left, text=" Formato de carpeta de fecha ", padding=10)
        self.lf_formato_fecha.pack(fill="x", pady=5)  # FIX T2.3
        self.combo_formato_fecha = ttk.Combobox(self.lf_formato_fecha, textvariable=self.var_formato_fecha_combo, values=["YYYY/MM", "YYYY-MM", "YYYY/MM/DD", "YYYY-MM-DD", "MM/YYYY", "MMMM YYYY"], state="readonly")
        self.combo_formato_fecha.pack(fill="x", pady=2)
        self.combo_formato_fecha.bind("<<ComboboxSelected>>", lambda e: self._actualizar_visor_paso3())

        self.lf_renombrado = ttk.LabelFrame(frame_left, text=" Renombrado de archivos ", padding=10)
        self.lf_renombrado.pack(fill="x", pady=5)  # FIX T2.3
        ttk.Checkbutton(self.lf_renombrado, text="Activar renombrado al copiar/mover", variable=self.var_activar_renombrado, command=self._al_cambiar_renombrado).pack(anchor="w", pady=2)
        ttk.Entry(self.lf_renombrado, textvariable=self.var_plantilla_nombre).pack(fill="x", pady=2)

        # Treeview visor
        frame_right = ttk.Frame(self.frame_paso3)
        frame_right.pack(side="right", fill="both", expand=True, padx=(5, 0))
        lf_visor = ttk.LabelFrame(frame_right, text=" Vista previa en vivo ", padding=10)
        lf_visor.pack(fill="both", expand=True)

        self.tree_visor = ttk.Treeview(lf_visor, show="tree", height=10)
        self.tree_visor.pack(fill="both", expand=True, pady=(0, 8))

        card_sim = tk.Frame(lf_visor, bg=self.COLOR_PANEL, highlightbackground=self.COLOR_BORDER, highlightthickness=1, padx=10, pady=8)
        card_sim.pack(fill="x")
        tk.Label(card_sim, text="Simulación de archivo:", font=("Helvetica", 9, "bold"), bg=self.COLOR_PANEL).pack(anchor="w")
        self.lbl_sim_antes = tk.Label(card_sim, text="Antes: mi_foto.jpg", font=("Helvetica", 8), fg=self.COLOR_SUBTEXT, bg=self.COLOR_PANEL)
        self.lbl_sim_antes.pack(anchor="w")
        self.lbl_sim_despues = tk.Label(card_sim, text="Después: destino/2024/05/mi_foto.jpg", font=("Helvetica", 9, "bold"), fg=self.COLOR_SUCCESS, bg=self.COLOR_PANEL)
        self.lbl_sim_despues.pack(anchor="w")
        # Traces para refrescar simulador del Paso 3 en tiempo real
        self.var_criterio_primario.trace_add("write", lambda *args: self._actualizar_visor_paso3())
        self.var_usar_secundario.trace_add("write", lambda *args: self._actualizar_visor_paso3())
        self.var_criterio_secundario.trace_add("write", lambda *args: self._actualizar_visor_paso3())
        self.var_formato_fecha_combo.trace_add("write", lambda *args: self._actualizar_visor_paso3())
        self.var_plantilla_nombre.trace_add("write", lambda *args: self._actualizar_visor_paso3())
        self._actualizar_visor_paso3()

    def _construir_paso4(self):
        self.lf_resumen = ttk.LabelFrame(self.frame_paso4, text=" Resumen de configuración ", padding=10)
        self.lf_resumen.pack(fill="x", pady=(0, 5))
        self.lbl_resumen_origen = ttk.Label(self.lf_resumen, text="Origen: -")
        self.lbl_resumen_origen.pack(anchor="w")
        self.lbl_resumen_destino = ttk.Label(self.lf_resumen, text="Destino: -")
        self.lbl_resumen_destino.pack(anchor="w")
        self.lbl_resumen_modo = ttk.Label(self.lf_resumen, text="Modo: -")
        self.lbl_resumen_modo.pack(anchor="w")

        frame_accion_paso4 = tk.Frame(self.frame_paso4, bg=self.COLOR_BG)
        frame_accion_paso4.pack(fill="x", pady=6)
        self.btn_analizar = tk.Button(frame_accion_paso4, text="🔍 Analizar y Previsualizar", bg=self.COLOR_SUCCESS, fg="#FFFFFF", font=("Helvetica", 9, "bold"), relief="flat", padx=10, pady=4, command=self._analizar_paso4)
        self.btn_analizar.pack(side="left")

        self.lbl_estado_analisis = ttk.Label(frame_accion_paso4, text="", font=("Helvetica", 9, "bold"), foreground=self.COLOR_ACCENT)
        self.lbl_estado_analisis.pack(side="left", padx=10)

        paned = ttk.PanedWindow(self.frame_paso4, orient="vertical")
        paned.pack(fill="both", expand=True, pady=5)
        frame_tree_container = ttk.Frame(paned)
        paned.add(frame_tree_container, weight=2)

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

        self.tree.tag_configure("MOVER", background="#D1FAE5", foreground="#065F46")
        self.tree.tag_configure("COPIAR", background="#D1FAE5", foreground="#065F46")
        self.tree.tag_configure("DUPLICADO", background="#FEF3C7", foreground="#92400E")
        self.tree.tag_configure("ERROR", background="#FEE2E2", foreground="#991B1B")

        frame_log_container = ttk.LabelFrame(paned, text=" Registro de Operaciones en Vivo (Log) ", padding=5)
        paned.add(frame_log_container, weight=1)
        self.log_text = scrolledtext.ScrolledText(frame_log_container, height=5, state="normal")
        self.log_text.pack(fill="both", expand=True)

    def _construir_paso5(self):
        ttk.Label(self.frame_paso5, text="Herramientas Avanzadas de Respaldo y Clonación:", font=("Helvetica", 11, "bold")).pack(anchor="w", pady=(0, 10))
        notebook_paso5 = ttk.Notebook(self.frame_paso5)
        notebook_paso5.pack(fill="both", expand=True)

        tab_carpeta = ttk.Frame(notebook_paso5, padding=12)
        notebook_paso5.add(tab_carpeta, text="📁 Clonar Carpeta Incremental")

        grid_c = ttk.Frame(tab_carpeta)
        grid_c.pack(fill="x", pady=5)
        ttk.Label(grid_c, text="Carpeta Origen:").grid(row=0, column=0, sticky="w", pady=5)
        self.entry_clone_orig = ttk.Entry(grid_c, width=45)
        self.entry_clone_orig.grid(row=0, column=1, padx=5, sticky="ew")
        ttk.Button(grid_c, text="Examinar...", command=lambda: self._examinar_generico(self.entry_clone_orig)).grid(row=0, column=2)

        ttk.Label(grid_c, text="Carpeta Destino:").grid(row=1, column=0, sticky="w", pady=5)
        self.entry_clone_dest = ttk.Entry(grid_c, width=45)
        self.entry_clone_dest.grid(row=1, column=1, padx=5, sticky="ew")
        ttk.Button(grid_c, text="Examinar...", command=lambda: self._examinar_generico(self.entry_clone_dest)).grid(row=1, column=2)
        grid_c.columnconfigure(1, weight=1)

        self.var_clone_inc = tk.BooleanVar(value=True)
        ttk.Checkbutton(tab_carpeta, text="Modo Incremental (Solo copiar archivos nuevos/modificados)", variable=self.var_clone_inc).pack(anchor="w", pady=8)
        
        self.btn_iniciar_clonacion = tk.Button(
            tab_carpeta, text="▶ Iniciar Clonación de Carpeta", bg=self.COLOR_SUCCESS, fg="#FFFFFF",
            font=("Helvetica", 9, "bold"), relief="flat", padx=12, pady=6, command=self._ejecutar_clonacion_carpeta_gui
        )
        self.btn_iniciar_clonacion.pack(anchor="w", pady=(5, 15))

        # Tarjeta visual de progreso de clonación
        self.card_progreso_clone = tk.Frame(tab_carpeta, bg=self.COLOR_PANEL, highlightbackground=self.COLOR_BORDER, highlightthickness=1, padx=15, pady=12)
        self.card_progreso_clone.pack(fill="x", pady=5)

        frame_header_clone = tk.Frame(self.card_progreso_clone, bg=self.COLOR_PANEL)
        frame_header_clone.pack(fill="x", pady=(0, 5))

        self.lbl_clone_porcentaje = tk.Label(frame_header_clone, text="0.0%", font=("Helvetica", 14, "bold"), fg=self.COLOR_PRIMARY, bg=self.COLOR_PANEL)
        self.lbl_clone_porcentaje.pack(side="left")

        self.lbl_clone_contadores = tk.Label(frame_header_clone, text="Esperando inicio...", font=("Helvetica", 9, "bold"), fg=self.COLOR_SUBTEXT, bg=self.COLOR_PANEL)
        self.lbl_clone_contadores.pack(side="right")

        self.progress_clone = ttk.Progressbar(self.card_progreso_clone, orient="horizontal", mode="determinate")
        self.progress_clone.pack(fill="x", pady=5)

        self.lbl_clone_archivo_actual = tk.Label(self.card_progreso_clone, text="", font=("Helvetica", 8), fg=self.COLOR_SUBTEXT, bg=self.COLOR_PANEL, anchor="w", justify="left")
        self.lbl_clone_archivo_actual.pack(fill="x", pady=(2, 5))

        self.btn_cancelar_clone = tk.Button(
            self.card_progreso_clone, text="⏹ Cancelar Clonación", bg=self.COLOR_PRIMARY, fg="#FFFFFF",
            font=("Helvetica", 8, "bold"), relief="flat", padx=8, pady=3, state="disabled", command=self._cancelar_clonacion_gui
        )
        self.btn_cancelar_clone.pack(anchor="e")

    # ---------------------------------------------------------
    # DESACOPLAMIENTO Y CONSUMO DE BACKEND (T2.1 & T2.2)
    # ---------------------------------------------------------
    def _analizar_paso4(self):
        if not self.origen or not self.destino:
            messagebox.showerror("Rutas Faltantes", "Por favor seleccione Origen y Destino en el Paso 1.")
            return

        for item in self.tree.get_children():
            self.tree.delete(item)

        self.lbl_estado_analisis.config(text="Generando plan...", foreground=self.COLOR_ACCENT)
        self.btn_analizar.config(state="disabled")

        exts_res = []
        if not self.filtros.get("todos", True):
            for cat in self.filtros.get("categorias", []):
                if cat in CATEGORIAS_EXT:
                    exts_res.extend(CATEGORIAS_EXT[cat])

        self.ejecutando = True

        filtros_av = {
            'tamano_min_bytes': self.filtros.get('tamano_min_bytes'),
            'tamano_max_bytes': self.filtros.get('tamano_max_bytes'),
            'dias_antiguedad': self.filtros.get('dias_antiguedad'),
            'incluir_ocultos': self.filtros.get('incluir_ocultos', False),
            'patron_regex': self.filtros.get('patron_regex'),
            'usar_creacion_filtro': self.filtros.get('usar_creacion_filtro', False),
        }

        def _hilo_analizar():
            res: ServiceResult = generar_plan_con_estructura(
                origen=self.origen, destino_base=self.destino, extensiones=exts_res or None,
                incluir_subcarpetas=self.filtros.get("incluir_subcarpetas", True),
                usar_exif=self.filtros.get("usar_exif", True),
                usar_hash_duplicados=self.filtros.get("usar_hash", False),
                estructura=self.estructura, filtros_avanzados=filtros_av
            )
            self.cola_eventos.put(('FIN_GENERAR_PLAN', res))

        threading.Thread(target=_hilo_analizar, daemon=True).start()

    def _iniciar_ejecucion_hilo(self):
        if not self.planes_actuales:
            messagebox.showinfo("Sin Archivos", "Genere un plan primero en el Paso 4.")
            return

        modo_actual = self.var_modo.get()
        if not messagebox.askyesno("Confirmar Operación", f"¿Desea {modo_actual.lower()} {len(self.planes_actuales)} archivos?"):
            return

        self.ejecutando = True
        self.cancelar = False
        self.btn_ejecutar.config(state="disabled")
        self.btn_analizar.config(state="disabled")

        def _hilo_ejecutar():
            # DESACOPLAMIENTO T2.1: Llamada directa a core.ejecutar_plan_con_modo
            res: ServiceResult = ejecutar_plan_con_modo(
                planes=self.planes_actuales,
                modo=modo_actual,
                callback_progreso=lambda i, total, nom: self.cola_eventos.put(('PROGRESO_PROCESADO', (i, nom))),
                cancelar_flag=lambda: self.cancelar
            )
            self.cola_eventos.put(('FIN_EJECUCION', res))

        threading.Thread(target=_hilo_ejecutar, daemon=True).start()

    def _procesar_cola_eventos(self):
        try:
            while True:
                tipo, datos = self.cola_eventos.get_nowait()

                if tipo == 'FIN_GENERAR_PLAN':
                    res: ServiceResult = datos
                    self.ejecutando = False
                    self.btn_analizar.config(state="normal")

                    # MAPEO DE ESTADOS UX T2.2
                    if not res.success:
                        self.lbl_estado_analisis.config(text=f"Error: {res.error_code}", foreground=self.COLOR_PRIMARY)
                        messagebox.showerror("Error en Análisis", f"Error [{res.error_code}]:\n{res.error}")
                    else:
                        self.planes_actuales = res.data
                        self.lbl_estado_analisis.config(text=f"Plan listo: {len(res.data)} archivos", foreground=self.COLOR_SUCCESS)
                        self.btn_ejecutar.config(state="normal" if res.data else "disabled")

                        for p in res.data:
                            acc = p['accion'].upper()
                            tag = acc if acc in ("MOVER", "COPIAR", "DUPLICADO") else "ERROR"
                            self.tree.insert("", "end", values=(p['origen'].name, acc, str(p['destino']), str(p['fecha'])), tags=(tag,))

                elif tipo == 'FIN_EJECUCION':
                    res: ServiceResult = datos
                    self.ejecutando = False
                    self.btn_analizar.config(state="normal")
                    self.btn_ejecutar.config(state="normal")

                    if not res.success and res.error_code == ErrorCode.ERR_EXECUTION_CANCELLED:
                        self.lbl_estado_analisis.config(text="⚠️ Operación cancelada por el usuario.", foreground=self.COLOR_ACCENT)
                        messagebox.showwarning("Operación Cancelada", "La ejecución fue cancelada por el usuario.")
                    elif not res.success:
                        self.lbl_estado_analisis.config(text=f"❌ Error: {res.error_code}", foreground=self.COLOR_PRIMARY)
                        messagebox.showerror("Error en Ejecución", f"Error [{res.error_code}]:\n{res.error}")
                    else:
                        d_res = res.data if isinstance(res.data, dict) else {}
                        exitos = d_res.get('exitos', len(self.planes_actuales))
                        errores = d_res.get('errores', 0)
                        self.lbl_estado_analisis.config(
                            text=f"✅ Ejecución completada: {exitos} exitosos | {errores} errores",
                            foreground=self.COLOR_SUCCESS
                        )
                        messagebox.showinfo(
                            "Ejecución Finalizada",
                            f"Operación finalizada con éxito:\n"
                            f"• Archivos procesados: {exitos}\n"
                            f"• Errores: {errores}"
                        )

                elif tipo == 'PROGRESO_PROCESADO':
                    i, nombre = datos
                    self.lbl_estado_analisis.config(text=f"Procesando [{i}/{len(self.planes_actuales)}]: {nombre}")

                elif tipo == 'PROGRESO_CLONACION':
                    i, total, b_cop, b_tot, nombre = datos
                    pct = (b_cop / b_tot * 100) if b_tot > 0 else (i / total * 100) if total > 0 else 0
                    self.progress_clone["value"] = pct
                    self.lbl_clone_porcentaje.config(text=f"{pct:.1f}%")

                    gb_cop = b_cop / (1024 ** 3)
                    gb_tot = b_tot / (1024 ** 3)
                    if b_tot > 0:
                        self.lbl_clone_contadores.config(text=f"[{i} / {total} archivos] ({gb_cop:.2f} GB / {gb_tot:.2f} GB)")
                    else:
                        self.lbl_clone_contadores.config(text=f"[{i} / {total} archivos]")

                    self.lbl_clone_archivo_actual.config(text=f"Copiando: {nombre}")

                elif tipo == 'FIN_CLONACION':
                    res: ServiceResult = datos
                    self.ejecutando_clonacion = False
                    self.btn_iniciar_clonacion.config(state="normal")
                    self.btn_cancelar_clone.config(state="disabled")

                    if not res.success and res.error_code == ErrorCode.ERR_EXECUTION_CANCELLED:
                        self.lbl_clone_archivo_actual.config(text="⚠️ Clonación cancelada por el usuario.")
                        messagebox.showwarning("Clonación Cancelada", "La clonación fue detenida por el usuario.")
                    elif not res.success:
                        self.lbl_clone_archivo_actual.config(text=f"❌ Error: {res.error}")
                        messagebox.showerror("Error de Clonación", f"Error [{res.error_code}]:\n{res.error}")
                    else:
                        d_res = res.data or {}
                        self.progress_clone["value"] = 100
                        self.lbl_clone_porcentaje.config(text="100.0%")
                        self.lbl_clone_archivo_actual.config(text="✅ Clonación completada con éxito.")
                        messagebox.showinfo(
                            "Clonación Finalizada",
                            f"Clonación completada exitosamente:\n"
                            f"• Copiados: {d_res.get('copiados', 0)}\n"
                            f"• Incremental omitidos: {d_res.get('omitidos', 0)}\n"
                            f"• Errores: {d_res.get('errores', 0)}"
                        )

        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._procesar_cola_eventos)

    # ---------------------------------------------------------
    # PERSISTENCIA REAL DE CONFIGURACIÓN Y PERFILES (T2.4)
    # ---------------------------------------------------------
    def _cargar_configuracion(self):
        if AppConfig.CONFIG_FILE.exists():
            try:
                with open(AppConfig.CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    self.origen = cfg.get("origen", "")
                    self.destino = cfg.get("destino", "")
                    if self.origen:
                        self.entry_origen.insert(0, self.origen)
                    if self.destino:
                        self.entry_destino.insert(0, self.destino)
                    self._validar_rutas_paso1()
            except Exception:
                pass

    def _guardar_configuracion(self):
        try:
            cfg = {"origen": self.entry_origen.get().strip(), "destino": self.entry_destino.get().strip()}
            with open(AppConfig.CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4)
        except Exception:
            pass

    def _guardar_perfil(self):
        nom = simpledialog.askstring("Guardar Perfil", "Nombre para el perfil:")
        if nom:
            self._guardar_filtros_paso2()
            self._guardar_estructura_paso3()
            # FIX T2.4: Guardar filtros reales seleccionados
            perfil = {
                "nombre": nom,
                "origen": self.entry_origen.get().strip(),
                "destino": self.entry_destino.get().strip(),
                "modo": self.var_modo.get(),
                "filtros": self.filtros,
                "estructura": self.estructura
            }
            try:
                perfiles = []
                if AppConfig.PERFILES_FILE.exists():
                    with open(AppConfig.PERFILES_FILE, "r", encoding="utf-8") as f:
                        perfiles = json.load(f)
                perfiles = [p for p in perfiles if p.get("nombre") != nom]
                perfiles.append(perfil)
                with open(AppConfig.PERFILES_FILE, "w", encoding="utf-8") as f:
                    json.dump(perfiles, f, indent=4, ensure_ascii=False)
                messagebox.showinfo("Perfil Guardado", f"Perfil '{nom}' guardado con éxito.")
            except Exception as e:
                messagebox.showerror("Error Perfil", f"No se pudo guardar el perfil: {e}")

    def _cargar_perfil(self):
        if AppConfig.PERFILES_FILE.exists():
            try:
                with open(AppConfig.PERFILES_FILE, "r", encoding="utf-8") as f:
                    perfiles = json.load(f)
                if perfiles:
                    p = perfiles[-1]
                    self.estructura = p.get("estructura", {})
                    self._al_cambiar_criterios_paso3()
                    messagebox.showinfo("Perfil", f"Perfil '{p.get('nombre')}' cargado.")
            except Exception:
                pass

    def _iniciar_wizard_modo(self):
        self.paso_actual = 1
        self._actualizar_estado_paso()

    def _iniciar_clonador_modo(self):
        self.paso_actual = 5
        self._actualizar_estado_paso()

    def _iniciar_limpieza_modo(self):
        d = filedialog.askdirectory(title="Seleccionar Carpeta para Limpieza Rápida")
        if d:
            eliminadas = limpiar_carpetas_vacias(d, dry_run=False)
            messagebox.showinfo("Limpieza Completada", f"Se eliminaron {len(eliminadas)} carpetas vacías.")

    def _volver_a_bienvenida(self):
        self.paso_actual = 0
        self._actualizar_estado_paso()

    def _actualizar_estado_paso(self):
        self.frame_paso0.pack_forget()
        self.frame_paso1.pack_forget()
        self.frame_paso2.pack_forget()
        self.frame_paso3.pack_forget()
        self.frame_paso4.pack_forget()
        self.frame_paso5.pack_forget()

        for i, lbl in enumerate(self.lbl_step_trackers, start=1):
            if i == self.paso_actual:
                lbl.config(fg="#FFFFFF", bg=self.COLOR_PRIMARY)
            elif i < self.paso_actual:
                lbl.config(fg="#FBBF24", bg=self.COLOR_HEADER)
            else:
                lbl.config(fg="#9CA3AF", bg=self.COLOR_HEADER)

        if self.paso_actual == 0:
            self.frame_paso0.pack(fill="both", expand=True)
            self.btn_anterior.config(state="disabled")
            self.btn_siguiente.pack_forget()
            self.btn_ejecutar.pack_forget()
            self.btn_reiniciar.pack_forget()

        elif self.paso_actual == 1:
            self.frame_paso1.pack(fill="both", expand=True)
            self.btn_anterior.config(state="disabled")
            self.btn_siguiente.pack(side="right", padx=5)
            self.btn_ejecutar.pack_forget()
            self.btn_reiniciar.pack(side="right", padx=5)
            self._validar_rutas_paso1()

        elif self.paso_actual == 2:
            self.frame_paso2.pack(fill="both", expand=True)
            self.btn_anterior.config(state="normal")
            self.btn_siguiente.pack(side="right", padx=5)
            self.btn_ejecutar.pack_forget()

        elif self.paso_actual == 3:
            self.frame_paso3.pack(fill="both", expand=True)
            self.btn_anterior.config(state="normal")
            self.btn_siguiente.pack(side="right", padx=5)
            self.btn_ejecutar.pack_forget()
            self._actualizar_visor_paso3()

        elif self.paso_actual == 4:
            self.frame_paso4.pack(fill="both", expand=True)
            self.btn_anterior.config(state="normal")
            self.btn_siguiente.pack_forget()
            self.btn_ejecutar.pack(side="right", padx=5)
            self.btn_ejecutar.config(state="normal" if self.planes_actuales else "disabled")
            self._actualizar_resumen_paso4()

        elif self.paso_actual == 5:
            self.frame_paso5.pack(fill="both", expand=True)
            self.btn_anterior.config(state="normal")
            self.btn_siguiente.pack_forget()
            self.btn_ejecutar.pack_forget()
            self.btn_reiniciar.pack(side="right", padx=5)

    def _siguiente(self):
        if self.paso_actual == 1:
            if not self._validar_rutas_paso1():
                messagebox.showwarning("Carpetas Inválidas", "Por favor seleccione carpetas de origen y destino válidas.")
                return
        elif self.paso_actual == 2:
            self._guardar_filtros_paso2()
        elif self.paso_actual == 3:
            self._guardar_estructura_paso3()

        if self.paso_actual < 4:
            self.paso_actual += 1
            self._actualizar_estado_paso()

    def _anterior(self):
        if self.paso_actual > 1:
            self.paso_actual -= 1
            self._actualizar_estado_paso()
        elif self.paso_actual == 1:
            self._volver_a_bienvenida()

    def _al_cambiar_cat_todos(self):
        if self.var_cat_todos.get():
            for v in self.vars_categorias.values():
                v.set(False)

    def _al_cambiar_cat_individual(self):
        if any(v.get() for v in self.vars_categorias.values()):
            self.var_cat_todos.set(False)
        else:
            self.var_cat_todos.set(True)

    def _al_cambiar_criterios_paso3(self):
        crit_p = self.var_criterio_primario.get()
        if crit_p == "Ninguno":
            self.var_usar_secundario.set(False)
            self.cb_criterio_secundario.config(state="disabled")
        else:
            self.cb_criterio_secundario.config(state="readonly" if self.var_usar_secundario.get() else "disabled")
        self._actualizar_visor_paso3()

    def _al_cambiar_renombrado(self):
        self._actualizar_visor_paso3()

    def _actualizar_visor_paso3(self):
        if not hasattr(self, 'tree_visor'):
            return
        for item in self.tree_visor.get_children():
            self.tree_visor.delete(item)

        self._guardar_estructura_paso3()
        arch_ficticio = Path("mi_foto.jpg")
        fecha_ficticia = date(2024, 5, 10)
        destino_base = Path("destino")

        try:
            ruta_res = generar_ruta_destino(arch_ficticio, fecha_ficticia, destino_base, self.estructura)
            rel = ruta_res.relative_to(destino_base)
            curr_parent = self.tree_visor.insert("", "end", text="destino/", open=True)
            for i, part in enumerate(list(rel.parts)):
                if i == len(rel.parts) - 1:
                    self.tree_visor.insert(curr_parent, "end", text=f"📄 {part}", open=True)
                else:
                    curr_parent = self.tree_visor.insert(curr_parent, "end", text=f"📁 {part}/", open=True)

            self.lbl_sim_antes.config(text=f"Antes: {arch_ficticio.name}")
            self.lbl_sim_despues.config(text=f"Después: {rel}")
        except Exception:
            pass

    def _guardar_estructura_paso3(self):
        mapa_crit = {'Fecha': 'fecha', 'Tipo de archivo': 'tipo', 'Nombre': 'nombre', 'Ninguno': 'ninguno'}
        crit_p = mapa_crit.get(self.var_criterio_primario.get(), 'fecha')
        crit_s = mapa_crit.get(self.var_criterio_secundario.get(), None) if self.var_usar_secundario.get() else None

        patron_elegido = self.var_formato_fecha_custom.get().strip() or self.var_formato_fecha_combo.get()
        mapa_fmt = {"YYYY/MM": "{YYYY}/{MM}", "YYYY-MM": "{YYYY}-{MM}", "YYYY/MM/DD": "{YYYY}/{MM}/{DD}", "YYYY-MM-DD": "{YYYY}-{MM}-{DD}"}
        patron_final = mapa_fmt.get(patron_elegido, patron_elegido)

        self.estructura = {
            'criterio_primario': crit_p,
            'criterio_secundario': crit_s,
            'formato_fecha': patron_final,
            'organizacion_tipo': self.var_org_tipo.get(),
            'organizacion_nombre': self.var_org_nombre.get(),
            'usar_fecha_creacion': (self.var_fuente_fecha.get() == "ctime"),
            'activar_renombrado': self.var_activar_renombrado.get(),
            'plantilla_nombre': self.var_plantilla_nombre.get().strip() if self.var_activar_renombrado.get() else None,
        }

    def _guardar_filtros_paso2(self):
        cats_seleccionadas = [cat for cat, var in self.vars_categorias.items() if var.get()]

        def _parse_mb(val: str):
            try:
                v = float(val.strip())
                return int(v * 1024 * 1024) if v > 0 else None
            except Exception:
                return None

        self.filtros = {
            "todos": self.var_cat_todos.get(),
            "categorias": cats_seleccionadas,
            "ext_adicionales": list(self.ext_adicionales),
            "incluir_subcarpetas": self.var_subcarpetas.get(),
            "usar_exif": self.var_exif.get(),
            "usar_hash": self.var_hash.get(),
            "tamano_min_bytes": _parse_mb(self.var_tamano_min.get()),
            "tamano_max_bytes": _parse_mb(self.var_tamano_max.get()),
            "dias_antiguedad": self.var_dias_antiguedad.get() if self.var_dias_antiguedad.get() > 0 else None,
            "incluir_ocultos": self.var_incluir_ocultos.get(),
            "patron_regex": self.var_patron_regex.get().strip() or None,
            "usar_creacion_filtro": self.var_usar_creacion_filtro.get(),
        }

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
            if self.paso_actual == 1:
                self.btn_siguiente.config(state="normal")
        else:
            if self.paso_actual == 1:
                self.btn_siguiente.config(state="disabled")

        return valido

    def _examinar_origen(self):
        d = filedialog.askdirectory(title="Seleccionar Carpeta Origen")
        if d:
            self.entry_origen.delete(0, tk.END)
            self.entry_origen.insert(0, d)
            self._validar_rutas_paso1()

    def _examinar_destino(self):
        d = filedialog.askdirectory(title="Seleccionar Carpeta Destino")
        if d:
            self.entry_destino.delete(0, tk.END)
            self.entry_destino.insert(0, d)
            self._validar_rutas_paso1()

    def _examinar_generico(self, entry_widget: ttk.Entry):
        d = filedialog.askdirectory()
        if d:
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, d)

    def _detectar_unidad_extraible(self):
        orig = self.entry_origen.get().strip()
        if not orig:
            messagebox.showinfo("Origen Requerido", "Por favor seleccione primero una carpeta de origen.")
            return

        if orig.startswith("/media/") or orig.startswith("/mnt/") or orig.startswith("/run/media/"):
            messagebox.showinfo("Dispositivo Extraíble", f"Se detectó un dispositivo externo en '{orig}'. Recomendamos usar modo 'Copiar'.")
            self._seleccionar_modo_tarjeta("Copiar")
        else:
            messagebox.showinfo("Almacenamiento Local", "La carpeta seleccionada pertenece al disco interno principal.")

    def _detectar_dispositivos_multimedia_gui(self):
        dispositivos = detectar_dispositivos_multimedia()
        if not dispositivos:
            messagebox.showinfo("Sin Dispositivos", "No se detectaron celulares ni cámaras MTP montadas.")
            return

        dlg = tk.Toplevel(self.root)
        dlg.title("Dispositivos Multimedia Detectados")
        dlg.geometry("520x300")
        dlg.transient(self.root)
        dlg.grab_set()

        tk.Label(dlg, text="Seleccione un dispositivo multimedia:", font=("Helvetica", 10, "bold")).pack(anchor="w", padx=15, pady=(15, 5))
        listbox = tk.Listbox(dlg, height=8)
        listbox.pack(fill="both", expand=True, padx=15, pady=5)

        for d in dispositivos:
            listbox.insert(tk.END, f"{d['etiqueta']} [{d['tipo']}] - {d['espacio']} ({d['ruta']})")

        def _usar_sel():
            sel = listbox.curselection()
            if sel:
                idx = sel[0]
                self.entry_origen.delete(0, tk.END)
                self.entry_origen.insert(0, dispositivos[idx]['ruta'])
                self._validar_rutas_paso1()
                dlg.destroy()

        tk.Button(dlg, text="Usar como Origen", bg=self.COLOR_SUCCESS, fg="#FFFFFF", font=("Helvetica", 9, "bold"), relief="flat", command=_usar_sel).pack(pady=10)

    def _actualizar_resumen_paso4(self):
        self.lbl_resumen_origen.config(text=f"Origen: {self.origen}")
        self.lbl_resumen_destino.config(text=f"Destino: {self.destino}")
        self.lbl_resumen_modo.config(text=f"Modo: {self.var_modo.get()}")

    def _dialogo_deshacer(self):
        res: ServiceResult = deshacer_n_operaciones(n=1, dry_run=False)
        if not res.success:
            messagebox.showinfo("Undo", f"No se pudo deshacer [{res.error_code}]:\n{res.error}")
        else:
            d = res.data or {}
            messagebox.showinfo("Undo Completado", f"Éxitos: {d.get('exitos', 0)} | Errores: {d.get('errores', 0)}")

    def _abrir_historial_undo(self):
        hist = obtener_historial_undo(limite=50)
        if not hist:
            messagebox.showinfo("Historial Undo", "Sin operaciones en el historial.")
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("Historial Undo")
        dlg.geometry("600x350")
        txt = scrolledtext.ScrolledText(dlg)
        txt.pack(fill="both", expand=True)
        for h in reversed(hist):
            txt.insert(tk.END, f"[{h.get('timestamp')[:19]}] {h.get('modo')}: {h.get('origen')} ➔ {h.get('destino')}\n")

    def _ejecutar_clonacion_carpeta_gui(self):
        orig = self.entry_clone_orig.get().strip()
        dest = self.entry_clone_dest.get().strip()
        if not orig or not dest:
            messagebox.showerror("Rutas Faltantes", "Por favor seleccione Origen y Destino válidos.")
            return

        p_o = Path(orig)
        p_d = Path(dest)
        if not p_o.exists() or not p_o.is_dir():
            messagebox.showerror("Origen Inválido", "La carpeta de origen seleccionada no existe.")
            return

        self.ejecutando_clonacion = True
        self.cancelar_clonacion = False

        self.btn_iniciar_clonacion.config(state="disabled")
        self.btn_cancelar_clone.config(state="normal")
        self.progress_clone["value"] = 0
        self.lbl_clone_porcentaje.config(text="0.0%")
        self.lbl_clone_contadores.config(text="Calculando tamaño y archivos...")
        self.lbl_clone_archivo_actual.config(text="Escaneando estructura...")

        inc = self.var_clone_inc.get()

        def _hilo_clonar():
            res: ServiceResult = clonar_carpeta(
                origen=orig,
                destino=dest,
                incremental=inc,
                callback_progreso=lambda i, tot, b_cop, b_tot, nom: self.cola_eventos.put(('PROGRESO_CLONACION', (i, tot, b_cop, b_tot, nom))),
                cancelar_flag=lambda: getattr(self, 'cancelar_clonacion', False)
            )
            self.cola_eventos.put(('FIN_CLONACION', res))

        threading.Thread(target=_hilo_clonar, daemon=True).start()

    def _cancelar_clonacion_gui(self):
        if hasattr(self, 'ejecutando_clonacion') and self.ejecutando_clonacion:
            self.cancelar_clonacion = True
            self.btn_cancelar_clone.config(state="disabled")
            self.lbl_clone_archivo_actual.config(text="Deteniendo clonación...")

    def _cancelar(self):
        if self.ejecutando:
            self.cancelar = True
        else:
            self._guardar_configuracion()
            self.root.destroy()

    def _al_cerrar_ventana(self):
        if self.ejecutando:
            self.cancelar = True
        self._guardar_configuracion()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = WizardApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
