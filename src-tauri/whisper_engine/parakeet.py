"""Parakeet TDT 0.6B v3 local backend (sherpa-onnx, int8 ONNX).

Kept in its own module on purpose: model.py only dispatches to it, and the
Groq/cloud flow in transcriber.py stays untouched.
"""
import os

import numpy as np
from huggingface_hub import hf_hub_download

from whisper_engine.constants import PARAKEET_MODEL_ID, SAMPLE_RATE

REPO_ID = "csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"
FILES = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")
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
    # Four threads saturate the transducer on a 6-core CPU while leaving
    # headroom for the rest of the desktop during dictation.
    return max(1, min(4, count))


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

    def close(self):
        """Drop the native recognizer so RSS is released on unload.

        sherpa-onnx holds ONNX sessions (~1 GB) behind this handle. Clearing
        the reference plus gc.collect() in the engine is what actually frees
        the RAM; without it `model = None` alone can leave the memory mapped
        until the next collection cycle.
        """
        try:
            self._recognizer = None
        except Exception:
            pass

    def transcribe(self, recording, language=""):
        audio = np.ascontiguousarray(recording, dtype=np.float32).reshape(-1)
        stream = self._recognizer.create_stream()
        stream.accept_waveform(sample_rate=SAMPLE_RATE, waveform=audio)
        self._recognizer.decode_stream(stream)
        return [_Segment(stream.result.text.strip())]


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
