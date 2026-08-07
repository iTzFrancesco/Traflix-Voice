import numpy as np
import time as pytime

from whisper_engine.constants import VOLUME_CEILING_DB, VOLUME_FLOOR_DB


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
    rms = float(np.sqrt(np.mean(np.square(samples))))
    peak = float(np.max(np.abs(samples)))
    effective_level = max(rms, peak * 0.08)
    level_db = 20.0 * np.log10(max(effective_level, 1e-6))
    normalized = (level_db - VOLUME_FLOOR_DB) / (
        VOLUME_CEILING_DB - VOLUME_FLOOR_DB
    ) * 100.0
    return int(np.clip(normalized, 0.0, 100.0))


def audio_callback(indata, frames, time, status, audio_queue, is_recording, log_func):
    if status:
        log_func({"status": "warning", "message": str(status)})
    if not is_recording:
        return

    # InputStream is mono. Queue only the channel itself so the stop path can
    # concatenate a flat recording without creating a second view later.
    mono = indata[:, 0] if indata.ndim > 1 else indata
    audio_queue.put(mono.copy())

    current_time = pytime.monotonic()
    if current_time - audio_callback._last_vol_time <= 0.05:
        return
    level = calculate_volume(indata)
    log_func({"status": "volume", "value": level})
    audio_callback._last_vol_time = current_time


audio_callback._last_vol_time = 0
