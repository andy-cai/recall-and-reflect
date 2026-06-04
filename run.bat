@echo off
REM Recall & Reflect — first run sets up a venv and installs deps, then launches.
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo Creating virtual environment...
    py -m venv venv
    call venv\Scripts\activate.bat
    echo Installing dependencies...
    python -m pip install --upgrade pip >nul
    python -m pip install -r requirements.txt
) else (
    call venv\Scripts\activate.bat
)

python run.py
