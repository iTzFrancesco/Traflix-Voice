import io
import math
import os
import struct
import threading
import time
import httpx
import numpy as np
import concurrent.futures

from whisper_engine.constants import (
    CLOUD_DEFAULT_PROMPT,
    CLOUD_EDGE_PAD_SECONDS,
    GROQ_MODEL,
    GROQ_MULTIPART_BOUNDARY,
    GROQ_TRANSCRIPTION_URL,
    CLOUD_SILENCE_PADDING_SECONDS,
    CLOUD_SILENCE_THRESHOLD,
    SAMPLE_RATE,
    TRANSCRIPTION_TIMEOUT,
)
from whisper_engine.groq_tracker import record_groq_usage
from whisper_engine import cloud_quality

_TRAF_DEBUG = os.environ.get("TRAF_DEBUG") == "1"
_GROQ_CLIENT = None
_GROQ_CLIENT_KEY = None
_GROQ_CLIENT_EPOCH = 0
_GROQ_CLIENT_LOCK = threading.Lock()
_GROQ_CLIENT_LEASES = {}
_GROQ_RETIRED_CLIENTS = {}
_GROQ_WARMUP_LOCK = threading.Lock()
_GROQ_WARMUPS = {}
_GROQ_CONNECTION_ACTIVITY = {}
_GROQ_WARMUP_LAST_ATTEMPT = None
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
_GROQ_MODELS_URL = _GROQ_TRANSCRIPTION_URL.copy_with(path="/openai/v1/models")
_GROQ_WARMUP_TIMEOUT = httpx.Timeout(2.0, connect=1.0, read=1.0, write=1.0, pool=0.05)
_GROQ_WARMUP_IDLE_SECONDS = 240.0
_GROQ_WARMUP_RETRY_SECONDS = 30.0
_CLOUD_ERROR_MESSAGE_LIMIT = 512
_CLOUD_SILENCE_PADDING_SAMPLES = int(SAMPLE_RATE * CLOUD_SILENCE_PADDING_SECONDS)
_EDGE_PAD_SAMPLES = int(SAMPLE_RATE * CLOUD_EDGE_PAD_SECONDS)
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
            # A slow models probe must leave one slot for the audio POST.
            max_connections=2,
            max_keepalive_connections=1,
            keepalive_expiry=300.0,
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
    with _GROQ_WARMUP_LOCK:
        _GROQ_CONNECTION_ACTIVITY.pop(id(client), None)
    close = getattr(client, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            # Cleanup must not mask the actual cloud result or shutdown path.
            pass


def _get_or_create_groq_client(groq_api_key, lease=False, expected_epoch=None):
    """Select a client atomically and optionally hold it for one request."""
    global _GROQ_CLIENT, _GROQ_CLIENT_KEY, _GROQ_CLIENT_EPOCH

    with _GROQ_CLIENT_LOCK:
        if expected_epoch is not None and expected_epoch != _GROQ_CLIENT_EPOCH:
            return None
        if _GROQ_CLIENT is not None and _GROQ_CLIENT_KEY == groq_api_key:
            client = _GROQ_CLIENT
            idle_client = None
        else:
            old_client = _GROQ_CLIENT
            client = create_groq_client(groq_api_key)
            if old_client is not None:
                _GROQ_CLIENT_EPOCH += 1
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


def record_groq_connection_activity(client):
    """Reuse a connection that has just completed a buffered HTTP response."""
    with _GROQ_WARMUP_LOCK:
        _GROQ_CONNECTION_ACTIVITY[id(client)] = time.monotonic()


def _warm_groq_connection(groq_api_key, shutting_down, expected_epoch):
    client = None
    response = None
    try:
        if _shutdown_requested(shutting_down):
            return
        client = _get_or_create_groq_client(
            groq_api_key, lease=True, expected_epoch=expected_epoch,
        )
        if client is None or _shutdown_requested(shutting_down):
            return
        with _GROQ_CLIENT_LOCK:
            if _GROQ_CLIENT is not client:
                return
        request = httpx.Request(
            "GET",
            _GROQ_MODELS_URL,
            headers={"Authorization": client.headers["Authorization"]},
            extensions={"timeout": _GROQ_WARMUP_TIMEOUT.as_dict()},
        )
        response = client.send(request, stream=False)
        if response.status_code == 200:
            record_groq_connection_activity(client)
    except Exception:
        # A connection probe must never interrupt dictation or expose credentials.
        pass
    finally:
        if response is not None:
            _close_client(response)
        if client is not None:
            release_groq_client(client)
        with _GROQ_WARMUP_LOCK:
            if _GROQ_WARMUPS.get(groq_api_key) is threading.current_thread():
                _GROQ_WARMUPS.pop(groq_api_key, None)


def prewarm_groq_connection(groq_api_key, shutting_down=False):
    """Probe the shared connection asynchronously, once per in-flight key."""
    global _GROQ_WARMUP_LAST_ATTEMPT
    if not groq_api_key or _shutdown_requested(shutting_down):
        return None
    with _GROQ_WARMUP_LOCK:
        now = time.monotonic()
        if _GROQ_CLIENT is not None and _GROQ_CLIENT_KEY == groq_api_key:
            last_activity = _GROQ_CONNECTION_ACTIVITY.get(id(_GROQ_CLIENT), -math.inf)
            if now - last_activity < _GROQ_WARMUP_IDLE_SECONDS:
                return None
        worker = _GROQ_WARMUPS.get(groq_api_key)
        if worker is not None:
            return worker
        if _GROQ_WARMUP_LAST_ATTEMPT is not None:
            last_key, attempted_at = _GROQ_WARMUP_LAST_ATTEMPT
            if last_key == groq_api_key and now - attempted_at < _GROQ_WARMUP_RETRY_SECONDS:
                return None
        worker = threading.Thread(
            target=_warm_groq_connection,
            args=(groq_api_key, shutting_down, _GROQ_CLIENT_EPOCH),
            daemon=True,
            name="groq-warmup",
        )
        _GROQ_WARMUPS[groq_api_key] = worker
        _GROQ_WARMUP_LAST_ATTEMPT = (groq_api_key, now)
        try:
            worker.start()
        except Exception:
            _GROQ_WARMUPS.pop(groq_api_key, None)
            return None
        return worker


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
    global _GROQ_CLIENT, _GROQ_CLIENT_KEY, _GROQ_CLIENT_EPOCH, _GROQ_WARMUP_LAST_ATTEMPT

    idle_clients = []
    with _GROQ_CLIENT_LOCK:
        _GROQ_CLIENT_EPOCH += 1
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
    with _GROQ_WARMUP_LOCK:
        _GROQ_WARMUP_LAST_ATTEMPT = None


def _encode_pcm16(recording, assume_normalized=False):
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
    return audio_int16


def _encode_wav_header(data_size):
    return _WAV_HEADER.pack(
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


def _encode_wav_payload(recording, assume_normalized=False):
    """Return the complete PCM WAV bytes for a mono recording."""
    pcm = _encode_pcm16(recording, assume_normalized)
    return b"".join((_encode_wav_header(pcm.nbytes), memoryview(pcm)))


def encode_wav(recording, assume_normalized=False):
    """Encode mono float32 samples as the PCM WAV payload Groq accepts."""
    return io.BytesIO(_encode_wav_payload(recording, assume_normalized))


def _ensure_default_prompt(vocabulary):
    """Anchor the product name in the decoder prompt when it is missing.

    The user vocabulary is empty by default, leaving Whisper without a hint
    for proper nouns ("Traflix" -> "traflixs"/"traflix ss"). Prepending the
    product name keeps the spelling stable; user entries are preserved after
    it within the same byte cap used for the prompt field.
    """
    if CLOUD_DEFAULT_PROMPT.casefold() in vocabulary.casefold():
        return vocabulary
    combined = f"{CLOUD_DEFAULT_PROMPT}, {vocabulary}" if vocabulary else CLOUD_DEFAULT_PROMPT
    return combined.encode("utf-8")[:224].decode("utf-8", errors="ignore").strip().rstrip(",")


def pad_abrupt_clip_edges(recording):
    """Add short digital silence only when speech touches the clip edge.

    Trimming keeps 0.32 s of natural padding, but a dictation that starts or
    ends mid-word has no silence to keep: the decoder then sees an abrupt
    onset and drops the first syllable. Padding just those edges gives the
    recognizer onset context without changing clean clips. The reported
    recording duration stays untouched; only this buffer grows.
    """
    if recording.size == 0 or _EDGE_PAD_SAMPLES <= 0:
        return recording
    threshold = CLOUD_SILENCE_THRESHOLD
    leading = abs(float(recording[0])) >= threshold
    trailing = abs(float(recording[-1])) >= threshold
    if not leading and not trailing:
        return recording
    pad = np.zeros(_EDGE_PAD_SAMPLES, dtype=np.float32)
    parts = [pad] if leading else []
    parts.append(recording)
    if trailing:
        parts.append(pad)
    return np.concatenate(parts)


def _cloud_multipart_prefix(language, detailed=False, vocabulary=""):
    prefix = _MULTIPART_PREFIXES.get(language)
    if prefix is None:
        prefix = _MULTIPART_BASE_PREFIX
        if language:
            prefix += _LANGUAGE_FIELD_PREFIX + language.encode("utf-8") + b"\r\n"
        prefix += _FILE_FIELD_PREFIX
    vocabulary = _ensure_default_prompt(cloud_quality.normalize_vocabulary(vocabulary))
    if detailed:
        prefix = prefix.replace(_RESPONSE_FORMAT_FIELD, _RESPONSE_FORMAT_FIELD.replace(
            b"\r\n\r\ntext\r\n", b"\r\n\r\nverbose_json\r\n"), 1)
    if vocabulary:
        prompt_field = (
            b"--" + _MULTIPART_BOUNDARY + b"\r\n"
            b'Content-Disposition: form-data; name="prompt"\r\n\r\n'
            + vocabulary.encode("utf-8") + b"\r\n"
        )
        prefix = prefix.replace(_FILE_FIELD_PREFIX, prompt_field + _FILE_FIELD_PREFIX, 1)
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
    *,
    detailed=False,
    vocabulary="",
):
    """Join PCM and framing once, without materializing a separate WAV blob."""
    pcm = _encode_pcm16(recording, assume_normalized)
    return b"".join(
        (_cloud_multipart_prefix(language, detailed, vocabulary), _encode_wav_header(pcm.nbytes),
         memoryview(pcm), _MULTIPART_SUFFIX)
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


def _prepare_local_recording(recording):
    """Contiguous float32 mono input for local inference.

    Slice views from silence trimming are already contiguous, so this is
    normally zero-copy; it only guards direct callers."""
    return np.ascontiguousarray(recording, dtype=np.float32).reshape(-1)


def trim_cloud_silence(recording):
    """Remove only edge samples below PCM16 resolution, retaining word edges."""
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
        first_active = None
        scan_mask = None
        first_chunk = recording[:_CLOUD_TRIM_SCAN_CHUNK]
        if first_chunk.any():
            scan_mask = np.empty(_CLOUD_TRIM_SCAN_CHUNK, dtype=np.bool_)
            active = _active_sample_mask(first_chunk, threshold, scan_mask)
            if active.any():
                # A normal onset proves this is not silence. Do not scan the
                # entire interior before finding its trailing edge.
                first_active = int(active.argmax())
        if first_active is None:
            # Keep cheap full-silence detection for long idle recordings.
            if recording.max() < threshold and recording.min() > -threshold:
                return recording[:0]
            if scan_mask is None:
                scan_mask = np.empty(_CLOUD_TRIM_SCAN_CHUNK, dtype=np.bool_)
            for chunk_start in range(_CLOUD_TRIM_SCAN_CHUNK, recording.size, _CLOUD_TRIM_SCAN_CHUNK):
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

    # Use the same conservative edge trim as cloud. Quiet speech must reach
    # the recognizer rather than being classified as silence by its volume.
    trimmed = trim_cloud_silence(_prepare_local_recording(recording))
    if trimmed.size == 0:
        # Pure silence: skip seconds of inference (R20) and keep the local
        # contract of always ending with a result event. The frontend guards
        # empty text (no paste, UI back to ready).
        log_func({"status": "result", "text": "", "duration": recording_duration})
        return
    # A dictation that starts/ends mid-word has no natural edge silence;
    # give the transducer the same onset context the cloud path receives.
    trimmed = pad_abrupt_clip_edges(trimmed)

    lang_param = "" if language == "auto" else language

    def _run_inference():
        segments = model.transcribe(trimmed, language=lang_param)
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


def transcribe_cloud(
    recording,
    language,
    recording_duration,
    groq_api_key,
    shutting_down,
    log_func,
    models_dir,
    *,
    correct_uncertain=False,
    vocabulary="",
    speech_filter=False,
    speech_detector=None,
):
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
        # Pad only abrupt edges (see pad_abrupt_clip_edges). The usage
        # duration reported to the UI keeps the original recording length.
        cloud_recording = pad_abrupt_clip_edges(cloud_recording)

        speech_present = speech_detector(cloud_recording) if speech_filter and speech_detector else None
        if _shutdown_requested(shutting_down):
            return
        if speech_present is False:
            log_func({"status": "ready", "message": "Nessuna voce rilevata."})
            return
        cloud_language = _normalize_cloud_language(language)
        buffer = encode_cloud_multipart_from_recording(
            cloud_recording,
            cloud_language,
            assume_normalized=True,
            detailed=correct_uncertain or speech_filter,
            vocabulary=vocabulary,
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
        record_groq_connection_activity(client)
        if response.status_code != 200:
            response.raise_for_status()

        transcript = cloud_quality.parse_cloud_transcript(
            response.content, correct_uncertain or speech_filter, recording_duration)
        if speech_present is True and transcript.no_speech:
            transcript = cloud_quality.CloudTranscript(transcript.text, transcript.uncertain)
        correction = (
            cloud_quality.correct_cloud_transcript(
                client, transcript, cloud_language, lambda: _shutdown_requested(shutting_down))
            if correct_uncertain else cloud_quality.CorrectionResult(
                "" if speech_filter and transcript.no_speech else transcript.text)
        )
        text = correction.text

        if _TRAF_DEBUG:
            import sys as _sys
            _sys.stderr.write(f"[PY-DEBUG] transcribe_cloud result len={len(text)} duration={recording_duration}\n")
            _sys.stderr.flush()
        if _shutdown_requested(shutting_down):
            return
        if text:
            log_func({"status": "result", "text": text, "duration": recording_duration})
        else:
            log_func({"status": "ready", "message": "Nessuna voce rilevata."})
        if models_dir and recording_duration > 0:
            _USAGE_EXECUTOR.submit(
                record_groq_usage,
                models_dir,
                duration_seconds=recording_duration,
                input_tokens=correction.input_tokens,
                output_tokens=correction.output_tokens,
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
