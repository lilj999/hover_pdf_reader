@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "PYTHON_CMD="
for %%I in (python python3) do (
    where %%I >nul 2>&1 && if not defined PYTHON_CMD set "PYTHON_CMD=%%I"
)
if not defined PYTHON_CMD (
    where py >nul 2>&1 && set "PYTHON_CMD=py -3"
)
if defined PYTHON_CMD (
    set "PYTHON_CHECK="
    for /f "delims=" %%A in ('%PYTHON_CMD% --version 2^>^1') do if not defined PYTHON_CHECK set "PYTHON_CHECK=%%A"
    echo !PYTHON_CHECK! | findstr /c:"Unable to create process" >nul 2>&1 && set "PYTHON_CMD="
)
if not defined PYTHON_CMD (
    echo Error: Python 3 executable not found. Install Python 3 or add it to PATH.
    pause
    exit /b 1
)

echo [1/5] Creating virtual environment...
if not exist .venv (
    %PYTHON_CMD% -m venv .venv
)

echo [2/5] Activating virtual environment...
call .venv\Scripts\activate.bat

echo [3/5] Installing dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install --upgrade pyinstaller

echo [4/5] Cleaning old build output...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist HoverPDFReader.spec del /q HoverPDFReader.spec

echo [5/5] Building portable onedir package...
pyinstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --onedir ^
  --name HoverPDFReader ^
  pdf_reader.py

if errorlevel 1 (
    echo.
    echo Build failed. If PySide6 or PyMuPDF resources are missing, try the fallback command in README_PACKAGING.md.
    pause
    exit /b 1
)

echo.
echo Done.
echo Portable app folder: dist\HoverPDFReader
echo Run: dist\HoverPDFReader\HoverPDFReader.exe
pause
