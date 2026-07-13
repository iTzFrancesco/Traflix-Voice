import io
import wave
import os
import httpx
import numpy as np
import concurrent.futures

from whisper_engine.constants import SAMPLE_RATE, TRANSCRIPTION_TIMEOUT, GROQ_MODEL
from whisper_engine.groq_tracker import record_groq_usage

_TRAF_DEBUG = os.environ.get("TRAF_DEBUG") == "1"


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
        from groq import Groq

        audio_int16 = (np.clip(recording, -1.0, 1.0) * 32767).astype(np.int16)

        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio_int16.tobytes())
        buffer.seek(0)

        client = Groq(
            api_key=groq_api_key,
            http_client=httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0, read=25.0)),
        )
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
