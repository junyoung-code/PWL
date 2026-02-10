@echo off
REM Complete Build Script - Setup, Build, and Run
REM This creates a standalone .exe that can run without Python

echo ====================================================
echo PWL - Complete Build and Run
echo ====================================================
echo.

REM ========================================
REM Step 1: Check/Install Python
REM ========================================
echo [1/5] Checking Python...
py --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=py
    goto :python_found
)

python --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=python
    goto :python_found
)

echo Python not found. Installing...
winget --version >nul 2>&1
if %errorlevel% equ 0 (
    echo Installing Python via winget...
    winget install -e --id Python.Python.3.12 --silent
    echo.
    echo Python installed! Please run this script again.
    pause
    exit /b 0
) else (
    echo ERROR: Please install Python manually from:
    echo https://www.python.org/downloads/
    pause
    exit /b 1
)

:python_found
%PYTHON_CMD% --version
echo.

REM ========================================
REM Step 2: Install Requirements
REM ========================================
echo [2/5] Installing required packages...
%PYTHON_CMD% -m pip install --upgrade pip --quiet
%PYTHON_CMD% -m pip install -r requirements.txt --quiet

if errorlevel 1 (
    echo Failed to install from requirements.txt
    echo Installing packages individually...
    %PYTHON_CMD% -m pip install pywin32 --quiet
    %PYTHON_CMD% -m pip install pyinstaller --quiet
)
echo Packages installed successfully!
echo.

REM ========================================
REM Step 3: Clean Previous Build
REM ========================================
echo [3/5] Cleaning previous build...

REM Kill running process if exists
echo Checking for running NotepadAutoSave.exe...
taskkill /F /IM NotepadAutoSave.exe >nul 2>&1
if %errorlevel% equ 0 (
    echo Process terminated. Waiting...
    timeout /t 2 /nobreak >nul
)

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist notepad_autosave.spec del /f notepad_autosave.spec
echo Clean complete!
echo.

REM ========================================
REM Step 4: Build Executable
REM ========================================
echo [4/5] Building executable...
echo This may take 1-2 minutes...
echo.

%PYTHON_CMD% -m PyInstaller --onefile ^
    --noconsole ^
    --name "NotepadAutoSave" ^
    --icon=NONE ^
    --add-data "config.json;." ^
    --hidden-import=uiautomation ^
    --hidden-import=comtypes ^
    --hidden-import=comtypes.stream ^
    notepad_autosave.py

if errorlevel 1 (
    echo.
    echo ====================================================
    echo ERROR: Build failed!
    echo ====================================================
    pause
    exit /b 1
)

REM Copy config file to dist folder
echo.
echo Copying config file...
copy config.json dist\config.json >nul

REM Create AA.txt target file if not exists
if not exist AA.txt (
    echo. > AA.txt
    echo Created AA.txt target file
)
copy AA.txt dist\AA.txt >nul
echo.

REM ========================================
REM Step 5: Build Complete
REM ========================================
echo ====================================================
echo Build Completed Successfully!
echo ====================================================
echo.
echo Executable created at: dist\NotepadAutoSave.exe
echo.
echo You can now:
echo   1. Run: dist\NotepadAutoSave.exe
echo   2. Copy the "dist" folder to any Windows PC
echo   3. No Python installation needed!
echo.

REM Ask if user wants to run the program
choice /C YN /M "Do you want to run NotepadAutoSave.exe now"
if errorlevel 2 goto :end
if errorlevel 1 goto :run_exe

:run_exe
echo.
echo Starting NotepadAutoSave.exe...
start "" "dist\NotepadAutoSave.exe"
echo.
echo Program started!
goto :end

:end
echo.
echo ====================================================
echo Next time, just double-click: dist\NotepadAutoSave.exe
echo ====================================================
pause
