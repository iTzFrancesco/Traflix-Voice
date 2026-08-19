import os
import json
import tempfile
import threading
import time as pytime


_USAGE_CACHE = {}
_USAGE_CACHE_LOCK = threading.Lock()
_USAGE_READY_DIRS = set()


def get_groq_usage_path(models_dir):
    if not models_dir:
        return None
    return os.path.join(os.path.dirname(models_dir), "groq_usage.json")


def _empty_usage(date, hour_bucket):
    return {
        "date": date,
        "audio_seconds": 0.0,
        "audio_seconds_hourly": 0.0,
        "hourly_reset": "",
        "_hour_bucket": hour_bucket,
        "llmInputTokens": 0,
        "llmOutputTokens": 0,
        "llmInputTokensHourly": 0,
        "llmOutputTokensHourly": 0,
    }


def _load_saved_usage(usage_path, today, hour_bucket):
    usage = _empty_usage(today, hour_bucket)
    if not os.path.exists(usage_path):
        return usage

    try:
        with open(usage_path, "r") as f:
            saved = json.load(f)
        if isinstance(saved, dict) and saved.get("date") == today:
            usage = saved
    except Exception:
        pass
    return usage


def record_groq_usage(models_dir, duration_seconds=0, input_tokens=0, output_tokens=0):
    if (
        not models_dir
        or not (duration_seconds > 0 or input_tokens > 0 or output_tokens > 0)
    ):
        return
    tmp_path = None
    try:
        now = pytime.time()
        today = pytime.strftime("%Y-%m-%d", pytime.localtime(now))
        hour_bucket = int(now // 3600)
        usage_path = get_groq_usage_path(models_dir)

        # The transcription result is already serialized through the usage
        # executor. Keep a process-local snapshot so every cloud result does
        # not reread and reparse the same tiny JSON file.
        with _USAGE_CACHE_LOCK:
            cached = _USAGE_CACHE.get(usage_path)
            usage = (
                dict(cached)
                if cached is not None
                else _load_saved_usage(usage_path, today, hour_bucket)
            )

            if usage.get("date") != today:
                usage = _empty_usage(today, hour_bucket)
            elif usage.get("_hour_bucket") != hour_bucket:
                # The sidecar can stay alive across hour boundaries. Reset the
                # hourly meter from persisted metadata instead of accumulating it
                # until the next process restart.
                usage["audio_seconds_hourly"] = 0.0
                usage["llmInputTokensHourly"] = 0
                usage["llmOutputTokensHourly"] = 0
                usage["_hour_bucket"] = hour_bucket

            if duration_seconds > 0:
                usage["audio_seconds"] = round(usage.get("audio_seconds", 0) + duration_seconds, 1)
                usage["audio_seconds_hourly"] = round(usage.get("audio_seconds_hourly", 0) + duration_seconds, 1)

            if input_tokens > 0 or output_tokens > 0:
                usage["llmInputTokens"] = usage.get("llmInputTokens", 0) + input_tokens
                usage["llmOutputTokens"] = usage.get("llmOutputTokens", 0) + output_tokens
                usage["llmInputTokensHourly"] = usage.get("llmInputTokensHourly", 0) + input_tokens
                usage["llmOutputTokensHourly"] = usage.get("llmOutputTokensHourly", 0) + output_tokens

            next_hour = (now // 3600 + 1) * 3600
            usage["hourly_reset"] = pytime.strftime("%H:%M", pytime.localtime(next_hour))

            # Atomic write: temp file + rename. Directory creation is needed
            # only for the first write of a sidecar process.
            dir_path = os.path.dirname(usage_path)
            if dir_path and dir_path not in _USAGE_READY_DIRS:
                os.makedirs(dir_path, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=dir_path or None,
                mode="w",
                suffix=".tmp",
                delete=False,
            ) as f:
                json.dump(usage, f, separators=(",", ":"))
                tmp_path = f.name
            os.replace(tmp_path, usage_path)
            _USAGE_CACHE[usage_path] = usage
            if dir_path:
                _USAGE_READY_DIRS.add(dir_path)
    except Exception:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
