@echo off
REM Recall & Reflect — first run sets up a venv and installs deps, then launches.
REM Later runs re-install only if a required package is missing (e.g. after an update).
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo Creating virtual environment...
    py -3 -m venv venv
    call venv\Scripts\activate.bat
    echo Installing dependencies...
    python -m pip install --upgrade pip >nul
    python -m pip install -r requirements.txt
) else (
    call venv\Scripts\activate.bat
    python -c "import fastapi, uvicorn, httpx, pydantic, fsrs, apscheduler" 2>nul
    if errorlevel 1 (
        echo Updating dependencies...
        python -m pip install -r requirements.txt
    )
)

python run.py
