import sys
import json
import queue
import threading
import concurrent.futures
import time as pytime
import numpy as np
import sounddevice as sd

from whisper_engine.constants import SAMPLE_RATE, BLOCK_SIZE
from whisper_engine import model as model_module
from whisper_engine import audio as audio_module
from whisper_engine import transcriber, ipc


class _RecordingSession:
    """Own the queue and stop signal for exactly one audio stream."""

    def __init__(self, capture_queue=None, provider=None):
        self.queue = capture_queue if capture_queue is not None else queue.SimpleQueue()
        self.provider = provider
        self.active = threading.Event()
        self.active.set()
        # The callback runs under the CPython GIL. Reading this per-session
        # flag avoids an Event syscall on every PortAudio block while the
        # Event remains available for lifecycle checks outside the callback.
        self.is_active = True
        self._stop_lock = threading.Lock()
        self._stop_sent = False

    def stop(self):
        with self._stop_lock:
            if self._stop_sent:
                return
            self._stop_sent = True
            self.is_active = False
            self.active.clear()
            self.queue.put(None)


class WhisperEngine:
    def __init__(self):
        self.model = None
        self.current_model_size = None
        # Audio blocks are only transferred between the callback and the
        # capture worker. SimpleQueue avoids the task-tracking and condition
        # bookkeeping that Queue adds to this hot path.
        self.audio_queue = queue.SimpleQueue()
        self.is_recording = False
        self._recording_lock = threading.Lock()
        self._active_session = None
        self.models_dir = None
        self._shutting_down = False
        self._model_lock = threading.Lock()
        self.current_device = "cpu"
        self.compute_device = "cpu"
        self.groq_api_key = None
        self.provider = "local"
        self._loading_in_progress = False
        # Capture must be independent from cloud/local processing. A request
        # can still be waiting on Groq when the user starts the next clip.
        self._capture_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="capture",
        )
        self._transcription_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="transcription",
        )

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

    def prepare_groq_client(self, api_key=None):
        # Capture the key that triggered prewarming. A delayed thread for an
        # older key must not replace the client selected by a newer setting or
        # resurrect a client while the sidecar is shutting down.
        key = self.groq_api_key if api_key is None else api_key
        if self._shutting_down or not key or key != self.groq_api_key:
            return
        if key:
            try:
                transcriber.get_groq_client(key)
            except Exception:
                # The normal transcription path reports configuration/import
                # errors to the UI; prewarming must never block startup.
                pass

    def stop_recording(self):
        with self._recording_lock:
            self.is_recording = False
            session = self._active_session
        # Wake only the current capture loop. A later recording owns a
        # different queue, so an old stop cannot poison the next session.
        if session is not None:
            session.stop()
        else:
            self.audio_queue.put(None)

    def prepare_transcription_worker(self):
        """Start capture and processing workers before the first hotkey press."""
        self._capture_executor.submit(lambda: None).result()
        self._transcription_executor.submit(lambda: None).result()

    def start_transcription(self, device_id, model_size, language="it"):
        """Dispatch recording without paying per-session thread startup."""
        audio_module.reset_volume_state()
        session = _RecordingSession(provider=self.provider)
        with self._recording_lock:
            previous = self._active_session
            self._active_session = session
            self.audio_queue = session.queue
            self.is_recording = True
        if previous is not None:
            previous.stop()
        return self._capture_executor.submit(
            self.transcribe,
            device_id,
            model_size,
            language,
            session.queue,
            session,
            True,
        )

    def close_transcription_worker(self):
        # Let the capture worker consume the stop sentinel before closing the
        # processing executor; otherwise a final capture could race its
        # deferred submit during sidecar shutdown.
        self.stop_recording()
        self._capture_executor.shutdown(wait=True, cancel_futures=True)
        self._transcription_executor.shutdown(wait=False, cancel_futures=True)

    def audio_callback(
        self,
        indata,
        frames,
        time,
        status,
        capture_queue=None,
        recording_event=None,
        recording_active=None,
    ):
        if capture_queue is None:
            capture_queue = self.audio_queue
        if recording_active is not None:
            is_recording = recording_active
        elif recording_event is not None:
            is_recording = recording_event.is_set()
        else:
            is_recording = self.is_recording
        audio_module.audio_callback(
            indata, frames, time, status, capture_queue, is_recording, self.log
        )

    def _transcribe_cloud(self, recording, language, recording_duration):
        transcriber.transcribe_cloud(recording, language, recording_duration, self.groq_api_key,
                                     lambda: self._shutting_down, self.log, self.models_dir)

    def _transcribe_local(self, recording, model_size, language, recording_duration):
        with self._model_lock:
            model = self.model
            if model is None:
                self.log({"status": "error", "message": "Modello scaricato durante la trascrizione."})
                if not self._shutting_down:
                    self.log({"status": "ready", "message": "Motore Whisper pronto."})
                return
        transcriber.transcribe_local(model, recording, language, recording_duration,
                                     self._shutting_down, self.log)

    def _process_recording(
        self,
        recording,
        model_size,
        language,
        recording_duration,
        provider,
    ):
        try:
            if provider == "cloud":
                self._transcribe_cloud(recording, language, recording_duration)
            else:
                self._transcribe_local(recording, model_size, language, recording_duration)
        except Exception as e:
            self.log({"status": "error", "message": str(e)})
            if not self._shutting_down:
                self.log({"status": "ready", "message": "Motore Whisper pronto."})

    def transcribe(
        self,
        device_id,
        model_size,
        language="it",
        capture_queue=None,
        capture_session=None,
        defer_processing=False,
    ):
        session = capture_session
        try:
            if session is None:
                session = _RecordingSession(capture_queue, provider=self.provider)
                with self._recording_lock:
                    self._active_session = session
                    self.audio_queue = session.queue
                    self.is_recording = True

            if not session.active.is_set() or self._shutting_down:
                return

            # Keep the provider selected when the session started. This
            # avoids repeated attribute reads and, more importantly, prevents
            # a settings toggle during capture from changing the destination
            # of an already-recorded clip.
            provider = session.provider if session.provider is not None else self.provider
            if provider == "local":
                self.load_model(model_size)

            if not session.active.is_set():
                return
            audio_data = []

            self.log({"status": "listening", "message": "In ascolto... parla ora."})

            start_time = pytime.monotonic()

            def session_audio_callback(indata, frames, callback_time, status):
                self.audio_callback(
                    indata,
                    frames,
                    callback_time,
                    status,
                    session.queue,
                    recording_active=session.is_active,
                )

            with sd.InputStream(device=device_id, channels=1, callback=session_audio_callback,
                                samplerate=SAMPLE_RATE, blocksize=BLOCK_SIZE,
                                dtype="float32"):
                while True:
                    data = session.queue.get()
                    if data is None:
                        break
                    audio_data.append(data)

            recording_duration = max(0.0, pytime.monotonic() - start_time)

            self.log({"status": "processing", "message": "Trascrizione in corso..."})

            if not audio_data:
                self.log({"status": "ready", "message": "Nessun audio catturato."})
                return

            # A very short cloud dictation can fit in one callback block. Keep
            # that already-owned mono array instead of allocating/copying it
            # through concatenate; multi-block recordings retain the existing
            # contiguous representation.
            recording = (
                audio_data[0]
                if len(audio_data) == 1
                else np.concatenate(audio_data, axis=0)
            )
            if recording.dtype != np.float32:
                recording = recording.astype(np.float32, copy=False)

            if defer_processing:
                self._transcription_executor.submit(
                    self._process_recording,
                    recording,
                    model_size,
                    language,
                    recording_duration,
                    provider,
                )
            else:
                self._process_recording(
                    recording,
                    model_size,
                    language,
                    recording_duration,
                    provider,
                )

        except Exception as e:
            self.log({"status": "error", "message": str(e)})
            if not self._shutting_down:
                self.log({"status": "ready", "message": "Motore Whisper pronto."})
        finally:
            if session is not None:
                with self._recording_lock:
                    if self._active_session is session:
                        self._active_session = None
                        self.is_recording = False

    def run(self):
        self.prepare_transcription_worker()
        self.log({"status": "starting", "message": "Avvio motore vocale..."})
        try:
            for line in sys.stdin:
                try:
                    data = json.loads(line)
                    cmd = data.get("command")
                    should_quit = ipc.handle_command(cmd, data, self)
                    if should_quit:
                        break
                except Exception as e:
                    self.log({"status": "error", "message": str(e)})
        finally:
            self.close_transcription_worker()
