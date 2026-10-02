"""Speech presence detection on a copy of the complete 16 kHz mono capture."""

import hashlib
from pathlib import Path
import threading

import numpy as np

SILERO_VAD_MODEL_URL = "https://github.com/snakers4/silero-vad/raw/refs/tags/v5.0/files/silero_vad.onnx"
SILERO_VAD_MODEL_SHA256 = "6b99cbfd39246b6706f98ec13c7c50c6b299181f2474fa05cbc8046acc274396"
SILERO_VAD_MODEL_BYTES = 2313101

_WINDOW_SHIFT = 512
_WINDOW_OVERLAP = 64
_TAIL_PADDING = 1536
_QUIET_PEAK_TARGET = 0.2


class SpeechGate:
    """Preload once outside capture; reuse one CPU model across recordings."""

    def __init__(self, model_path: str | Path):
        self._lock = threading.Lock()
        self._model = None
        try:
            path = Path(model_path)
            if path.stat().st_size != SILERO_VAD_MODEL_BYTES:
                return
            if hashlib.sha256(path.read_bytes()).hexdigest() != SILERO_VAD_MODEL_SHA256:
                return

            # Unsupported or corrupt models can terminate the native process.
            # Only the pinned v5 model reaches sherpa's loader.
            import sherpa_onnx

            config = sherpa_onnx.VadModelConfig()
            config.sample_rate = 16000
            config.num_threads = 1
            config.provider = "cpu"
            config.silero_vad.model = str(path)
            config.silero_vad.window_size = _WINDOW_SHIFT
            config.silero_vad.threshold = 0.5
            config.silero_vad.min_speech_duration = 0.032
            config.silero_vad.min_silence_duration = 0.1
            model = sherpa_onnx.VadModel.create(config)
            if model.window_size() == _WINDOW_SHIFT + _WINDOW_OVERLAP:
                self._model = model
        except Exception:
            self._model = None

    @property
    def available(self) -> bool:
        with self._lock:
            return self._model is not None

    def close(self) -> None:
        with self._lock:
            self._model = None

    def detect(self, recording) -> bool | None:
        """Return True for voice, False for no voice, None when unavailable."""
        try:
            source = np.asarray(recording)
            if source.ndim == 2 and source.shape[1] == 1:
                source = source[:, 0]
            if source.ndim != 1 or source.dtype.kind not in "fiu":
                return None
            with np.errstate(over="ignore", invalid="ignore"):
                samples = np.asarray(source, dtype=np.float32)
            if not np.isfinite(samples).all():
                return None
        except Exception:
            return None

        with self._lock:
            model = self._model
            if model is None:
                return None
            result = None
            try:
                model.reset()
                peak = float(np.max(np.abs(samples))) if samples.size else 0.0
                if peak == 0.0:
                    result = False
                else:
                    # Normalize only the VAD copy: quiet voice has no rejection
                    # threshold, and the ASR capture retains every original sample.
                    analysis = np.pad(samples, (_WINDOW_OVERLAP, _TAIL_PADDING))
                    if peak < _QUIET_PEAK_TARGET:
                        np.divide(analysis, peak, out=analysis)
                        np.multiply(analysis, _QUIET_PEAK_TARGET, out=analysis)
                    result = False
                    width = _WINDOW_SHIFT + _WINDOW_OVERLAP
                    for offset in range(0, analysis.size, _WINDOW_SHIFT):
                        block = analysis[offset:offset + width]
                        if block.size < width:
                            block = np.pad(block, (0, width - block.size))
                        if model.is_speech(block):
                            result = True
                            break
            except Exception:
                self._model = None
                result = None
            finally:
                try:
                    model.reset()
                except Exception:
                    self._model = None
                    result = None
            return result
