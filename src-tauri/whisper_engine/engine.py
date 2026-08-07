import sys
import json
import queue
import threading
import numpy as np
import sounddevice as sd

from whisper_engine.constants import SAMPLE_RATE, BLOCK_SIZE
from whisper_engine import model as model_module
from whisper_engine import audio as audio_module
from whisper_engine import transcriber, ipc


class WhisperEngine:
    def __init__(self):
        self.model = None
        self.current_model_size = None
        self.audio_queue = queue.Queue()
        self.is_recording = False
        self.models_dir = None
        self._shutting_down = False
        self._model_lock = threading.Lock()
        self.current_device = "cpu"
        self.compute_device = "cpu"
        self.groq_api_key = None
        self.provider = "local"
        self._loading_in_progress = False

    def log(self, data):
        ipc.log(data)

    def verify_model(self, size):
        return model_module.verify_model(self.models_dir, size)

    def load_model(self, size):
        with self._model_lock:
            if self.model is not None and self.current_model_size == size:
                return

            self._loading_in_progress = True
            try:
                self.model = model_module.load_model(self.models_dir, size, self.log)
                self.current_model_size = size
                self._loading_in_progress = False
            except:
                self._loading_in_progress = False
                raise

    def unload_model(self):
        with self._model_lock:
            if self.model is not None:
                self.model = None
                self.current_model_size = None
                self.log({"status": "info", "message": "Modello locale rimosso dalla memoria."})

    def _preload_default_model(self, model_size="small"):
        loaded_model, size = model_module.preload_default_model(self.models_dir, model_size, self.log)
        if loaded_model is not None:
            with self._model_lock:
                self.model = loaded_model
                self.current_model_size = size

    def download_model(self, size):
        model_module.download_model(self.models_dir, size, self.log)

    def close_groq_client(self):
        transcriber.close_groq_client()

    def audio_callback(self, indata, frames, time, status):
        audio_module.audio_callback(indata, frames, time, status, self.audio_queue, self.is_recording, self.log)

    def _transcribe_cloud(self, recording, language, recording_duration):
        transcriber.transcribe_cloud(recording, language, recording_duration, self.groq_api_key,
                                     self._shutting_down, self.log, self.models_dir)

    def _transcribe_local(self, recording, model_size, language, recording_duration):
        with self._model_lock:
            model = self.model
            if model is None:
                self.log({"status": "error", "message": "Modello scaricato durante la trascrizione."})
                return
        transcriber.transcribe_local(model, recording, language, recording_duration,
                                     self._shutting_down, self.log)

    def transcribe(self, device_id, model_size, language="it"):
        try:
            if self.provider == "local":
                self.load_model(model_size)

            self.audio_queue = queue.Queue()
            self.is_recording = True
            audio_data = []

            self.log({"status": "listening", "message": "In ascolto... parla ora."})

            import time as pytime
            start_time = pytime.time()

            with sd.InputStream(device=device_id, channels=1, callback=self.audio_callback,
                                samplerate=SAMPLE_RATE, blocksize=BLOCK_SIZE):
                while self.is_recording:
                    try:
                        data = self.audio_queue.get(timeout=0.05)
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

    def run(self):
        self.log({"status": "starting", "message": "Avvio motore vocale..."})
        for line in sys.stdin:
            try:
                data = json.loads(line)
                cmd = data.get("command")
                should_quit = ipc.handle_command(cmd, data, self)
                if should_quit:
                    break
            except Exception as e:
                self.log({"status": "error", "message": str(e)})
