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

    samples = np.nan_to_num(samples, nan=0.0, posinf=0.0, neginf=0.0)
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
    audio_queue.put(indata.copy())
    if is_recording:
        level = calculate_volume(indata)
        current_time = pytime.time()
        if current_time - audio_callback._last_vol_time > 0.05:
            log_func({"status": "volume", "value": level})
            audio_callback._last_vol_time = current_time


audio_callback._last_vol_time = 0
