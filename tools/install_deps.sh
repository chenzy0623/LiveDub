#!/usr/bin/env bash
# Install runtime dependencies into .venv using the Tsinghua PyPI mirror.
set -e
cd "$(dirname "$0")/.."
PY=".venv/Scripts/python.exe"
MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"
export PIP_DEFAULT_TIMEOUT=120

echo "== upgrading pip =="
"$PY" -m pip install -q --upgrade pip -i "$MIRROR" || true

echo "== core audio + vad =="
"$PY" -m pip install -i "$MIRROR" pyaudiowpatch onnxruntime soundfile requests

echo "== asr =="
"$PY" -m pip install -i "$MIRROR" faster-whisper

echo "== tts =="
"$PY" -m pip install -i "$MIRROR" edge-tts

echo "== gui =="
"$PY" -m pip install -i "$MIRROR" PySide6

echo "== done =="
"$PY" -m pip list
