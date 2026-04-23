@echo off
cd /d "%~dp0"
python -m app.main
if errorlevel 1 (
  echo.
  echo Ocurrio un error al iniciar TECNOMEDIA GT Business Suite.
  pause
)
