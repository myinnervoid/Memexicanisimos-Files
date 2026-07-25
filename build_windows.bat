@echo off
echo =======================================================
echo  Memexicanisimos Files v1.0 - Compilador para Windows
echo =======================================================
echo.
echo Creando entorno virtual...
python -m venv venv
call venv\Scripts\activate

echo.
echo Instalando dependencias necesarias...
pip install -r requirements.txt
pip install pyinstaller

echo.
echo Compilando con PyInstaller...
pyinstaller --noconfirm --clean --onefile --windowed --name "memexicanisimos-files" --icon "icon/icon.ico" gui_wizard.py

echo.
echo =======================================================
echo  ¡Listo! El ejecutable está en: dist\memexicanisimos-files.exe
echo =======================================================
pause
