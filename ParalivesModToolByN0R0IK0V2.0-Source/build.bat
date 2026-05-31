@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo  Paralives Mod Tool  --  Build Script
echo ============================================================
echo.

:: ── Install / update dependencies ───────────────────────────────────────────
echo [1/3]  Installing dependencies...
pip install --quiet --upgrade customtkinter Pillow pyinstaller
if errorlevel 1 (
    echo ERROR: pip install failed. Make sure Python is installed and on PATH.
    pause & exit /b 1
)
echo        Done.
echo.

:: ── Build the exe ────────────────────────────────────────────────────────────
echo [2/3]  Building ParalivesModTool.exe...
python -m PyInstaller ^
    --onefile ^
    --windowed ^
    --collect-all customtkinter ^
    --name "ParalivesModTool" ^
    paralives_mod_tool.py

if errorlevel 1 (
    echo.
    echo ERROR: PyInstaller build failed. See output above.
    pause & exit /b 1
)
echo        Done.
echo.

:: ── Move exe one level up, clean up build clutter ───────────────────────────
echo [3/3]  Packaging...

:: Move exe to parent folder (next to AllPythonFiles)
if exist "dist\ParalivesModTool.exe" (
    move /y "dist\ParalivesModTool.exe" "..\ParalivesModTool.exe" >nul
    echo        ParalivesModTool.exe  →  %~dp0..\
) else (
    echo WARNING: exe not found in dist\ — check PyInstaller output above.
)

:: Clean up build artefacts
if exist "dist\"  rmdir /s /q "dist"
if exist "build\" rmdir /s /q "build"
if exist "ParalivesModTool.spec" del /q "ParalivesModTool.spec"
echo        Build artefacts removed.
echo.

echo ============================================================
echo  Build complete!
echo  Output: %~dp0..\ParalivesModTool.exe
echo ============================================================
echo.
pause
