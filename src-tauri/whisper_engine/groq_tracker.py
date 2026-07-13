import os
import json
import tempfile
import time as pytime


def get_groq_usage_path(models_dir):
    if not models_dir:
        return None
    return os.path.join(os.path.dirname(models_dir), "groq_usage.json")


def record_groq_usage(models_dir, duration_seconds=0, input_tokens=0, output_tokens=0):
    if not models_dir:
        return
    try:
        now = pytime.time()
        today = pytime.strftime("%Y-%m-%d", pytime.localtime(now))

        usage = {"date": today, "audio_seconds": 0.0, "audio_seconds_hourly": 0.0, "hourly_reset": "",
                 "llmInputTokens": 0, "llmOutputTokens": 0,
                 "llmInputTokensHourly": 0, "llmOutputTokensHourly": 0}
        usage_path = get_groq_usage_path(models_dir)
        if os.path.exists(usage_path):
            try:
                with open(usage_path, "r") as f:
                    saved = json.load(f)
                    if saved.get("date") == today:
                        usage = saved
            except Exception:
                pass

        if usage.get("date") != today:
            usage = {"date": today, "audio_seconds": 0.0, "audio_seconds_hourly": 0.0, "hourly_reset": "",
                     "llmInputTokens": 0, "llmOutputTokens": 0,
                     "llmInputTokensHourly": 0, "llmOutputTokensHourly": 0}

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

        # Atomic write: temp file + rename
        dir_path = os.path.dirname(usage_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=dir_path, mode='w', suffix='.tmp', delete=False) as f:
            json.dump(usage, f)
            tmp_path = f.name
        os.replace(tmp_path, usage_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
