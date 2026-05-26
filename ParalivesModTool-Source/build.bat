@echo off
echo Installing dependencies...
pip install customtkinter Pillow pyinstaller

echo.
echo Building ParalivesModTool.exe...
python -m PyInstaller --onefile --windowed --collect-all customtkinter --name "ParalivesModTool" paralives_mod_tool.py

echo.
echo Done. The exe is in the dist\ folder.
pause
