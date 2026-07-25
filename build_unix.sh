#!/bin/bash
set -e

echo "======================================================="
echo " Memexicanisimos Files v1.0 - Compilador Linux / macOS"
echo "======================================================="
echo ""

echo "Creando entorno virtual..."
python3 -m venv venv
source venv/bin/activate

echo "Instalando dependencias necesarias..."
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

echo "Compilando con PyInstaller..."
pyinstaller --noconfirm --clean --onefile --windowed --name "memexicanisimos-files" --icon "icon/icon.ico" gui_wizard.py

echo ""
echo "======================================================="
echo " ¡Listo! El ejecutable está en: dist/memexicanisimos-files"
echo "======================================================="
