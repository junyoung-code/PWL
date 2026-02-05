@echo off
REM Quick Run Script - Just run the program
REM Use this after building with build_and_run.bat

echo ====================================
echo PWL - Quick Run
echo ====================================
echo.

REM Check if exe exists
if not exist "dist\NotepadAutoSave.exe" (
    echo ERROR: NotepadAutoSave.exe not found!
    echo.
    echo Please build the program first by running:
    echo   build_and_run.bat
    echo.
    pause
    exit /b 1
)

echo Starting NotepadAutoSave...
start "" "dist\NotepadAutoSave.exe"

echo.
echo Program started!
echo Check for the popup window.
echo.
timeout /t 2 >nul
