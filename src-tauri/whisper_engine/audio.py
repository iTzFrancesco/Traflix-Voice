import numpy as np

from whisper_engine.constants import (
    SAMPLE_RATE,
    VOLUME_DB_SCALE,
    VOLUME_FLOOR_DB,
)

VOLUME_UPDATE_SAMPLES = max(1, SAMPLE_RATE // 20)


def calculate_volume(indata):
    """Return a perceptual 0-100 level for one microphone block.

    RMS represents the sustained speech energy while a small peak contribution
    keeps consonants and word onsets visible. The dB mapping avoids the old
    block-size-dependent norm calculation and exposes quiet speech earlier.
    """
    samples = np.asarray(indata, dtype=np.float32)
    if samples.size == 0:
        return 0

    # The callback already queued an independent copy. Reuse the sounddevice
    # buffer for sanitizing invalid samples instead of allocating another
    # block on every volume update.
    samples = np.nan_to_num(
        samples, nan=0.0, posinf=0.0, neginf=0.0, copy=False
    )
    # The dot product computes RMS without materializing a squared copy. The
    # queued cloud capture is a contiguous mono vector, so ravel() is a view
    # on the hot path and NumPy can use its optimized reduction.
    flat = samples.reshape(-1)
    peak = float(np.max(np.abs(flat)))
    rms = float(np.sqrt(np.dot(flat, flat) / samples.size))
    effective_level = max(rms, peak * 0.08)
    level_db = 20.0 * np.log10(max(effective_level, 1e-6))
    normalized = (level_db - VOLUME_FLOOR_DB) * VOLUME_DB_SCALE
    return int(np.clip(normalized, 0.0, 100.0))


def audio_callback(indata, frames, time, status, audio_queue, is_recording, log_func):
    if status:
        log_func({"status": "warning", "message": str(status)})
    if not is_recording:
        audio_callback._volume_sample_count = 0
        return

    # InputStream is mono. Queue only the channel itself so the stop path can
    # concatenate a flat recording without creating a second view later.
    mono = indata[:, 0] if indata.ndim > 1 else indata
    queued = mono.copy()
    audio_queue.put(queued)

    audio_callback._volume_sample_count += max(0, int(frames or 0))
    if audio_callback._volume_sample_count < VOLUME_UPDATE_SAMPLES:
        return
    audio_callback._volume_sample_count -= VOLUME_UPDATE_SAMPLES
    # Reuse the queued mono copy: it is contiguous, already independent from
    # PortAudio's callback buffer, and avoids scanning the 2-D input view.
    level = calculate_volume(queued)
    if level == getattr(audio_callback, "_last_volume", None):
        return
    audio_callback._last_volume = level
    log_func({"status": "volume", "value": level})


audio_callback._volume_sample_count = VOLUME_UPDATE_SAMPLES
audio_callback._last_volume = None


def reset_volume_state():
    """Reset the meter at the start of a new recording session."""
    audio_callback._volume_sample_count = VOLUME_UPDATE_SAMPLES
    audio_callback._last_volume = None
