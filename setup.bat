@echo off
echo ========================================
echo    AutoMoto AI - Setup Script
echo ========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.10+ from python.org
    echo Make sure to check "Add Python to PATH" during installation
    echo.
    pause
    exit /b 1
)

echo Python found:
python --version
echo.

REM Create virtual environment
echo Creating virtual environment...
if exist "venv\" (
    echo Virtual environment already exists. Skipping creation.
) else (
    python -m venv venv
    if errorlevel 1 (
        echo Failed to create virtual environment
        pause
        exit /b 1
    )
    echo Virtual environment created successfully
)
echo.

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo Failed to activate virtual environment
    pause
    exit /b 1
)
echo.

REM Upgrade pip
echo Upgrading pip...
python -m pip install --upgrade pip
echo.

REM Install dependencies
echo Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies
    pause
    exit /b 1
)
echo.

REM Check if .env exists
if not exist ".env" (
    echo.
    echo ========================================
    echo    IMPORTANT: API Key Configuration
    echo ========================================
    echo.
    echo .env file not found!
    echo.
    echo Please follow these steps:
    echo 1. Rename .env.example to .env
    echo 2. Get your OpenAI API key from: https://platform.openai.com/api-keys
    echo 3. Open .env file and replace "your_openai_api_key_here" with your actual key
    echo 4. Save the file
    echo.
    echo After configuring the API key, you can run the application using run.bat
    echo.
) else (
    echo .env file found
    echo.
)

REM Run installation test
echo Running installation test...
echo.
python test_installation.py
echo.

echo ========================================
echo    Setup Complete!
echo ========================================
echo.
echo Next steps:
echo 1. Configure your OpenAI API key in .env file (if not done)
echo 2. Run the application using: run.bat
echo    OR manually: python main.py
echo.
echo For detailed instructions, see setup_guide.txt
echo.

call venv\Scripts\deactivate.bat
pause
