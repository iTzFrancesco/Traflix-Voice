"""Persistent transcribe.cpp helper for the same Parakeet v3 GGUF used by Hex."""
import hashlib
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading

import numpy as np
from huggingface_hub import hf_hub_download

FILENAME = "parakeet-tdt-0.6b-v3-Q8_0.gguf"
REPO_ID = "handy-computer/parakeet-tdt-0.6b-v3-gguf"
REVISION = "85ac09ea12fc4b1112fa76810059364bc6adc9de"
MODEL_BYTES = 739_508_576
MODEL_SHA256 = "5859f77944efcd8eafa23a6350731960b2b55b2203df51f319665c807d802cc7"
_verified = set()


def helper_path():
    name = "traflix-transcriber.exe" if sys.platform == "win32" else "traflix-transcriber"
    if getattr(sys, "frozen", False):
        path = Path(sys.executable).parent / name
    else:
        path = Path(__file__).resolve().parents[1] / "native-transcriber" / "target" / "release" / name
    return path if path.is_file() else None


def verify(directory, checksum=False):
    path = Path(directory) / FILENAME
    try:
        stat = path.stat()
        if stat.st_size != MODEL_BYTES:
            return False
        if checksum:
            key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
            if key not in _verified:
                digest = hashlib.sha256()
                with path.open("rb") as source:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(block)
                if digest.hexdigest() != MODEL_SHA256:
                    return False
                _verified.clear()
                _verified.add(key)
        return True
    except OSError:
        return False


def download(directory):
    hf_hub_download(repo_id=REPO_ID, revision=REVISION, filename=FILENAME, local_dir=directory)
    if not verify(directory, checksum=True):
        # Do not delete an existing model or the legacy ONNX fallback on failure.
        raise RuntimeError("Verifica SHA-256 del modello GGUF fallita. Ripeti il download.")


class NativeSession:
    def __init__(self, executable, model_path):
        self.executable = str(executable)
        self.model_path = str(model_path)
        self.lock = threading.Lock()
        self.process = None
        self.metadata = self._start()

    def _start(self):
        self.process = subprocess.Popen(
            [self.executable], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        replies = self.replies = queue.Queue()
        output = self.process.stdout

        def read_replies():
            try:
                for line in output:
                    replies.put(json.loads(line))
            except (ValueError, OSError):
                pass
            finally:
                replies.put(None)

        threading.Thread(target=read_replies, name="native-asr-output", daemon=True).start()
        return self._exchange({"command": "init", "model": self.model_path}, timeout=180)

    def _exchange(self, command, audio=None, timeout=60):
        try:
            self.process.stdin.write((json.dumps(command) + "\n").encode("utf-8"))
            if audio is not None:
                self.process.stdin.write(memoryview(audio).cast("B"))
            self.process.stdin.flush()
            reply = self.replies.get(timeout=timeout)
            if reply is None:
                raise RuntimeError("Motore nativo terminato durante la trascrizione.")
            if reply.get("status") == "error":
                raise RuntimeError(reply.get("message", "Errore motore nativo"))
            expected = "ready" if command["command"] == "init" else "result"
            if reply.get("status") != expected:
                raise RuntimeError("Risposta inattesa dal motore nativo.")
            return reply
        except queue.Empty as error:
            self.close()
            raise RuntimeError(f"Timeout del motore nativo dopo {timeout} secondi.") from error
        except Exception:
            self.close()
            raise

    def transcribe(self, audio):
        audio = np.ascontiguousarray(audio, dtype="<f4").reshape(-1)
        if not 0 < audio.size <= 16_000 * 600:
            raise ValueError("Il segmento audio supera il limite di 10 minuti.")
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                self.close()
                self.metadata = self._start()
            return self._exchange({"command": "transcribe", "samples": int(audio.size)}, audio)["text"]

    def close(self):
        process, self.process = self.process, None
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            for pipe in (process.stdin, process.stdout):
                if pipe:
                    pipe.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


class NativeRecognizer:
    def __init__(self, session):
        self._session = session

    def snapshot(self):
        return NativeRecognizer(self._session)

    def close(self):
        self._session = None

    def transcribe(self, recording, language=""):
        from whisper_engine.parakeet import (
            _compact_digital_pauses, _split_at_pauses, _CHUNK_CONTEXT_SAMPLES, _Segment,
        )
        session = self._session
        audio = _compact_digital_pauses(np.ascontiguousarray(recording, dtype=np.float32).reshape(-1))
        chunks = _split_at_pauses(audio)
        segments = []
        for index, chunk in enumerate(chunks):
            leading = _CHUNK_CONTEXT_SAMPLES if index else 0
            trailing = _CHUNK_CONTEXT_SAMPLES if index < len(chunks) - 1 else 0
            if leading or trailing:
                chunk = np.pad(chunk, (leading, trailing))
            segments.append(_Segment(session.transcribe(chunk)))
        return segments


def load(directory, log_func):
    if not verify(directory, checksum=True):
        raise RuntimeError("Modello GGUF mancante o non valido. Scarica Parakeet dalla tab IA.")
    session = NativeSession(helper_path(), Path(directory) / FILENAME)
    log_func({"status": "info", "message": (
        f"Parakeet GGUF pronto: transcribe.cpp, {session.metadata['backend']}, "
        f"{session.metadata['device']}."
    )})
    log_func({"status": "gpu_info", "current_device": session.metadata["backend"],
              "device_name": session.metadata["device"],
              "message": f"Dispositivo in uso: {session.metadata['device']} ({session.metadata['backend']})"})
    return NativeRecognizer(session)
