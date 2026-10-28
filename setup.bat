@echo off
REM AutoMoto AI v4 - Windows setup
python -m venv venv || (echo Python 3.10+ is required & exit /b 1)
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist ".env" copy .env.example .env
echo.
echo Done. Add at least one API key to .env, then run run.bat
