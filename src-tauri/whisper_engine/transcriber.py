import io
import os
import struct
import threading
import httpx
import numpy as np
import concurrent.futures

from whisper_engine.constants import (
    GROQ_MODEL,
    GROQ_MULTIPART_BOUNDARY,
    GROQ_TRANSCRIPTION_URL,
    CLOUD_SILENCE_PADDING_SECONDS,
    CLOUD_SILENCE_THRESHOLD,
    SAMPLE_RATE,
    TRANSCRIPTION_TIMEOUT,
)
from whisper_engine.groq_tracker import record_groq_usage

_TRAF_DEBUG = os.environ.get("TRAF_DEBUG") == "1"
_GROQ_CLIENT = None
_GROQ_CLIENT_KEY = None
_GROQ_CLIENT_LOCK = threading.Lock()
_USAGE_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="groq-usage"
)
_MULTIPART_BOUNDARY = GROQ_MULTIPART_BOUNDARY.encode("ascii")
_MODEL_FIELD = (
    b"--" + _MULTIPART_BOUNDARY + b"\r\n"
    b'Content-Disposition: form-data; name="model"\r\n\r\n'
    + GROQ_MODEL.encode("ascii")
    + b"\r\n"
)
_RESPONSE_FORMAT_FIELD = (
    b"--" + _MULTIPART_BOUNDARY + b"\r\n"
    b'Content-Disposition: form-data; name="response_format"\r\n\r\ntext\r\n'
)
_LANGUAGE_FIELD_PREFIX = (
    b"--" + _MULTIPART_BOUNDARY + b"\r\n"
    b'Content-Disposition: form-data; name="language"\r\n\r\n'
)
_FILE_FIELD_PREFIX = (
    b"--" + _MULTIPART_BOUNDARY + b"\r\n"
    b'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
    b"Content-Type: audio/wav\r\n\r\n"
)
_MULTIPART_SUFFIX = b"\r\n--" + _MULTIPART_BOUNDARY + b"--\r\n"
_MULTIPART_BASE_PREFIX = _MODEL_FIELD + _RESPONSE_FORMAT_FIELD
_MULTIPART_PREFIXES = {
    language: (
        _MULTIPART_BASE_PREFIX
        + _LANGUAGE_FIELD_PREFIX
        + language.encode("ascii")
        + b"\r\n"
        + _FILE_FIELD_PREFIX
    )
    for language in ("it", "en", "fr", "de", "es", "pt")
}
_MULTIPART_PREFIXES[None] = _MULTIPART_BASE_PREFIX + _FILE_FIELD_PREFIX
_WAV_HEADER = struct.Struct("<4sI4s4sIHHIIHH4sI")
_GROQ_TRANSCRIPTION_URL = httpx.URL(GROQ_TRANSCRIPTION_URL)
_CLOUD_SILENCE_PADDING_SAMPLES = int(SAMPLE_RATE * CLOUD_SILENCE_PADDING_SECONDS)
_CLOUD_TRIM_MASK_LIMIT = SAMPLE_RATE * 8
_CLOUD_TRIM_SCAN_CHUNK = SAMPLE_RATE


def _ignore_response_cookies(_response):
    """Groq uses bearer auth; response cookies are irrelevant to this client."""
    return None


def create_groq_client(groq_api_key):
    """Create one persistent HTTP client for the Groq endpoint."""
    client = httpx.Client(
        headers={
            "Authorization": f"Bearer {groq_api_key}",
            "Content-Type": f"multipart/form-data; boundary={GROQ_MULTIPART_BOUNDARY}",
        },
        timeout=httpx.Timeout(30.0, connect=10.0, read=25.0),
        limits=httpx.Limits(
            max_connections=2,
            max_keepalive_connections=1,
            keepalive_expiry=60.0,
        ),
    )
    # The transcription API is stateless and authenticates every request via
    # Authorization. Skipping CookieJar extraction avoids urllib's relatively
    # expensive response-header conversion on every successful call.
    client.cookies.extract_cookies = _ignore_response_cookies
    return client


