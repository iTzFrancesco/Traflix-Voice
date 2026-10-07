"""Parakeet TDT 0.6B v3 local backend (sherpa-onnx, int8 ONNX).

Kept in its own module on purpose: model.py only dispatches to it, and the
Groq/cloud flow in transcriber.py stays untouched.
"""
import os

import numpy as np
from huggingface_hub import hf_hub_download

from whisper_engine.constants import (
    CLOUD_EDGE_PAD_SECONDS,
    CLOUD_SILENCE_PADDING_SECONDS,
    PARAKEET_MODEL_ID,
    SAMPLE_RATE,
)

REPO_ID = "csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"
FILES = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")
_PAUSE_FRAME_SAMPLES = SAMPLE_RATE // 50
_MIN_PAUSE_FRAMES = 8
_CHUNK_TARGET_SAMPLES = 20 * SAMPLE_RATE
_CHUNK_SEARCH_SAMPLES = 8 * SAMPLE_RATE
_MIN_CHUNK_SAMPLES = _CHUNK_TARGET_SAMPLES - _CHUNK_SEARCH_SAMPLES
_CHUNK_CONTEXT_SAMPLES = int(CLOUD_EDGE_PAD_SECONDS * SAMPLE_RATE)
_PAUSE_PADDING_SAMPLES = int(CLOUD_SILENCE_PADDING_SECONDS * SAMPLE_RATE)
_MISSING_DEP_MESSAGE = (
    "Backend Parakeet non disponibile: pacchetto 'sherpa-onnx' non installato. "
    "Installalo con: py -m pip install sherpa-onnx (Windows) oppure "
    "python3 -m pip install sherpa-onnx, poi riavvia l'app. "
    "In alternativa passa al provider Cloud nella tab IA."
)


def is_backend_available():
    """True when the sherpa-onnx wheel can be imported in this interpreter."""
    try:
        import sherpa_onnx  # noqa: F401
        return True
    except ImportError:
        return False
    except Exception:
        return False


def backend_status():
    """Machine-readable backend probe used by the `check_backend` IPC command."""
    if is_backend_available():
        return {"available": True, "message": "Backend sherpa-onnx disponibile."}
    return {"available": False, "message": _MISSING_DEP_MESSAGE}


def is_parakeet_model(size):
    return size == PARAKEET_MODEL_ID or (
        isinstance(size, str) and size.startswith("parakeet")
    )


def model_dir(models_dir):
    return os.path.join(models_dir, PARAKEET_MODEL_ID)


def verify(models_dir):
    directory = model_dir(models_dir)
    for filename in FILES:
        path = os.path.join(directory, filename)
        if not os.path.exists(path):
            return False, f"File non trovato: {path}"
        try:
            if os.path.getsize(path) == 0:
                return False, f"File vuoto: {path}"
        except OSError as e:
            return False, str(e)
    return True, "OK"


def _worker_threads():
    try:
        count = os.cpu_count() or 1
    except Exception:
        count = 1
    # Six threads improved long-clip decoding on a 6-core/12-thread Windows
    # host without changing short-clip latency. Preserve the four-thread cap
    # on smaller CPUs so longer dictations do not crowd out the desktop.
    cap = 6 if count >= 12 else 4
    return max(1, min(cap, count))


def _compact_digital_pauses(audio):
    """Shorten zero-only pauses over one second, keeping both edge contexts."""
    if audio.size <= _CHUNK_TARGET_SAMPLES + _CHUNK_SEARCH_SAMPLES:
        return audio
    transitions = np.diff(np.concatenate(([False], audio == 0, [False])).astype(np.int8))
    starts = np.flatnonzero(transitions == 1)
    ends = np.flatnonzero(transitions == -1)
    long = ends - starts > SAMPLE_RATE
    if not long.any():
        return audio
    pieces = []
    cursor = 0
    for start, end in zip(starts[long], ends[long]):
        pieces.append(audio[cursor:start + _PAUSE_PADDING_SAMPLES])
        cursor = end - _PAUSE_PADDING_SAMPLES
    pieces.append(audio[cursor:])
    return np.concatenate(pieces)


