import io
import math
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
_GROQ_CLIENT_LEASES = {}
_GROQ_RETIRED_CLIENTS = {}
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
_CLOUD_ERROR_MESSAGE_LIMIT = 512
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
        timeout=httpx.Timeout(30.0, connect=10.0, read=25.0, pool=5.0),
        limits=httpx.Limits(
            max_connections=1,
            max_keepalive_connections=1,
            keepalive_expiry=60.0,
        ),
    )
    # HTTP/1.1 is persistent by default, and Groq's tiny text response does
    # not benefit from content compression. Omitting both defaults reduces
    # request header normalization/wire bytes without changing semantics.
    client.headers.pop("Connection", None)
    client.headers.pop("Accept-Encoding", None)
    # The transcription API is stateless and authenticates every request via
    # Authorization. Skipping CookieJar extraction avoids urllib's relatively
    # expensive response-header conversion on every successful call.
    client.cookies.extract_cookies = _ignore_response_cookies
    return client


def _close_client(client):
    close = getattr(client, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            # Cleanup must not mask the actual cloud result or shutdown path.
            pass


def _get_or_create_groq_client(groq_api_key, lease=False):
    """Select a client atomically and optionally hold it for one request."""
    global _GROQ_CLIENT, _GROQ_CLIENT_KEY

    with _GROQ_CLIENT_LOCK:
        if _GROQ_CLIENT is not None and _GROQ_CLIENT_KEY == groq_api_key:
            client = _GROQ_CLIENT
            idle_client = None
        else:
            old_client = _GROQ_CLIENT
            client = create_groq_client(groq_api_key)
            _GROQ_CLIENT = client
            _GROQ_CLIENT_KEY = groq_api_key
            idle_client = None
            if old_client is not None:
                old_id = id(old_client)
                if _GROQ_CLIENT_LEASES.get(old_id, 0):
                    _GROQ_RETIRED_CLIENTS[old_id] = old_client
                else:
                    idle_client = old_client

        if lease:
            client_id = id(client)
            _GROQ_CLIENT_LEASES[client_id] = (
                _GROQ_CLIENT_LEASES.get(client_id, 0) + 1
            )

    # Transport cleanup never runs while the cache lock is held.
    if idle_client is not None:
        _close_client(idle_client)
    return client


def get_groq_client(groq_api_key):
    """Return a keep-alive HTTP client, rebuilding only when the key changes."""
    return _get_or_create_groq_client(groq_api_key)


def acquire_groq_client(groq_api_key):
    """Return a client protected from key rotation until it is released."""
    return _get_or_create_groq_client(groq_api_key, lease=True)


def release_groq_client(client):
    """Release a request lease and close a retired client when it is idle."""
    client_id = id(client)
    idle_client = None
    with _GROQ_CLIENT_LOCK:
        count = _GROQ_CLIENT_LEASES.get(client_id, 0)
        if count <= 1:
            _GROQ_CLIENT_LEASES.pop(client_id, None)
            idle_client = _GROQ_RETIRED_CLIENTS.pop(client_id, None)
        else:
            _GROQ_CLIENT_LEASES[client_id] = count - 1
    if idle_client is not None:
        _close_client(idle_client)


def close_groq_client():
    """Close the cached client during sidecar shutdown."""
    global _GROQ_CLIENT, _GROQ_CLIENT_KEY

    idle_clients = []
    with _GROQ_CLIENT_LOCK:
        client = _GROQ_CLIENT
        _GROQ_CLIENT = None
        _GROQ_CLIENT_KEY = None
        if client is not None:
            client_id = id(client)
            if _GROQ_CLIENT_LEASES.get(client_id, 0):
                _GROQ_RETIRED_CLIENTS[client_id] = client
            else:
                idle_clients.append(client)

        for client_id, retired in list(_GROQ_RETIRED_CLIENTS.items()):
            if not _GROQ_CLIENT_LEASES.get(client_id, 0):
                _GROQ_RETIRED_CLIENTS.pop(client_id, None)
                idle_clients.append(retired)

    for idle_client in idle_clients:
        _close_client(idle_client)


def _encode_wav_payload(recording, assume_normalized=False):
    """Return the complete PCM WAV bytes for a mono recording."""
    if assume_normalized:
        # sounddevice delivers float32 samples in [-1, 1]. The cloud capture
        # path has already crossed that contract boundary, so skip two full
        # recording-sized min/max scans before the int16 conversion.
        audio_int16 = np.empty(recording.size, dtype=np.int16)
        with np.errstate(invalid="ignore", over="ignore"):
            np.multiply(recording, 32767.0, out=audio_int16, casting="unsafe")
    elif (
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
    return wav_header + pcm_data


def encode_wav(recording, assume_normalized=False):
    """Encode mono float32 samples as the PCM WAV payload Groq accepts."""
    return io.BytesIO(_encode_wav_payload(recording, assume_normalized))


def _cloud_multipart_prefix(language):
    prefix = _MULTIPART_PREFIXES.get(language)
    if prefix is None:
        prefix = _MULTIPART_BASE_PREFIX
        if language:
            prefix += _LANGUAGE_FIELD_PREFIX + language.encode("utf-8") + b"\r\n"
        prefix += _FILE_FIELD_PREFIX
    return prefix


def _build_cloud_multipart(wav_payload, language):
    return b"".join(
        (_cloud_multipart_prefix(language), wav_payload, _MULTIPART_SUFFIX)
    )


def encode_cloud_multipart(wav_buffer, language):
    """Build the fixed cloud multipart envelope without HTTPX re-encoding it."""
    get_buffer = getattr(wav_buffer, "getbuffer", None)
    if callable(get_buffer):
        return _build_cloud_multipart(get_buffer(), language)
    return _build_cloud_multipart(wav_buffer.getvalue(), language)


def encode_cloud_multipart_from_recording(
    recording,
    language,
    assume_normalized=False,
):
    """Encode and wrap cloud audio without an intermediate BytesIO copy."""
    return _build_cloud_multipart(
        _encode_wav_payload(recording, assume_normalized),
        language,
    )


def _is_rate_limit_error(error, response=None):
    status_code = getattr(response, "status_code", None)
    if status_code is None:
        error_response = getattr(error, "response", None)
        status_code = getattr(error_response, "status_code", None)
    if status_code == 429:
        return True

    message = str(error).lower()
    return "429" in message or "rate" in message or "limit" in message


def _prepare_cloud_recording(recording):
    """Normalize direct callers to the mono float32 contract used by capture."""
    if isinstance(recording, np.ndarray):
        if recording.ndim == 1 and recording.dtype == np.float32:
            return recording
        if (
            recording.ndim == 2
            and recording.shape[1] == 1
            and recording.dtype == np.float32
        ):
            return recording[:, 0]

    prepared = np.asarray(recording)
    if prepared.ndim == 2 and prepared.shape[1] == 1:
        prepared = prepared[:, 0]
    elif prepared.ndim != 1:
        raise ValueError("L'audio cloud deve essere un array mono 1-D.")
    if prepared.dtype != np.float32:
        prepared = prepared.astype(np.float32, copy=False)
    return prepared


def _normalize_cloud_language(language):
    if language is None:
        return None
    # The UI already sends the canonical short code for the normal path.
    # Avoid str/strip/lower allocations while preserving normalization for
    # direct callers and values such as "AUTO".
    if isinstance(language, str) and language in _MULTIPART_PREFIXES:
        return language
    normalized = str(language).strip().lower()
    return None if not normalized or normalized == "auto" else normalized


def _shutdown_requested(value):
    return value() if callable(value) else bool(value)


def _normalize_recording_duration(value):
    # ``engine.transcribe`` supplies a finite non-negative float. Returning it
    # unchanged avoids a redundant float conversion on every cloud request.
    if type(value) is float:
        return value if math.isfinite(value) and value >= 0.0 else 0.0
    if type(value) is int:
        return float(value) if value >= 0 else 0.0
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return 0.0
    return duration if math.isfinite(duration) and duration >= 0.0 else 0.0


def _active_sample_mask(recording, threshold, output=None):
    """Mark positive or negative samples without allocating abs(recording)."""
    active = output if output is not None else np.empty(recording.shape, dtype=np.bool_)
    active = active[: recording.size]
    np.greater_equal(recording, threshold, out=active)
    active |= recording <= -threshold
    return active


def trim_cloud_silence(recording):
    """Remove only leading/trailing near-silence before a cloud upload."""
    if recording.size == 0:
        return recording

    threshold = CLOUD_SILENCE_THRESHOLD
    if abs(recording[0]) >= threshold and abs(recording[-1]) >= threshold:
        return recording

    if recording.size <= _CLOUD_TRIM_MASK_LIMIT:
        # NumPy's vectorized abs+compare is faster for the common short clip;
        # the allocation-free comparator below is reserved for long scans.
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

        scan_mask = np.empty(_CLOUD_TRIM_SCAN_CHUNK, dtype=np.bool_)
        first_active = None
        for chunk_start in range(0, recording.size, _CLOUD_TRIM_SCAN_CHUNK):
            chunk = recording[chunk_start : chunk_start + _CLOUD_TRIM_SCAN_CHUNK]
            active = _active_sample_mask(chunk, threshold, scan_mask)
            if active.any():
                first_active = chunk_start + int(active.argmax())
                break
        if first_active is None:
            return recording[:0]

        for chunk_end in range(recording.size, first_active, -_CLOUD_TRIM_SCAN_CHUNK):
            chunk_start = max(first_active, chunk_end - _CLOUD_TRIM_SCAN_CHUNK)
            chunk = recording[chunk_start:chunk_end]
            active = _active_sample_mask(chunk, threshold, scan_mask)
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
    recording_duration = _normalize_recording_duration(recording_duration)
    if _shutdown_requested(shutting_down):
        return

    if not groq_api_key:
        log_func({"status": "error", "message": "Groq API key non configurata. Inseriscila nella tab Sistema."})
        log_func({"status": "ready", "message": "Motore Whisper pronto."})
        return

    client = None
    response = None
    try:
        cloud_recording = trim_cloud_silence(_prepare_cloud_recording(recording))
        if _shutdown_requested(shutting_down):
            return
        if cloud_recording.size == 0:
            log_func({"status": "ready", "message": "Nessun audio riconosciuto."})
            return

        cloud_language = _normalize_cloud_language(language)
        buffer = encode_cloud_multipart_from_recording(
            cloud_recording,
            cloud_language,
            assume_normalized=True,
        )

        client = acquire_groq_client(groq_api_key)

        request = httpx.Request(
            "POST",
            _GROQ_TRANSCRIPTION_URL,
            headers=client.headers,
            content=buffer,
        )
        if _shutdown_requested(shutting_down):
            return
        response = client.send(request, stream=False)
        if response.status_code != 200:
            response.raise_for_status()

        # Groq returns UTF-8 text; decoding the already-buffered body avoids
        # HTTPX charset detection on the success path.
        text = response.content.decode("utf-8", errors="replace").strip()

        if _TRAF_DEBUG:
            import sys as _sys
            _sys.stderr.write(f"[PY-DEBUG] transcribe_cloud result len={len(text)} duration={recording_duration}\n")
            _sys.stderr.flush()
        if _shutdown_requested(shutting_down):
            return
        log_func({"status": "result", "text": text, "duration": recording_duration})
        if models_dir and recording_duration > 0:
            _USAGE_EXECUTOR.submit(
                record_groq_usage,
                models_dir,
                duration_seconds=recording_duration,
            )

    except ImportError:
        log_func({"status": "error", "message": "Libreria 'groq' non installata. Esegui: pip install groq"})
        log_func({"status": "ready", "message": "Motore Whisper pronto."})
    except httpx.TimeoutException:
        log_func({"status": "error", "message": "Timeout nella richiesta Groq. Riprova tra poco."})
        log_func({"status": "ready", "message": "Motore Whisper pronto."})
    except Exception as e:
        err_msg = str(e)
        if groq_api_key:
            err_msg = err_msg.replace(str(groq_api_key), "[redacted]")
        if len(err_msg) > _CLOUD_ERROR_MESSAGE_LIMIT:
            err_msg = err_msg[: _CLOUD_ERROR_MESSAGE_LIMIT - 1] + "…"
        if _is_rate_limit_error(e, response):
            log_func({"status": "rate_limit", "message": "Limite API Groq raggiunto. Riprova tra qualche minuto o passa al modello locale."})
        else:
            log_func({"status": "error", "message": f"Errore API Groq: {err_msg}"})
        log_func({"status": "ready", "message": "Motore Whisper pronto."})
    finally:
        if response is not None:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        if client is not None:
            release_groq_client(client)
