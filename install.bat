@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================
echo   LiveDub 环境安装（首次使用跑一次即可）
echo ============================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] 创建 Python 虚拟环境...
    where python >nul 2>nul
    if errorlevel 1 (
        echo.
        echo 没找到 python。请先安装 Python 3.10+ （勾选 Add to PATH），再重新运行本脚本。
        pause
        exit /b 1
    )
    python -m venv .venv
)

set "PY=.venv\Scripts\python.exe"
set "MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple"

echo [2/3] 安装依赖（清华镜像，约 200MB）...
"%PY%" -m pip install --upgrade pip -i %MIRROR%
"%PY%" -m pip install -i %MIRROR% pyaudiowpatch onnxruntime requests numpy faster-whisper edge-tts miniaudio sherpa-onnx PySide6
:: 可选：装完 VB-CABLE 后用它把系统默认播放设备改回扬声器（tools\fix_default_audio.py）
"%PY%" -m pip install -i %MIRROR% comtypes pycaw
if errorlevel 1 (
    echo.
    echo 依赖安装失败，请检查网络后重试。
    pause
    exit /b 1
)

echo.
echo [3/3] 下载模型（约 230MB，走 hf-mirror 镜像）...
"%PY%" tools\download_models.py
if errorlevel 1 (
    echo.
    echo 模型下载失败，可稍后手动运行： .venv\Scripts\python.exe tools\download_models.py
    pause
    exit /b 1
)

echo.
echo 安装完成！双击 start.bat 启动。
pause