def get_groq_client(groq_api_key):
    """Return a keep-alive HTTP client, rebuilding it only when the key changes."""
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
    if (
        recording.size >= SAMPLE_RATE * 2
        and recording.max() <= 1.0
        and recording.min() >= -1.0
    ):
        # PortAudio's float32 contract is already normalized. For normal
        # dictations, write directly into the target dtype and avoid a second
        # recording-sized float buffer. Keep the exact clipping path for
        # synthetic/out-of-range or non-finite inputs.
        audio_int16 = np.empty(recording.size, dtype=np.int16)
        np.multiply(recording, 32767.0, out=audio_int16, casting="unsafe")
    else:
        clipped = np.clip(recording, -1.0, 1.0)
        np.multiply(clipped, 32767.0, out=clipped)
        audio_int16 = clipped.astype(np.int16)
    pcm_data = audio_int16.tobytes()
    data_size = len(pcm_data)
    wav_header = _WAV_HEADER.pack(
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


def encode_cloud_multipart(wav_buffer, language):
    """Build the fixed cloud multipart envelope without HTTPX re-encoding it."""
    prefix = _MULTIPART_PREFIXES.get(language)
    if prefix is None:
        prefix = _MULTIPART_BASE_PREFIX
        if language:
            prefix += _LANGUAGE_FIELD_PREFIX + language.encode("utf-8") + b"\r\n"
        prefix += _FILE_FIELD_PREFIX
    return b"".join((prefix, wav_buffer.getvalue(), _MULTIPART_SUFFIX))


def trim_cloud_silence(recording):
    """Remove only leading/trailing near-silence before a cloud upload."""
    if recording.size == 0:
        return recording

    threshold = CLOUD_SILENCE_THRESHOLD
    if abs(recording[0]) >= threshold and abs(recording[-1]) >= threshold:
        return recording

    if recording.size <= _CLOUD_TRIM_MASK_LIMIT:
        active = np.abs(recording) >= threshold
        if not active.any():
            return recording[:0]
        first_active = int(active.argmax())
        last_active = recording.size - 1 - int(active[::-1].argmax())
    else:
        # Avoid allocating a recording-sized mask for long dictations. The
        # min/max check makes long silence cheap; edge scans allocate at most
        # one second of temporary booleans at a time.
        if recording.max() < threshold and recording.min() > -threshold:
            return recording[:0]

        first_active = None
        for chunk_start in range(0, recording.size, _CLOUD_TRIM_SCAN_CHUNK):
            chunk = recording[chunk_start : chunk_start + _CLOUD_TRIM_SCAN_CHUNK]
            active = np.abs(chunk) >= threshold
            if active.any():
                first_active = chunk_start + int(active.argmax())
                break
        if first_active is None:
            return recording[:0]

        for chunk_end in range(recording.size, first_active, -_CLOUD_TRIM_SCAN_CHUNK):
            chunk_start = max(first_active, chunk_end - _CLOUD_TRIM_SCAN_CHUNK)
            chunk = recording[chunk_start:chunk_end]
            active = np.abs(chunk) >= threshold
            if active.any():
                last_active = chunk_end - 1 - int(active[::-1].argmax())
                break

    start = max(0, first_active - _CLOUD_SILENCE_PADDING_SAMPLES)
    end = min(
        recording.size,
        last_active + _CLOUD_SILENCE_PADDING_SAMPLES + 1,
    )
    return recording[start:end]


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
        cloud_recording = trim_cloud_silence(recording)
        if cloud_recording.size == 0:
            log_func({"status": "ready", "message": "Nessun audio riconosciuto."})
            return

        buffer = encode_cloud_multipart(
            encode_wav(cloud_recording),
            language if language != "auto" else None,
        )

        client = get_groq_client(groq_api_key)

        request = httpx.Request(
            "POST",
            _GROQ_TRANSCRIPTION_URL,
            headers=client.headers,
            content=buffer,
        )
        response = client.send(request)
        if response.status_code != 200:
            response.raise_for_status()

        # Groq returns UTF-8 text; decoding the already-buffered body avoids
        # HTTPX charset detection on the success path.
        text = response.content.decode("utf-8").strip()

        if _TRAF_DEBUG:
            import sys as _sys
            _sys.stderr.write(f"[PY-DEBUG] transcribe_cloud result len={len(text)} duration={recording_duration}\n")
            _sys.stderr.flush()
        log_func({"status": "result", "text": text, "duration": recording_duration})
        if models_dir:
            _USAGE_EXECUTOR.submit(
                record_groq_usage,
                models_dir,
                duration_seconds=recording_duration,
            )

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