def _split_at_pauses(audio):
    """Bound long inference inputs at quiet pauses, retaining every sample.

    Full-clip inference grows disproportionately on long dictations. A cut
    needs at least 160 ms of quiet audio; continuous or noisy speech stays
    together rather than forcing a word boundary. Scale the quiet threshold
    to the upper speech level so low-volume words and isolated clicks do not
    make the entire recording look silent.
    """
    if audio.size <= _CHUNK_TARGET_SAMPLES + _CHUNK_SEARCH_SAMPLES:
        return [audio]

    frame_count = audio.size // _PAUSE_FRAME_SAMPLES
    frames = audio[:frame_count * _PAUSE_FRAME_SAMPLES].reshape(
        frame_count, _PAUSE_FRAME_SAMPLES,
    )
    peaks = np.max(np.abs(frames), axis=1)
    quiet_threshold = min(0.001, float(np.percentile(peaks, 90)) * 0.01)
    quiet = peaks <= quiet_threshold
    if quiet.all():
        return [audio]
    transitions = np.diff(np.concatenate(([False], quiet, [False])).astype(np.int8))
    starts = np.flatnonzero(transitions == 1)
    ends = np.flatnonzero(transitions == -1)
    cuts = [
        int((start + end) * _PAUSE_FRAME_SAMPLES // 2)
        for start, end in zip(starts, ends)
        if end - start >= _MIN_PAUSE_FRAMES and start > 0 and end < frame_count
    ]

    chunks = []
    start = 0
    while audio.size - start > _CHUNK_TARGET_SAMPLES + _CHUNK_SEARCH_SAMPLES:
        eligible = [
            cut for cut in cuts
            if start + _MIN_CHUNK_SAMPLES <= cut <= audio.size - 2 * SAMPLE_RATE
        ]
        if not eligible:
            break
        target = start + _CHUNK_TARGET_SAMPLES
        cut = min(eligible, key=lambda point: abs(point - target))
        chunks.append(audio[start:cut])
        start = cut
    if not chunks:
        return [audio]
    chunks.append(audio[start:])
    return chunks


class _Segment:
    __slots__ = ("text",)

    def __init__(self, text):
        self.text = text


class ParakeetRecognizer:
    """Adapter exposing the transcribe() shape used by transcribe_local.

    transcribe_local() calls model.transcribe(recording, language=...), so
    matching that signature keeps the shared local path unchanged. The
    transducer handles the supported languages itself; language is accepted
    for interface compatibility and ignored.
    """

    def __init__(self, recognizer):
        self._recognizer = recognizer

    def snapshot(self):
        """Pin native sessions independently of the engine's unloadable adapter."""
        return ParakeetRecognizer(self._recognizer)

    def close(self):
        """Drop the native recognizer so RSS is released on unload.

        sherpa-onnx holds ONNX sessions (~1 GB) behind this handle. Clearing
        the reference plus gc.collect() in the engine is what actually frees
        the RAM; without it `model = None` alone can leave the memory mapped
        until the next collection cycle. An active transcription keeps its
        own reference until its last chunk has completed.
        """
        try:
            self._recognizer = None
        except Exception:
            pass

    def transcribe(self, recording, language=""):
        recognizer = self._recognizer
        audio = np.ascontiguousarray(recording, dtype=np.float32).reshape(-1)
        audio = _compact_digital_pauses(audio)
        chunks = _split_at_pauses(audio)
        segments = []
        for index, chunk in enumerate(chunks):
            # New boundaries need onset/tail context so TDT retains short
            # words beside the cut, even when the natural pause is brief.
            leading = _CHUNK_CONTEXT_SAMPLES if index else 0
            trailing = _CHUNK_CONTEXT_SAMPLES if index < len(chunks) - 1 else 0
            if leading or trailing:
                chunk = np.pad(chunk, (leading, trailing))
            stream = recognizer.create_stream()
            stream.accept_waveform(sample_rate=SAMPLE_RATE, waveform=chunk)
            recognizer.decode_stream(stream)
            segments.append(_Segment(stream.result.text.strip()))
        return segments


def load(models_dir, log_func, num_threads=None):
    is_valid, msg = verify(models_dir)
    if not is_valid:
        log_func({"status": "error", "message": f"Modello Parakeet non valido: {msg}"})
        raise Exception(f"Modello Parakeet non valido: {msg}")

    try:
        import sherpa_onnx
    except ImportError:
        log_func({"status": "error", "message": _MISSING_DEP_MESSAGE})
        raise

    directory = model_dir(models_dir)
    log_func({"status": "loading_model", "message": "Caricamento modello Parakeet TDT 0.6B v3..."})
    try:
        recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=os.path.join(directory, "encoder.int8.onnx"),
            decoder=os.path.join(directory, "decoder.int8.onnx"),
            joiner=os.path.join(directory, "joiner.int8.onnx"),
            tokens=os.path.join(directory, "tokens.txt"),
            num_threads=_worker_threads() if num_threads is None else num_threads,
            sample_rate=SAMPLE_RATE,
            model_type="nemo_transducer",
        )
    except Exception as e:
        log_func({"status": "error", "message": f"Errore caricamento modello Parakeet: {str(e)}"})
        raise
    log_func({"status": "info", "message": "Modello Parakeet caricato."})
    return ParakeetRecognizer(recognizer)


def _remove_partial_files(directory):
    for filename in FILES:
        try:
            path = os.path.join(directory, filename)
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


def download(models_dir, log_func):
    directory = model_dir(models_dir)
    try:
        os.makedirs(directory, exist_ok=True)
    except Exception as e:
        log_func({"status": "download_error", "message": f"Download fallito: {str(e)}", "model": PARAKEET_MODEL_ID})
        return

    try:
        log_func({"status": "downloading", "message": "Download modello Parakeet TDT 0.6B v3...", "model": PARAKEET_MODEL_ID})
        for filename in FILES:
            hf_hub_download(
                repo_id=REPO_ID,
                filename=filename,
                local_dir=directory,
                local_dir_use_symlinks=False,
            )

        is_valid, msg = verify(models_dir)
        if not is_valid:
            log_func({"status": "error", "message": f"Verifica fallita: {msg}"})
            _remove_partial_files(directory)
            return

        log_func({"status": "download_complete", "message": "Modello Parakeet scaricato.", "model": PARAKEET_MODEL_ID})
    except Exception as e:
        log_func({"status": "download_error", "message": f"Download fallito: {str(e)}", "model": PARAKEET_MODEL_ID})
        _remove_partial_files(directory)
