import numpy as np
import time as pytime


def audio_callback(indata, frames, time, status, audio_queue, is_recording, log_func):
    if status:
        log_func({"status": "warning", "message": str(status)})
    audio_queue.put(indata.copy())
    if is_recording:
        volume_norm = np.linalg.norm(indata) * 10
        level = min(100, int(volume_norm))
        current_time = pytime.time()
        if current_time - audio_callback._last_vol_time > 0.05:
            log_func({"status": "volume", "value": level})
            audio_callback._last_vol_time = current_time


audio_callback._last_vol_time = 0
