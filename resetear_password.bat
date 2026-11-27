@echo off
setlocal
cd /d "%~dp0"

set "STOCKEX_PYTHON=python"
if exist "venv\Scripts\python.exe" (
    set "STOCKEX_PYTHON=venv\Scripts\python.exe"
) else if exist "env\Scripts\python.exe" (
    set "STOCKEX_PYTHON=env\Scripts\python.exe"
)

REM Django solicita la contraseña sin mostrarla y aplica sus validadores.
if "%~1"=="" (
    echo Uso: resetear_password.bat USUARIO
    exit /b 1
)
"%STOCKEX_PYTHON%" manage.py changepassword "%~1"
exit /b %errorlevel%
