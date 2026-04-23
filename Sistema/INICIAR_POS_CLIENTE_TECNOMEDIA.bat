@echo off
cd /d "%~dp0"
python -m app.sales_pos_module
if errorlevel 1 (
  echo.
  echo Ocurrio un error al iniciar TECNOMEDIA POS Cliente.
  pause
)
