# 📁 Memexicanisimos Files v1.0

> **Memexicanisimos Files** – Organiza, clona, respalda y renombra tus archivos con un asistente paso a paso.
> Parte del ecosistema de software open-source **Memexicanisimos**.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/python-3.8%2B-brightgreen.svg)](https://python.org)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20Windows%20%7C%20macOS-orange.svg)](#)

---

## 📦 Descarga directa (Linux)

Puedes descargar el binario ya compilado para Linux x86_64 desde [GitHub Releases](https://github.com/myinnervoid/Memexicanisimos-Files/releases).

```bash
# Descargar y ejecutar (.tar.gz)
wget https://github.com/myinnervoid/Memexicanisimos-Files/releases/download/v1.0/memexicanisimos-files-linux-x86_64.tar.gz
tar -xzf memexicanisimos-files-linux-x86_64.tar.gz
./memexicanisimos-files
```

O si prefieres el formato ZIP:
```bash
unzip memexicanisimos-files-linux.zip
chmod +x memexicanisimos-files
./memexicanisimos-files
```

---

## 🌟 Características Principales

- 🎯 **Análisis Inteligente de Destino**: Detecta si la carpeta de destino ya cuenta con estructuras organizativas (`YYYY/MM`, extensión o por letra) para integrar archivos sin duplicar carpetas.
- ↩️ **Sistema Undo / Deshacer**: Revierte operaciones con registro atómico en formato **JSON Lines** (`~/.organizador_undo.jsonl`), soporte para simulación **Dry-Run** e historial de operaciones.
- 📂 **Organización Flexible por 5 Criterios**:
  - Por **Fecha** (EXIF, Regex en nombre, o fecha del sistema `ctime`/`mtime`).
  - Por **Tipo de archivo** (extensión individual o categorías como Imágenes, Documentos, Música, Código).
  - Por **Nombre** (primera letra A-Z o nombre completo).
- 🏷️ **Renombrado Masivo Avanzado**: Usa placeholders estándar (`{nombre}`, `{ext}`, `{fecha}`, `{contador:03d}`) y **metadatos de audio** (`{artista}`, `{album}`, `{titulo}`, `{ano}`, `{genero}`, `{caratula}`).
- 🧹 **Limpieza de Metadatos y Carpetas Vacías**: Opción para eliminar metadatos sensibles de audio y borrar carpetas vacías del origen/destino.
- 🔍 **Filtros Avanzados**: Filtra por rango de tamaño en MB, antigüedad máxima en días, archivos ocultos y expresiones regulares (Regex).
- 🚀 **Respaldo y Clonación (Paso 5)**:
  - Clonación incremental de carpetas (`rsync -u` / `shutil`).
  - Respaldo automático de carpetas personales (`~/Documentos`, `~/Imágenes`, etc.).
  - Clonación de discos/particiones a nivel de bloque con `dd` / `ddrescue` y verificación checksum MD5.
- 📷 **Importador desde Dispositivos Multimedia**: Detección automática de teléfonos Android (MTP), cámaras (PTP) y unidades extraíbles montadas.
- 💾 **Sistema de Perfiles**: Guarda y carga combinaciones completas de filtros, renombrado y estructuras en `~/.organizador_perfiles.json`.
- 🎨 **Interfaz Pastel**: Diseñada en Tkinter con paleta suave para máxima legibilidad.

---

## 🛠️ Compilar desde el código fuente (Windows, macOS, Linux)

Si prefieres compilar tú mismo para cualquier sistema operativo:

1. Clona el repositorio:
```bash
git clone https://github.com/myinnervoid/Memexicanisimos-Files.git
cd Memexicanisimos-Files
```

2. Ejecuta el script según tu sistema:
- **Windows**: Ejecuta `build_windows.bat` (o haz doble clic sobre él).
- **Linux / macOS**: Ejecuta `./build_unix.sh`.

El ejecutable binario se generará automáticamente en la carpeta `dist/`.

---

## 🔧 Solución de Problemas (Troubleshooting)

### Error: "Failed to load shared library"
En Linux, si la distribución es muy ligera, puede faltar alguna biblioteca gráfica del sistema. Instala los paquetes necesarios:

```bash
# Debian / Ubuntu
sudo apt install python3-tk python3-pil python3-pil.imagetk

# Fedora
sudo dnf install python3-tkinter python3-pillow

# Arch Linux
sudo pacman -S tk pillow
```

### Error: "ModuleNotFoundError"
Asegúrate de tener todas las dependencias Python instaladas:
```bash
pip install -r requirements.txt
```

### El binario no se ejecuta en otra distribución Linux
El binario compilado con PyInstaller empaqueta Python y las dependencias de Python, pero puede requerir bibliotecas compartidas del sistema (como `glibc`, `libtcl`, `libtk`). Si encuentras errores de bibliotecas faltantes en distribuciones antiguas o minimalistas, instala los paquetes del sistema indicados arriba o ejecuta la herramienta mediante script usando `./build_unix.sh`.

---

## 🌐 Sitio Web Oficial

Visita nuestra página web interactiva en GitHub Pages:
👉 **[https://myinnervoid.github.io/Memexicanisimos-Files/](https://myinnervoid.github.io/Memexicanisimos-Files/)**

---

## 📄 Licencia

Este proyecto está distribuido bajo la licencia **MIT**. Consulta el archivo `LICENSE` para más información.

---

## 💙 Ecosistema Memexicanisimos

**Memexicanisimos Files** es parte de la suite de herramientas open-source desarrolladas para empoderar a la comunidad Linux.
