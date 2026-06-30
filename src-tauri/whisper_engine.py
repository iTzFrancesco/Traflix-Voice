import sys
import json
import io
import wave
import sounddevice as sd
import numpy as np
import os
import queue
import threading
import concurrent.futures
from pywhispercpp.model import Model
from huggingface_hub import hf_hub_download

SAMPLE_RATE = 16000
BLOCK_SIZE = 4000
TRANSCRIPTION_TIMEOUT = 60
GROQ_MODEL = "whisper-large-v3-turbo"

class WhisperEngine:
    def __init__(self):
        self.model = None
        self.current_model_size = None
        self.audio_queue = queue.Queue()
        self.is_recording = False
        self.models_dir = None
        self._model_lock = threading.Lock()
        self.current_device = "cpu"
        self.compute_device = "cpu"
        self.groq_api_key = None
        self.provider = "local"

    def verify_model(self, size):
        model_path = os.path.join(self.models_dir, f"ggml-{size}.bin")
        if not os.path.exists(model_path):
            return False, f"File non trovato: {model_path}"
        try:
            if os.path.getsize(model_path) == 0:
                return False, f"File vuoto: {model_path}"
        except OSError as e:
            return False, str(e)
        return True, "OK"

    def unload_model(self):
        with self._model_lock:
            if self.model is not None:
                self.model = None
                self.current_model_size = None
                self.log({"status": "info", "message": "Modello locale rimosso dalla memoria."})

    def load_model(self, size):
        with self._model_lock:
            if self.model is not None and self.current_model_size == size:
                return

            is_valid, msg = self.verify_model(size)
            if not is_valid:
                self.log({"status": "error", "message": f"Modello {size} non valido: {msg}"})
                raise Exception(f"Modello {size} non valido: {msg}")

            self.log({"status": "loading_model", "message": f"Caricamento modello {size}..."})
            model_path = os.path.join(self.models_dir, f"ggml-{size}.bin")
            try:
                self.model = Model(model_path, print_realtime=False, print_progress=False)
                self.current_model_size = size
                self.log({"status": "info", "message": f"Modello {size} caricato."})
            except Exception as e:
                self.log({"status": "error", "message": f"Errore caricamento modello: {str(e)}"})
                raise

    def _preload_default_model(self, model_size="small"):
        try:
            is_valid, _ = self.verify_model(model_size)
            if is_valid:
                self.log({"status": "loading_model", "message": f"Caricamento modello {model_size}..."})
                self.load_model(model_size)
                self.log({"status": "ready", "message": "Modello pronto."})
            else:
                self.log({"status": "ready", "message": "Pronto (nessun modello da precaricare)."})
        except Exception as e:
            self.log({"status": "ready", "message": f"Pronto (precaricamento saltato: {str(e)})"})

    def log(self, data):
        print(json.dumps(data))
        sys.stdout.flush()

    def _get_groq_usage_path(self):
        return os.path.join(os.path.dirname(self.models_dir), "groq_usage.json")

    def _record_groq_usage(self, duration_seconds):
        try:
            import time as pytime
            now = pytime.time()
            today = pytime.strftime("%Y-%m-%d", pytime.localtime(now))

            usage = {"date": today, "audio_seconds": 0.0, "audio_seconds_hourly": 0.0, "hourly_reset": ""}
            usage_path = self._get_groq_usage_path()
            if os.path.exists(usage_path):
                try:
                    with open(usage_path, "r") as f:
                        saved = json.load(f)
                        if saved.get("date") == today:
                            usage = saved
                except Exception:
                    pass

            if usage.get("date") != today:
                usage = {"date": today, "audio_seconds": 0.0, "audio_seconds_hourly": 0.0, "hourly_reset": ""}

            usage["audio_seconds"] = round(usage.get("audio_seconds", 0) + duration_seconds, 1)
            usage["audio_seconds_hourly"] = round(usage.get("audio_seconds_hourly", 0) + duration_seconds, 1)
            next_hour = (now // 3600 + 1) * 3600
            usage["hourly_reset"] = pytime.strftime("%H:%M", pytime.localtime(next_hour))

            with open(usage_path, "w") as f:
                json.dump(usage, f)
        except Exception:
            pass

    def download_model(self, size):
        local_path = os.path.join(self.models_dir, f"ggml-{size}.bin")

        try:
            self.log({"status": "downloading", "message": f"Download modello {size}...", "model": size})
            hf_hub_download(
                repo_id="ggerganov/whisper.cpp",
                filename=f"ggml-{size}.bin",
                local_dir=self.models_dir,
                local_dir_use_symlinks=False
            )

            is_valid, msg = self.verify_model(size)
            if not is_valid:
                self.log({"status": "error", "message": f"Verifica fallita: {msg}"})
                try:
                    if os.path.exists(local_path):
                        os.remove(local_path)
                except Exception:
                    pass
                return

            self.log({"status": "download_complete", "message": f"Modello {size} scaricato.", "model": size})
        except Exception as e:
            self.log({"status": "error", "message": f"Download fallito: {str(e)}"})
            try:
                if os.path.exists(local_path):
                    os.remove(local_path)
            except Exception:
                pass

    def audio_callback(self, indata, frames, time, status):
        if status:
            self.log({"status": "warning", "message": str(status)})
        self.audio_queue.put(indata.copy())
        if self.is_recording:
            volume_norm = np.linalg.norm(indata) * 10
            level = min(100, int(volume_norm))
            if not hasattr(self, '_last_vol_time'): self._last_vol_time = 0
            import time as pytime
            current_time = pytime.time()
            if current_time - self._last_vol_time > 0.05:
                self.log({"status": "volume", "value": level})
                self._last_vol_time = current_time

    def transcribe(self, device_id, model_size, language="it"):
        try:
            if self.provider == "local":
                self.load_model(model_size)

            self.is_recording = True
            self.audio_queue = queue.Queue()
            audio_data = []

            self.log({"status": "listening", "message": "In ascolto... parla ora."})

            import time as pytime
            start_time = pytime.time()

            with sd.InputStream(device=device_id, channels=1, callback=self.audio_callback,
                                samplerate=SAMPLE_RATE, blocksize=BLOCK_SIZE):
                while self.is_recording:
                    try:
                        data = self.audio_queue.get(timeout=0.1)
                        audio_data.append(data)
                    except queue.Empty:
                        continue

            recording_duration = pytime.time() - start_time

            self.log({"status": "processing", "message": "Trascrizione in corso..."})

            if not audio_data:
                self.log({"status": "ready", "message": "Nessun audio catturato."})
                return

            recording = np.concatenate(audio_data, axis=0).flatten().astype(np.float32)

            if self.provider == "cloud":
                self._transcribe_cloud(recording, language, recording_duration)
            else:
                self._transcribe_local(recording, model_size, language, recording_duration)

        except Exception as e:
            self.log({"status": "error", "message": str(e)})

    def _transcribe_local(self, recording, model_size, language, recording_duration):
        lang_param = "" if language == "auto" else language

        def _run_inference():
            segments = self.model.transcribe(recording, language=lang_param)
            text = " ".join(s.text for s in segments).strip()
            return text

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run_inference)
            try:
                text = future.result(timeout=TRANSCRIPTION_TIMEOUT)
            except concurrent.futures.TimeoutError:
                self.log({"status": "error", "message": f"Timeout dopo {TRANSCRIPTION_TIMEOUT}s"})
                self.log({"status": "ready", "message": "Motore Whisper pronto."})
                return

        self.log({"status": "result", "text": text, "duration": recording_duration})

    def _transcribe_cloud(self, recording, language, recording_duration):
        if not self.groq_api_key:
            self.log({"status": "error", "message": "Groq API key non configurata. Inseriscila nella tab Sistema."})
            self.log({"status": "ready", "message": "Motore Whisper pronto."})
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

            client = Groq(api_key=self.groq_api_key)
            lang_param = language if language != "auto" else None

            transcription = client.audio.transcriptions.create(
                model=GROQ_MODEL,
                file=("audio.wav", buffer, "audio/wav"),
                language=lang_param,
                response_format="text",
            )

            text = transcription if isinstance(transcription, str) else transcription.text
            self.log({"status": "result", "text": text.strip(), "duration": recording_duration})
            self._record_groq_usage(recording_duration)

        except ImportError:
            self.log({"status": "error", "message": "Libreria 'groq' non installata. Esegui: pip install groq"})
            self.log({"status": "ready", "message": "Motore Whisper pronto."})
        except Exception as e:
            err_msg = str(e)
            if "429" in err_msg or "rate" in err_msg.lower() or "limit" in err_msg.lower():
                self.log({"status": "rate_limit", "message": "Limite API Groq raggiunto. Riprova tra qualche minuto o passa al modello locale."})
            else:
                self.log({"status": "error", "message": f"Errore API Groq: {err_msg}"})
            self.log({"status": "ready", "message": "Motore Whisper pronto."})

    def run(self):
        self.log({"status": "starting", "message": "Avvio motore vocale..."})
        for line in sys.stdin:
            try:
                data = json.loads(line)
                cmd = data.get("command")

                if cmd == "init":
                    self.models_dir = data.get("models_dir")
                    self.groq_api_key = data.get("groq_api_key")
                    self.provider = data.get("provider", "local")
                    preload_model = data.get("model", "small")
                    self.log({"status": "info", "message": f"Cartella modelli: {self.models_dir}, provider: {self.provider}"})
                    if self.provider == "local":
                        threading.Thread(target=self._preload_default_model, args=(preload_model,), daemon=True).start()
                    else:
                        self.log({"status": "ready", "message": f"Pronto (cloud: {GROQ_MODEL})."})
                elif cmd == "download":
                    threading.Thread(target=self.download_model, args=(data.get("model"),)).start()
                elif cmd == "set_provider":
                    new_provider = data.get("provider", "local")
                    old_provider = self.provider
                    self.provider = new_provider
                    if new_provider == "cloud" and old_provider == "local":
                        self.unload_model()
                    elif new_provider == "local":
                        preload_model = data.get("model", "small")
                        threading.Thread(target=self._preload_default_model, args=(preload_model,), daemon=True).start()
                elif cmd == "transcribe":
                    self.provider = data.get("provider", "local")
                    threading.Thread(target=self.transcribe,
                                     args=(data.get("device"), data.get("model", "small"), data.get("language", "it"))).start()
                elif cmd == "stop":
                    self.is_recording = False
                elif cmd == "quit":
                    self.unload_model()
                    break
            except Exception as e:
                self.log({"status": "error", "message": str(e)})

if __name__ == "__main__":
    engine = WhisperEngine()
    engine.run()
