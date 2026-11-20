"""Silero VAD（ONNX，无需 PyTorch）。

支持 v4（h/c 状态）与 v5+（state 状态）两种模型导出。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np

SAMPLE_RATE = 16000
FRAME = 512  # 16k 下 32ms


class SileroVAD:
    def __init__(self, model_path: Path, threads: int = 2):
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, threads)
        opts.inter_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(str(model_path), opts, providers=["CPUExecutionProvider"])
        self.in_names = [i.name for i in self.session.get_inputs()]
        self._v5 = "state" in self.in_names
        if self._v5:
            self._state = np.zeros((2, 1, 128), dtype=np.float32)
        else:
            self._h = np.zeros((2, 1, 64), dtype=np.float32)
            self._c = np.zeros((2, 1, 64), dtype=np.float32)
        self._sr = np.array(SAMPLE_RATE, dtype=np.int64)

    def reset(self) -> None:
        if self._v5:
            self._state = np.zeros((2, 1, 128), dtype=np.float32)
        else:
            self._h = np.zeros((2, 1, 64), dtype=np.float32)
            self._c = np.zeros((2, 1, 64), dtype=np.float32)

    def prob(self, frame: np.ndarray) -> float:
        """frame: 512 个 float32 样本。返回语音概率。"""
        x = np.asarray(frame, dtype=np.float32).reshape(1, -1)
        if x.shape[1] < FRAME:
            x = np.pad(x, ((0, 0), (0, FRAME - x.shape[1])))
        elif x.shape[1] > FRAME:
            x = x[:, :FRAME]
        if self._v5:
            out, self._state = self.session.run(
                None, {"input": x, "state": self._state, "sr": self._sr})
        else:
            out, self._h, self._c = self.session.run(
                None, {"input": x, "h": self._h, "c": self._c, "sr": self._sr})
        return float(np.asarray(out).reshape(-1)[0])


class EnergyVAD:
    """后备方案：能量门限。模型加载失败时使用。"""

    def __init__(self, threshold_db: float = -45.0):
        self.threshold = threshold_db

    def reset(self) -> None:
        pass

    def prob(self, frame: np.ndarray) -> float:
        x = np.asarray(frame, dtype=np.float32)
        r = float(np.sqrt(np.mean(x * x) + 1e-12))
        d = 20.0 * np.log10(max(r, 1e-9))
        # 平滑映射到 0~1
        return float(np.clip((d - self.threshold + 10.0) / 20.0, 0.0, 1.0))


def load_vad(models_dir: Path, threads: int = 2):
    p = Path(models_dir) / "silero_vad.onnx"
    if p.exists():
        try:
            return SileroVAD(p, threads=threads)
        except Exception as e:
            print(f"[VAD] Silero 加载失败，改用能量 VAD: {e}")
    return EnergyVAD()
