@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo.
echo  ===== Instalador del editor de video =====
echo.

rem --- 1. Python ---
set "PY="
py -3.12 --version >nul 2>&1 && set "PY=py -3.12"
if not defined PY py -3.11 --version >nul 2>&1 && set "PY=py -3.11"
if not defined PY python --version >nul 2>&1 && set "PY=python"
if not defined PY (
  echo [1/3] No tienes Python. Lo instalo con winget...
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  echo.
  echo  Python instalado. CIERRA esta ventana y vuelve a ejecutar instalar.bat
  pause
  exit /b
)
echo [1/3] Python encontrado: %PY%

rem --- 2. FFmpeg ---
where ffmpeg >nul 2>&1
if errorlevel 1 (
  echo [2/3] No tienes FFmpeg. Lo instalo con winget...
  winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
  echo.
  echo  FFmpeg instalado. CIERRA esta ventana y vuelve a ejecutar instalar.bat
  echo  (si sigue sin encontrarlo, reinicia el ordenador^)
  pause
  exit /b
)
echo [2/3] FFmpeg encontrado

rem --- 3. Librerias ---
if not exist ".venv\Scripts\python.exe" (
  echo [3/3] Creando entorno de Python...
  %PY% -m venv .venv || (echo No pude crear el entorno & pause & exit /b 1)
)
echo [3/3] Instalando librerias (la primera vez tarda unos minutos)...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt || (echo Fallo instalando librerias & pause & exit /b 1)

if not exist ".env" copy ".env.example" ".env" >nul

echo.
echo  ===== Todo listo. Abre el editor con iniciar.bat =====
echo  (la primera vez que generes subtitulos se descarga el modelo de voz, entre 150 MB y 1,5 GB segun la precision elegida)
echo.
pause
