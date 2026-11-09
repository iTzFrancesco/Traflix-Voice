"""Parakeet Ultra audio preparation and native CPU/GPU dispatch."""
import os
import threading
import unicodedata

import numpy as np

from whisper_engine.constants import (
    CLOUD_EDGE_PAD_SECONDS,
    CLOUD_SILENCE_PADDING_SECONDS,
    DEFAULT_LOCAL_MODEL,
    LEGACY_LOCAL_MODEL_IDS,
    PARAKEET_MODEL_ID,
    SAMPLE_RATE,
)

_PAUSE_FRAME_SAMPLES = SAMPLE_RATE // 50
_MIN_PAUSE_FRAMES = 8
_CHUNK_CONTEXT_SAMPLES = int(CLOUD_EDGE_PAD_SECONDS * SAMPLE_RATE)
_CHUNK_OVERLAP_SAMPLES = SAMPLE_RATE // 2
_MAX_SINGLE_PASS_SAMPLES = 28 * SAMPLE_RATE
_MAX_CHUNK_SAMPLES = _MAX_SINGLE_PASS_SAMPLES - 2 * _CHUNK_OVERLAP_SAMPLES
_MAX_FINAL_CORE_SAMPLES = (
    _MAX_SINGLE_PASS_SAMPLES - _CHUNK_OVERLAP_SAMPLES - _CHUNK_CONTEXT_SAMPLES
)
_MIN_TRAILING_SAMPLES = 2 * SAMPLE_RATE
_PAUSE_PADDING_SAMPLES = int(CLOUD_SILENCE_PADDING_SECONDS * SAMPLE_RATE)


def is_backend_available():
    from whisper_engine import native_parakeet
    return native_parakeet.helper_path() is not None


def backend_status():
    from whisper_engine import native_parakeet
    if native_parakeet.helper_path() is None:
        return {
            "available": False,
            "message": "Motore nativo Parakeet Ultra non trovato. Ricompila l'helper e riavvia l'app.",
        }
    if native_parakeet.gpu_available():
        return {"available": True, "message": "Parakeet Ultra disponibile su CPU e GPU."}
    return {"available": True, "message": "Parakeet Ultra disponibile su CPU."}


def is_parakeet_model(size):
    return size == DEFAULT_LOCAL_MODEL or size in LEGACY_LOCAL_MODEL_IDS


def normalize_model_id(size):
    if size is None or size == "":
        return DEFAULT_LOCAL_MODEL
    if is_parakeet_model(size):
        return DEFAULT_LOCAL_MODEL
    raise ValueError(f"Modello locale non supportato: {size}. È disponibile solo Parakeet Ultra.")


def model_dir(models_dir):
    return os.path.join(models_dir, PARAKEET_MODEL_ID)


def verify(models_dir):
    from whisper_engine import native_parakeet
    directory = model_dir(models_dir)
    if native_parakeet.verify(directory):
        return True, "OK"
    return False, f"File modello mancante o dimensione non valida: {native_parakeet.FILENAME}"


