# 📁 Memexicanisimos Files v1.0

> **Memexicanisimos Files** – Organiza, clona, respalda y renombra tus archivos con un asistente gráfico de 5 pasos para Linux, Windows y macOS.
> Parte del ecosistema de software open-source **Memexicanisimos**.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/python-3.8%2B-brightgreen.svg)](https://python.org)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20Windows%20%7C%20macOS-orange.svg)](#)
[![Releases](https://img.shields.io/badge/release-v1.0-blue.svg)](https://github.com/myinnervoid/Memexicanisimos-Files/releases/tag/1.0)

---

## 🚀 🐧 Descarga Directa para Linux (Opción Recomendada)

Si utilizas Linux (x86_64), **no necesitas instalar Python ni compilar nada**. El ejecutable ya contiene todo lo necesario para funcionar inmediatamente.

### Pasos rápidos (3 pasos):

1. **Descarga** el paquete comprimido desde [GitHub Releases v1.0](https://github.com/myinnervoid/Memexicanisimos-Files/releases/tag/1.0):
   - 📦 [memexicanisimos-files-linux-x86_64.tar.gz](https://github.com/myinnervoid/Memexicanisimos-Files/releases/download/1.0/memexicanisimos-files-linux-x86_64.tar.gz)
   - 📦 [memexicanisimos-files-linux.zip](https://github.com/myinnervoid/Memexicanisimos-Files/releases/download/1.0/memexicanisimos-files-linux.zip)

2. **Descomprime** el archivo descargado en tu carpeta favorita.

3. **Abre una terminal** en esa carpeta y ejecuta:

```bash
# Otorgar permisos de ejecución
chmod +x memexicanisimos-files

# Iniciar la aplicación
./memexicanisimos-files
```

💡 **Tip Pro**: Para poder ejecutar `memexicanisimos-files` desde cualquier terminal sin escribir la ruta, muévelo a `/usr/local/bin/`:
```bash
sudo mv memexicanisimos-files /usr/local/bin/
```

---

## 🌟 Características Principales

- 🎯 **Análisis Inteligente de Destino**: Detecta automáticamente si la carpeta de destino ya cuenta con estructuras organizativas (`YYYY/MM`, extensión o por letra) para integrar archivos sin duplicar carpetas.
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

## 🛠️ Compilación desde el Código Fuente (Multiplataforma)

Si prefieres compilar la aplicación tú mismo o estás en **Windows** o **macOS**, puedes utilizar los scripts automáticos incluidos en el proyecto.

### 📋 Requisitos Previos Generales
- Tener instalado **Python 3.8** o superior ([python.org](https://www.python.org/downloads/)).
- Tener instalado **Git** ([git-scm.com](https://git-scm.com/)).

---

### 🪟 Instalar y Compilar en Windows

1. Abre la consola de comandos (**CMD**) o **PowerShell** y clona el repositorio:
```cmd
git clone https://github.com/myinnervoid/Memexicanisimos-Files.git
cd Memexicanisimos-Files
```

2. Ejecuta el script automático de compilación:
```cmd
build_windows.bat
```

3. ¡Listo! El ejecutable `.exe` se generará en la carpeta `dist\memexicanisimos-files.exe`.

---

### 🍎 Instalar y Compilar en macOS

1. Abre la **Terminal** y clona el repositorio:
```bash
git clone https://github.com/myinnervoid/Memexicanisimos-Files.git
cd Memexicanisimos-Files
```

2. Otorga permisos de ejecución al script y compila:
```bash
chmod +x build_unix.sh
./build_unix.sh
```

3. El binario ejecutable estará listo en la carpeta `dist/memexicanisimos-files`.

---

### 🐧 Instalar y Compilar en Linux (Opcional)

*(Nota: Te recomendamos usar la [Descarga Directa](#-descarga-directa-para-linux-opción-recomendada) que no requiere compilación).*

1. Clona el repositorio e ingresa a la carpeta:
```bash
git clone https://github.com/myinnervoid/Memexicanisimos-Files.git
cd Memexicanisimos-Files
```

2. Ejecuta el script de compilación Unix:
```bash
chmod +x build_unix.sh
./build_unix.sh
```

3. El ejecutable compilado estará disponible en `dist/memexicanisimos-files`.

---

## 🔧 Solución de Problemas Frecuentes (Troubleshooting)

| Error / Problema | Causa Probable | Solución Paso a Paso |
|---|---|---|
| `'python' no se reconoce como un comando interno` | Python no está agregado al PATH de Windows | Reinstala Python desde [python.org](https://www.python.org) asegurándote de marcar la casilla **"Add python.exe to PATH"**. |
| `pip: command not found` | `pip` no está instalado en el sistema Linux | Instálalo usando el gestor de paquetes:<br>`sudo apt install python3-pip` (Debian/Ubuntu)<br>`sudo dnf install python3-pip` (Fedora) |
| `Permission denied` al ejecutar `./build_unix.sh` | El script no tiene permisos de ejecución | Otorga permisos ejecutando:<br>`chmod +x build_unix.sh` |
| `ModuleNotFoundError: No module named 'tkinter'` | Falta la interfaz gráfica Tkinter en Linux | Instala Tkinter en el sistema:<br>`sudo apt install python3-tk` (Debian/Ubuntu)<br>`sudo dnf install python3-tkinter` (Fedora)<br>`sudo pacman -S tk` (Arch Linux) |
| `ModuleNotFoundError: No module named 'PIL'` o `mutagen` | Falta alguna dependencia Python | Asegúrate de instalar los requerimientos ejecutando:<br>`pip install -r requirements.txt` |
| `Failed to load shared library` al abrir binario | La distribución Linux no posee librerías gráficas estándar | Instala las librerías base:<br>`sudo apt install python3-pil python3-pil.imagetk` |

---

## 🌐 Sitio Web Oficial

Visita nuestra página web interactiva en GitHub Pages:
👉 **[https://myinnervoid.github.io/Memexicanisimos-Files/](https://myinnervoid.github.io/Memexicanisimos-Files/)**

---

## 📄 Licencia

Este proyecto está distribuido bajo la licencia **MIT**. Consulta el archivo `LICENSE` para más información.

---

## 💙 Ecosistema Memexicanisimos

**Memexicanisimos Files** es parte de la suite de herramientas open-source desarrolladas para empoderar a la comunidad Linux y facilitar la gestión digital.
