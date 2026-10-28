@echo off
REM AutoMoto AI v4 - starts the local web UI (http://127.0.0.1:8765)
if not exist "venv\" (echo Run setup.bat first & exit /b 1)
call venv\Scripts\activate.bat
python -m automoto serve %*
