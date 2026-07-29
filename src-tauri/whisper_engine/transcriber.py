import io
import wave
import os
import re
import httpx
import numpy as np
import concurrent.futures

from whisper_engine.constants import SAMPLE_RATE, TRANSCRIPTION_TIMEOUT, GROQ_MODEL, GROQ_TEXT_MODEL, POST_PROCESSING_TIMEOUT
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


def apply_dictionary(text, entries):
    """Apply explicit replacements case-insensitively without touching substrings."""
    active_entries = [entry for entry in (entries or []) if str(entry.get("spoken", "")).strip()]
    active_entries.sort(key=lambda entry: len(str(entry["spoken"])), reverse=True)
    for entry in active_entries:
        spoken = str(entry["spoken"]).strip()
        replacement = str(entry.get("replacement", ""))
        pattern = re.compile(r"(?<!\w)" + re.escape(spoken) + r"(?!\w)", re.IGNORECASE)
        text = pattern.sub(lambda _match, value=replacement: value, text)
    return text


def improve_cloud_text(text, groq_api_key, post_processing, log_func):
    """Best-effort cloud cleanup. A failure deliberately returns the original text."""
    entries = post_processing.get("dictionary_entries", [])
    cleanup_enabled = bool(post_processing.get("enabled"))
    has_dictionary = any(item.get("replacement") for item in entries)
    if not cleanup_enabled and not has_dictionary:
        return text
    try:
        from groq import Groq
        dictionary_lines = []
        for item in entries:
            if not item.get("replacement"):
                continue
            spoken = str(item.get("spoken", "")).strip()
            replacement = str(item.get("replacement", "")).strip()
            if spoken and spoken.casefold() != replacement.casefold():
                dictionary_lines.append(f'- Se senti "{spoken}", scrivi "{replacement}"')
            else:
                dictionary_lines.append(
                    f'- Termine canonico: "{replacement}". Riconosci automaticamente '
                    "varianti fonetiche o errori plausibili."
                )
        dictionary = "\n".join(dictionary_lines) or "(nessuna)"
        cleanup_rule = (
            "Correggi ortografia, punteggiatura, maiuscole e numeri."
            if cleanup_enabled
            else "Correggi esclusivamente i termini riconducibili al dizionario; non modificare altro."
        )
        filler_rule = (
            "Rimuovi esitazioni e filler (es. ehm, cioè) solo quando non alterano il significato."
            if cleanup_enabled and post_processing.get("remove_fillers", True)
            else "Non rimuovere filler."
        )
        prompt = f"""Correggi questa dettatura in italiano. Restituisci soltanto il testo finale.
Non aggiungere contenuto, non riassumere, non cambiare tono o lingua. {cleanup_rule} {filler_rule}
Il dizionario utente da rispettare e' (le regole esplicite hanno priorita'):\n{dictionary}\n\nTesto:\n{text}"""
        with httpx.Client(timeout=POST_PROCESSING_TIMEOUT) as http_client:
            client = Groq(api_key=groq_api_key, http_client=http_client)
            result = client.chat.completions.create(
                model=GROQ_TEXT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_completion_tokens=min(max(len(text.split()) * 3 + 32, 64), 512),
            )
        cleaned = (result.choices[0].message.content or "").strip()
        if not cleaned:
            return apply_dictionary(text, entries)
        usage = getattr(result, "usage", None)
        log_func({"status": "post_processed", "input_tokens": getattr(usage, "prompt_tokens", 0), "output_tokens": getattr(usage, "completion_tokens", 0)})
        return apply_dictionary(cleaned, entries)
    except Exception as exc:
        log_func({"status": "warning", "message": f"Miglioramento testo non disponibile: {exc}"})
        return apply_dictionary(text, entries)


PROMPT_ENGINEER_INSTRUCTION = (
    "Lavora come prompt engineer specializzato nello sviluppo software. Trasforma la "
    "richiesta dettata in un prompt tecnico, completo e immediatamente "
    "utilizzabile per un task di sviluppo software. Rendi espliciti, solo quando pertinenti: "
    "obiettivo di implementazione o debug, comportamento attuale e atteso, contesto del "
    "codebase, file o componenti coinvolti, stack e vincoli, casi limite, criteri di "
    "accettazione e verifiche o test da eseguire. Mantieni la lingua e l'intenzione "
    "dell'utente, conserva tutti i dettagli tecnici utili ed elimina ambiguità e ripetizioni. "
    "Non inventare file, API, dipendenze, requisiti o risultati. Se manca un'informazione "
    "bloccante, inserisci una breve sezione 'Da chiarire' con domande concrete. Non citare "
    "agenti, chatbot, modelli o ruoli generici."
)


def enhance_prompt(text, groq_api_key, log_func, request_id=""):
    """Turn dictated text into one automatically engineered prompt."""
    try:
        from groq import Groq
        prompt = f"""{PROMPT_ENGINEER_INSTRUCTION}
Rispondi soltanto con il prompt finale, senza introduzioni, commenti o delimitatori.

Richiesta dettata:
{text}"""
        with httpx.Client(timeout=POST_PROCESSING_TIMEOUT) as http_client:
            client = Groq(api_key=groq_api_key, http_client=http_client)
            result = client.chat.completions.create(
                model=GROQ_TEXT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.15,
                max_completion_tokens=min(max(len(text.split()) * 5 + 100, 180), 900),
            )
        output = (result.choices[0].message.content or "").strip()
        if not output:
            raise RuntimeError("Il modello non ha restituito alcun testo")
        log_func({
            "status": "transformed",
            "text": output,
            "request_id": request_id,
        })
    except Exception as exc:
        log_func({
            "status": "transform_error",
            "message": f"Trasformazione non disponibile: {exc}",
            "request_id": request_id,
        })


def transcribe_cloud(recording, language, recording_duration, groq_api_key, shutting_down, log_func, models_dir, post_processing=None):
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
        text = improve_cloud_text(text.strip(), groq_api_key, post_processing or {}, log_func)

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
