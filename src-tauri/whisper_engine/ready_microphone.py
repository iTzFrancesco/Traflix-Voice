"""Provider-independent microphone ownership and bounded idle pre-roll."""
from collections import deque
from contextlib import contextmanager
import threading
import time

import numpy as np
from whisper_engine.constants import SAMPLE_RATE, BLOCK_SIZE

PRE_ROLL_SAMPLES = int(0.45 * SAMPLE_RATE)


class ReadyMicrophone:
    def __init__(self, stream_factory):
        self.factory = stream_factory
        self.control = threading.Lock()
        self.state = threading.RLock()
        self.stream = None
        self.device = None
        self.healthy = False
        self.generation = 0
        self.ring = deque()
        self.samples = 0
        self.active = None
        self.failure = None

    def _callback(self, generation, indata, frames, callback_time, status):
        with self.state:
            if generation != self.generation:
                return
            if self.active is not None:
                session, callback = self.active
                if session.is_active:
                    callback(indata, frames, callback_time, status)
                return
            mono = np.asarray(indata[:, 0] if indata.ndim > 1 else indata, dtype=np.float32).copy()
            self.ring.append(mono)
            self.samples += mono.size
            while self.samples > PRE_ROLL_SAMPLES:
                excess = self.samples - PRE_ROLL_SAMPLES
                first = self.ring.popleft()
                if first.size > excess:
                    self.ring.appendleft(first[excess:].copy())
                    self.samples -= excess
                else:
                    self.samples -= first.size

    def _finished(self, generation):
        with self.state:
            if generation != self.generation:
                return
            self.healthy = False
            self.failure = "Il microfono si è disconnesso. Riprova per riconnetterlo."
            if self.active is not None:
                self.active[0].stop(drain_seconds=0)

    def _close(self):
        with self.state:
            stream, self.stream = self.stream, None
            self.generation += 1
            self.healthy = False
            self.ring.clear()
            self.samples = 0
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()

    def _ensure(self, device):
        with self.state:
            if self.stream is not None and self.healthy and self.device == device:
                return
        self._close()
        with self.state:
            generation = self.generation
            self.device = device
            self.failure = None
            self.healthy = True
        stream = None
        try:
            stream = self.factory(device=device, channels=1, samplerate=SAMPLE_RATE,
                                  blocksize=BLOCK_SIZE, dtype="float32",
                                  callback=lambda *args: self._callback(generation, *args),
                                  finished_callback=lambda: self._finished(generation))
            self.stream = stream
            stream.start()
            if not self.healthy:
                raise RuntimeError(self.failure or "Microfono non disponibile")
        except Exception:
            self._close()
            raise

    def prepare(self, enabled, device):
        with self.control:
            with self.state:
                if self.active is not None:
                    return  # Apply the latest configuration after this clip.
            if enabled:
                self._ensure(device)
            else:
                self._close()

    @contextmanager
    def capture(self, device, session, callback):
        with self.control:
            self._ensure(device)
            with self.state:
                if self.active is not None:
                    raise RuntimeError("Microfono già in uso")
                for block in self.ring:
                    session.queue.put(block)
                if self.ring:
                    session.first_block_at = time.monotonic()
                self.ring.clear()
                self.samples = 0
                self.active = (session, callback)
        try:
            yield
        finally:
            # Fence callbacks before the capture worker drains the queue.
            with self.state:
                self.active = None
                self.ring.clear()
                self.samples = 0
                failure = self.failure
            if failure:
                raise RuntimeError(failure)

    def close(self):
        with self.control:
            self._close()
