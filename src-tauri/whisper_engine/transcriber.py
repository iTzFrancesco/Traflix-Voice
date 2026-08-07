import io
import os
import struct
import threading
import httpx
import numpy as np
import concurrent.futures

from whisper_engine.constants import SAMPLE_RATE, TRANSCRIPTION_TIMEOUT, GROQ_MODEL
from whisper_engine.groq_tracker import record_groq_usage

_TRAF_DEBUG = os.environ.get("TRAF_DEBUG") == "1"
_GROQ_CLIENT = None
_GROQ_CLIENT_KEY = None
_GROQ_CLIENT_LOCK = threading.Lock()


def create_groq_client(groq_api_key):
    """Create one configured client; callers can safely reuse it."""
    from groq import Groq

    return Groq(
        api_key=groq_api_key,
        http_client=httpx.Client(
            timeout=httpx.Timeout(30.0, connect=10.0, read=25.0)
        ),
    )


def get_groq_client(groq_api_key):
    """Return a keep-alive client, rebuilding it only when the key changes."""
    global _GROQ_CLIENT, _GROQ_CLIENT_KEY

    with _GROQ_CLIENT_LOCK:
        if _GROQ_CLIENT is not None and _GROQ_CLIENT_KEY == groq_api_key:
            return _GROQ_CLIENT

        old_client = _GROQ_CLIENT
        client = create_groq_client(groq_api_key)
        _GROQ_CLIENT = client
        _GROQ_CLIENT_KEY = groq_api_key

        if old_client is not None:
            close = getattr(old_client, "close", None)
            if callable(close):
                close()

        return client


def close_groq_client():
    """Close the cached client during sidecar shutdown."""
    global _GROQ_CLIENT, _GROQ_CLIENT_KEY

    with _GROQ_CLIENT_LOCK:
        client = _GROQ_CLIENT
        _GROQ_CLIENT = None
        _GROQ_CLIENT_KEY = None

    if client is not None:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def encode_wav(recording):
    """Encode mono float32 samples as the PCM WAV payload Groq accepts."""
    audio_int16 = (np.clip(recording, -1.0, 1.0) * 32767).astype(np.int16)
    pcm_data = audio_int16.tobytes()
    data_size = len(pcm_data)
    wav_header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        SAMPLE_RATE,
        SAMPLE_RATE * 2,
        2,
        16,
        b"data",
        data_size,
    )
    return io.BytesIO(wav_header + pcm_data)


def transcribe_local(model, recording, language, recording_duration, shutting_down, log_func):
    if shutting_down:
        return

    lang_param = "" if language == "auto" else language

    def _run_inference():
        segments = model.transcribe(recording, language=lang_param)
        text = " ".join(s.text for s in segments).strip()
        return text

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_run_inference)
        try:
            text = future.result(timeout=TRANSCRIPTION_TIMEOUT)
        except concurrent.futures.TimeoutError:
            log_func({"status": "error", "message": f"Timeout dopo {TRANSCRIPTION_TIMEOUT}s"})
            log_func({"status": "ready", "message": "Motore Whisper pronto."})
            return

    if _TRAF_DEBUG:
        import sys as _sys
        _sys.stderr.write(f"[PY-DEBUG] transcribe_local result len={len(text)} duration={recording_duration}\n")
        _sys.stderr.flush()
    log_func({"status": "result", "text": text, "duration": recording_duration})


def transcribe_cloud(recording, language, recording_duration, groq_api_key, shutting_down, log_func, models_dir):
    if shutting_down:
        return

    if not groq_api_key:
        log_func({"status": "error", "message": "Groq API key non configurata. Inseriscila nella tab Sistema."})
        log_func({"status": "ready", "message": "Motore Whisper pronto."})
        return

    try:
        buffer = encode_wav(recording)

        client = get_groq_client(groq_api_key)
        lang_param = language if language != "auto" else None

        transcription = client.audio.transcriptions.create(
            model=GROQ_MODEL,
            file=("audio.wav", buffer, "audio/wav"),
            language=lang_param,
            response_format="text",
        )

        text = transcription if isinstance(transcription, str) else transcription.text
        text = text.strip()

        if _TRAF_DEBUG:
            import sys as _sys
            _sys.stderr.write(f"[PY-DEBUG] transcribe_cloud result len={len(text)} duration={recording_duration}\n")
            _sys.stderr.flush()
        log_func({"status": "result", "text": text, "duration": recording_duration})
        record_groq_usage(models_dir, duration_seconds=recording_duration)

    except ImportError:
        log_func({"status": "error", "message": "Libreria 'groq' non installata. Esegui: pip install groq"})
        log_func({"status": "ready", "message": "Motore Whisper pronto."})
    except Exception as e:
        err_msg = str(e)
        if "429" in err_msg or "rate" in err_msg.lower() or "limit" in err_msg.lower():
            log_func({"status": "rate_limit", "message": "Limite API Groq raggiunto. Riprova tra qualche minuto o passa al modello locale."})
        else:
            log_func({"status": "error", "message": f"Errore API Groq: {err_msg}"})
        log_func({"status": "ready", "message": "Motore Whisper pronto."})
