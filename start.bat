@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo 还没安装环境，请先双击 install.bat
    pause
    exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" "%~dp0main.py"
