@echo off
REM Windows Batch Script to Build Standalone Executable (Console Version)
REM This version shows a console window for easier debugging

echo ================================================
echo Notepad Auto-Save - Executable Builder (Console)
echo ================================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python from https://www.python.org/
    pause
    exit /b 1
)

echo [1/4] Installing required packages...
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install requirements
    pause
    exit /b 1
)

echo.
echo [2/4] Cleaning previous build...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist notepad_autosave.spec del /f notepad_autosave.spec

echo.
echo [3/4] Building executable with PyInstaller (Console mode)...
pyinstaller --onefile ^
    --console ^
    --name "NotepadAutoSave_Console" ^
    --icon=NONE ^
    --add-data "config.json;." ^
    notepad_autosave.py

if errorlevel 1 (
    echo ERROR: Build failed
    pause
    exit /b 1
)

echo.
echo [4/4] Copying config file to dist folder...
copy config.json dist\config.json

echo.
echo ================================================
echo Build completed successfully!
echo ================================================
echo.
echo Executable location: dist\NotepadAutoSave_Console.exe
echo.
echo This version shows a console window with logs.
echo Good for debugging and seeing what the program is doing!
echo.
pause
