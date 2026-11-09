"""Persistent transcribe.cpp helper for the pinned Parakeet Ultra GGUF."""
import hashlib
import json
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time
import unicodedata

import numpy as np
from huggingface_hub import hf_hub_download

FILENAME = "parakeet-ultra-Q8_0.gguf"
REPO_ID = "handy-computer/parakeet-ultra-gguf"
REVISION = "a1539be1b849ea7463b88343e5277b373d0c4ea9"
MODEL_BYTES = 740_363_168
MODEL_SHA256 = "007a59761e9258779f189df396b50d12b83bb5b79e66df4b955c230d2f2a0a59"
LEGACY_MODEL_DIRS = ("parakeet-tdt-0.6b-v3-int8",)
_verified = set()
_gpu_probe = {}


def helper_path():
    name = "traflix-transcriber.exe" if sys.platform == "win32" else "traflix-transcriber"
    if getattr(sys, "frozen", False):
        path = Path(sys.executable).parent / name
    else:
        path = Path(__file__).resolve().parents[1] / "native-transcriber" / "target" / "release" / name
    return path if path.is_file() else None


def gpu_available():
    path = helper_path()
    if path is None:
        return False
    key = (str(path), path.stat().st_mtime_ns)
    cached = _gpu_probe.get(key)
    if cached is not None and time.monotonic() - cached[0] < 60:
        return cached[1]
    try:
        result = subprocess.run([str(path)], cwd=path.parent,
            input=b'{"command":"probe"}\n{"command":"quit"}\n', stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=True)
        reply = json.loads(result.stdout.splitlines()[0])
        available = reply.get("status") == "probe" and reply.get("gpu_available") is True
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        available = False
    _gpu_probe.clear()
    _gpu_probe[key] = (time.monotonic(), available)
    return available


def disable_gpu():
    path = helper_path()
    if path is not None:
        _gpu_probe[(str(path), path.stat().st_mtime_ns)] = (time.monotonic(), False)


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
    Path(directory).mkdir(parents=True, exist_ok=True)
    hf_hub_download(repo_id=REPO_ID, revision=REVISION, filename=FILENAME, local_dir=directory)
    if not verify(directory, checksum=True):
        raise RuntimeError("Verifica SHA-256 del modello GGUF fallita. Ripeti il download.")


def cleanup_legacy_models(models_dir, log_func=None):
    """Remove only the previously supported Parakeet v3 directory."""
    root = Path(models_dir).resolve()
    for model_id in LEGACY_MODEL_DIRS:
        legacy_dir = root / model_id
        try:
            if legacy_dir.is_symlink() or legacy_dir.parent.resolve() != root:
                continue
            if legacy_dir.is_dir():
                shutil.rmtree(legacy_dir)
                if log_func is not None:
                    log_func({
                        "status": "info",
                        "message": f"Rimosso il vecchio modello {model_id} dopo la verifica di Parakeet Ultra.",
                    })
        except OSError as error:
            if log_func is not None:
                log_func({
                    "status": "warning",
                    "message": f"Il vecchio modello {model_id} non è stato rimosso: {error}",
                })


class NativeSession:
    def __init__(self, executable, model_path, cpu_only=False):
        self.executable = str(executable)
        self.model_path = str(model_path)
        self.cpu_only = cpu_only
        self.lock = threading.Lock()
        self.process = None
        self.metadata = self._start()

    def _start(self):
        if self.cpu_only:
            return self._start_backend(True)
        try:
            return self._start_backend(False)
        except (RuntimeError, OSError):
            # A driver can fail during Vulkan initialization. Retry in a fresh
            # process with only CPU modules registered.
            self.cpu_only = True
            return self._start_backend(True)

    def _start_backend(self, cpu_only):
        self.process = subprocess.Popen(
            [self.executable], cwd=str(Path(self.executable).parent),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
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
        return self._exchange({"command": "init", "model": self.model_path, "cpu_only": cpu_only}, timeout=180)

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
            _compact_digital_pauses, _split_at_pauses, _CHUNK_CONTEXT_SAMPLES,
            _CHUNK_OVERLAP_SAMPLES, _Segment,
        )
        session = self._session
        audio = _compact_digital_pauses(np.ascontiguousarray(recording, dtype=np.float32).reshape(-1))
        chunks = _split_at_pauses(audio)
        if len(chunks) == 1:
            return [_Segment(session.transcribe(chunks[0]))]

        texts = []
        offset = 0
        for index, core in enumerate(chunks):
            core_end = offset + core.size
            start = max(0, offset - _CHUNK_OVERLAP_SAMPLES)
            end = min(audio.size, core_end + _CHUNK_OVERLAP_SAMPLES)
            chunk = audio[start:end]
            leading = _CHUNK_CONTEXT_SAMPLES if index == 0 else 0
            trailing = _CHUNK_CONTEXT_SAMPLES if index == len(chunks) - 1 else 0
            if leading or trailing:
                chunk = np.pad(chunk, (leading, trailing))
            texts.append(session.transcribe(chunk).strip())
            offset = core_end
        return [_Segment(_merge_overlapping_text(texts))]


def _merge_overlapping_text(texts):
    merged = []
    for text in texts:
        words = text.split()
        if not words:
            continue
        overlap = 0
        if merged:
            previous = " ".join(merged)
            previous_words = previous.split()
            limit = min(12, len(previous_words), len(words))
            for size in range(limit, 0, -1):
                left = [_word_key(word) for word in previous_words[-size:]]
                right = [_word_key(word) for word in words[:size]]
                if all(left) and left == right:
                    overlap = size
                    break
        merged.extend(words[overlap:])
    return " ".join(merged).strip()


def _word_key(word):
    return "".join(
        character.casefold()
        for character in word
        if not unicodedata.category(character).startswith("P")
    )


def load(directory, log_func, cpu_only=False):
    if not verify(directory, checksum=True):
        raise RuntimeError("Modello GGUF mancante o non valido. Scarica Parakeet Ultra dalla tab IA.")
    executable = helper_path()
    if executable is None:
        raise RuntimeError("Motore nativo mancante. Ricompila l'helper transcribe.cpp e riavvia l'app.")
    session = NativeSession(executable, Path(directory) / FILENAME, cpu_only=cpu_only)
    cleanup_legacy_models(Path(directory).parent, log_func)
    log_func({"status": "info", "message": (
        f"Parakeet GGUF pronto: transcribe.cpp, {session.metadata['backend']}, "
        f"{session.metadata['device']}."
    )})
    log_func({"status": "gpu_info", "current_device": session.metadata["backend"],
              "device_name": session.metadata["device"],
              "message": f"Dispositivo in uso: {session.metadata['device']} ({session.metadata['backend']})"})
    return NativeRecognizer(session)