def _compact_digital_pauses(audio):
    """Shorten zero-only pauses over one second, keeping both edge contexts."""
    if audio.size <= _MAX_SINGLE_PASS_SAMPLES:
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
    """Split long audio at pauses or nearby low-energy points, retaining all samples."""
    if audio.size <= _MAX_SINGLE_PASS_SAMPLES:
        return [audio]

    frame_count = audio.size // _PAUSE_FRAME_SAMPLES
    frames = audio[:frame_count * _PAUSE_FRAME_SAMPLES].reshape(
        frame_count, _PAUSE_FRAME_SAMPLES,
    )
    peaks = np.max(np.abs(frames), axis=1)
    # Keep the pause detector conservative: a quiet voice beside louder speech
    # must not be classified as silence and removed from the transcript.
    quiet_threshold = min(0.0001, float(np.percentile(peaks, 90)) * 0.0001)
    quiet = peaks <= quiet_threshold
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
    # The final core receives a left overlap and trailing edge padding. Start
    # another chunk before those additions could push the helper input over
    # Ultra's conservative 28-second single-pass limit.
    while audio.size - start > _MAX_FINAL_CORE_SAMPLES:
        max_cut = min(start + _MAX_CHUNK_SAMPLES, audio.size - _MIN_TRAILING_SAMPLES)
        min_cut = start + SAMPLE_RATE
        eligible = [cut for cut in cuts if min_cut <= cut <= max_cut]
        if eligible:
            # Prefer the latest real pause that keeps this decoder input under
            # its 28-second operating limit.
            cut = max(eligible)
        else:
            # Continuous speech has no safe pause. Search the final two seconds
            # before the limit and overlap both sides of the low-energy cut.
            search_start = max(min_cut, max_cut - 2 * SAMPLE_RATE)
            search_end = max_cut
            first = max(0, search_start // _PAUSE_FRAME_SAMPLES)
            last = min(frame_count, (search_end + _PAUSE_FRAME_SAMPLES - 1) // _PAUSE_FRAME_SAMPLES)
            if first < last:
                cut = (first + int(np.argmin(peaks[first:last]))) * _PAUSE_FRAME_SAMPLES
                cut = min(max(cut, min_cut), max_cut)
            else:
                cut = max_cut
        if cut <= start or cut > start + _MAX_CHUNK_SAMPLES:
            cut = max_cut
        chunks.append(audio[start:cut])
        start = cut
    chunks.append(audio[start:])
    return chunks


class _Segment:
    __slots__ = ("text",)

    def __init__(self, text):
        self.text = text


class ParakeetRecognizer:
    """Adapter for offline recognizers that expose create_stream/decode_stream."""

    def __init__(self, recognizer):
        self._recognizer = recognizer

    def snapshot(self):
        return ParakeetRecognizer(self._recognizer)

    def close(self):
        self._recognizer = None

    def transcribe(self, recording, language=""):
        recognizer = self._recognizer
        audio = _compact_digital_pauses(np.ascontiguousarray(recording, dtype=np.float32).reshape(-1))
        chunks = _split_at_pauses(audio)
        segments = []
        for index, chunk in enumerate(chunks):
            leading = _CHUNK_CONTEXT_SAMPLES if index else 0
            trailing = _CHUNK_CONTEXT_SAMPLES if index < len(chunks) - 1 else 0
            if leading or trailing:
                chunk = np.pad(chunk, (leading, trailing))
            stream = recognizer.create_stream()
            stream.accept_waveform(sample_rate=SAMPLE_RATE, waveform=chunk)
            recognizer.decode_stream(stream)
            segments.append(_Segment(stream.result.text.strip()))
        return segments


class _AdaptiveSession:
    def __init__(self, model, cpu_factory, log_func):
        self.model = model
        self.cpu_factory = cpu_factory
        self.log = log_func
        self.lock = threading.Lock()

    def transcribe(self, recording, language):
        from whisper_engine import native_parakeet
        with self.lock:
            if self.model is None:
                self.model = self.cpu_factory()
            try:
                return self.model.transcribe(recording, language=language)
            except Exception:
                if self.model._session.metadata.get("backend") == "cpu":
                    raise
                self.model.close()
                self.model = None
                native_parakeet.disable_gpu()
                self.log({"status": "warning", "message": "GPU non disponibile. Passaggio automatico alla CPU."})
                self.model = self.cpu_factory()
                return self.model.transcribe(recording, language=language)

    def close(self):
        with self.lock:
            if self.model is not None:
                self.model.close()
                self.model = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


class AdaptiveRecognizer:
    def __init__(self, session):
        self._recognizer = session

    def snapshot(self):
        return AdaptiveRecognizer(self._recognizer)

    def close(self):
        self._recognizer = None

    def transcribe(self, recording, language=""):
        if self._recognizer is None:
            raise RuntimeError("La sessione Parakeet Ultra è stata rilasciata.")
        return self._recognizer.transcribe(recording, language)


def _load_native(models_dir, log_func):
    from whisper_engine import native_parakeet
    directory = model_dir(models_dir)
    if native_parakeet.helper_path() is None:
        raise RuntimeError("Motore nativo Parakeet Ultra non trovato. Ricompila l'helper e riavvia l'app.")
    if native_parakeet.gpu_available():
        model = native_parakeet.load(directory, log_func)
        if model._session.metadata.get("backend") != "cpu":
            return AdaptiveRecognizer(_AdaptiveSession(
                model,
                lambda: native_parakeet.load(directory, log_func, cpu_only=True),
                log_func,
            ))
        return model
    return native_parakeet.load(directory, log_func, cpu_only=True)


def load(models_dir, log_func):
    from whisper_engine import native_parakeet
    directory = model_dir(models_dir)
    if native_parakeet.helper_path() is None:
        raise RuntimeError("Motore nativo Parakeet Ultra non trovato. Ricompila l'helper e riavvia l'app.")
    downloaded = False
    if not native_parakeet.verify(directory, checksum=True):
        model_path = os.path.join(directory, native_parakeet.FILENAME)
        if os.path.exists(model_path):
            try:
                os.remove(model_path)
            except OSError as error:
                raise RuntimeError(f"Il modello Parakeet Ultra non valido non può essere sostituito: {error}") from error
        log_func({
            "status": "downloading",
            "model": PARAKEET_MODEL_ID,
            "message": "Download Parakeet Ultra GGUF (~740 MB)...",
        })
        native_parakeet.download(directory)
        downloaded = True
    model = _load_native(models_dir, log_func)
    if downloaded:
        log_func({"status": "download_complete", "model": PARAKEET_MODEL_ID,
                  "message": "Parakeet Ultra scaricato, verificato e pronto."})
    return model


def download(models_dir, log_func):
    from whisper_engine import native_parakeet
    directory = model_dir(models_dir)
    if native_parakeet.helper_path() is None:
        log_func({"status": "download_error", "model": PARAKEET_MODEL_ID,
                  "message": "Motore nativo Parakeet Ultra non trovato. Ricompila l'helper e riavvia l'app."})
        return
    log_func({"status": "downloading", "model": PARAKEET_MODEL_ID,
              "message": "Download Parakeet Ultra GGUF (~740 MB)..."})
    try:
        model_path = os.path.join(directory, native_parakeet.FILENAME)
        if os.path.exists(model_path) and not native_parakeet.verify(directory, checksum=True):
            os.remove(model_path)
        native_parakeet.download(directory)
        model = _load_native(models_dir, log_func)
        model.close()
        log_func({"status": "download_complete", "model": PARAKEET_MODEL_ID,
                  "message": "Parakeet Ultra scaricato, verificato e pronto."})
    except Exception as error:
        log_func({"status": "download_error", "model": PARAKEET_MODEL_ID,
                  "message": f"Download Parakeet Ultra non riuscito: {error}"})
