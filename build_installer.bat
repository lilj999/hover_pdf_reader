@echo off
setlocal
cd /d "%~dp0"

if not exist dist\HoverPDFReader\HoverPDFReader.exe (
    echo Portable package not found. Building it first...
    call build_portable.bat
)

where iscc >nul 2>nul
if errorlevel 1 (
    echo.
    echo Cannot find iscc.exe.
    echo Please install Inno Setup, then add it to PATH, or run this manually:
    echo "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
    pause
    exit /b 1
)

iscc installer.iss
if errorlevel 1 (
    echo Installer build failed.
    pause
    exit /b 1
)

echo.
echo Done.
echo Installer: installer\HoverPDFReader_Setup_1.0.0.exe
pause
