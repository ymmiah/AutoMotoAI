@echo off
echo ========================================
echo    AutoMoto AI - Startup Script
echo ========================================
echo.

REM Check if virtual environment exists
if not exist "venv\" (
    echo Virtual environment not found!
    echo Please run setup.bat first or follow setup_guide.txt
    echo.
    pause
    exit /b 1
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

REM Check if activation was successful
if errorlevel 1 (
    echo Failed to activate virtual environment
    pause
    exit /b 1
)

echo Virtual environment activated
echo.

REM Run the application
echo Starting AutoMoto AI...
echo.
python main.py

REM Deactivate when done
call venv\Scripts\deactivate.bat

echo.
echo AutoMoto AI has been closed.
pause
