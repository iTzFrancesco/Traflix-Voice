import sys
import json
import threading

from whisper_engine.constants import GROQ_MODEL


_FAST_STATUS_LINES = {
    ("listening", "In ascolto... parla ora."): '{"status":"listening","message":"In ascolto... parla ora."}\n',
    ("processing", "Trascrizione in corso..."): '{"status":"processing","message":"Trascrizione in corso..."}\n',
}


def log(data):
    # Volume events are the hottest IPC message and contain only a bounded
    # integer. Avoiding a full JSON encoder call keeps the audio callback
    # lightweight; every other event retains the generic serializer.
    value = data.get("value")
    if data.get("status") == "volume" and type(value) is int:
        line = '{"status":"volume","value":' + str(value) + "}\n"
    elif data.get("status") == "result":
        # Result text dominates the payload and compact encoding is slower for
        # this lower-frequency path on short responses; retain the established
        # serializer here and optimize status events below.
        line = json.dumps(data) + "\n"
    else:
        line = _FAST_STATUS_LINES.get((data.get("status"), data.get("message")))
        if line is not None:
            sys.stdout.write(line)
            sys.stdout.flush()
            return
        # Sidecar events are line-delimited machine JSON. Compact separators
        # reduce stdout bytes and WebView parsing work for status events.
        line = json.dumps(data, separators=(",", ":")) + "\n"
    sys.stdout.write(line)
    sys.stdout.flush()


def handle_command(cmd, data, engine):
    if cmd == "init":
        engine.models_dir = data.get("models_dir")
        engine.groq_api_key = data.get("groq_api_key")
        engine.provider = data.get("provider", "local")
        preload_model = data.get("model", "small")
        engine.log({"status": "info", "message": f"Cartella modelli: {engine.models_dir}, provider: {engine.provider}"})
        if engine.provider == "local":
            threading.Thread(target=engine._preload_default_model, args=(preload_model,), daemon=True).start()
        else:
            threading.Thread(
                target=engine.prepare_groq_client,
                args=(engine.groq_api_key,),
                daemon=True,
            ).start()
            engine.log({"status": "ready", "message": f"Pronto (cloud: {GROQ_MODEL})."})
    elif cmd == "download":
        threading.Thread(target=engine.download_model, args=(data.get("model"),), daemon=True).start()
    elif cmd == "get_status":
        if engine.provider == "cloud":
            engine.log({"status": "ready", "message": "Pronto (cloud)."})
        elif engine._loading_in_progress:
            engine.log({"status": "loading_model", "message": "Caricamento modello in corso..."})
        elif engine.model is not None:
            engine.log({"status": "ready", "message": "Modello già caricato."})
        else:
            engine.log({"status": "starting", "message": "Motore in fase di avvio..."})
    elif cmd == "set_provider":
        new_provider = data.get("provider", "local")
        old_provider = engine.provider
        engine.provider = new_provider
        if new_provider == "cloud" and old_provider == "local":
            engine.unload_model()
            threading.Thread(
                target=engine.prepare_groq_client,
                args=(engine.groq_api_key,),
                daemon=True,
            ).start()
        elif new_provider == "local":
            preload_model = data.get("model", "small")
            threading.Thread(target=engine._preload_default_model, args=(preload_model,), daemon=True).start()
    elif cmd == "transcribe":
        engine.provider = data.get("provider", "local")
        engine.start_transcription(
            data.get("device"),
            data.get("model", "small"),
            data.get("language", "it"),
        )
    elif cmd == "stop":
        engine.stop_recording()
    elif cmd == "set_device":
        engine.compute_device = data.get("device", "cpu")
        engine.log({"status": "info", "message": f"Dispositivo di calcolo impostato a: {engine.compute_device}"})
    elif cmd == "set_groq_api_key":
        engine.groq_api_key = data.get("api_key") or None
        if engine.provider == "cloud":
            threading.Thread(
                target=engine.prepare_groq_client,
                args=(engine.groq_api_key,),
                daemon=True,
            ).start()
    elif cmd == "quit":
        engine._shutting_down = True
        engine.stop_recording()
        engine.close_groq_client()
        return True
    return False
