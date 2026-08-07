#!/usr/bin/env python3
"""Measure stop-to-request latency through the Python Cloud path.

The audio stream and Groq HTTP response are deterministic fakes, but the
benchmark uses the real engine, IPC stop command, queue drain, WAV
preparation, cached client and result handling. It intentionally excludes
network time.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import threading
import time
import types
from pathlib import Path

import httpx
import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src-tauri"))


_request_event: threading.Event | None = None


class _FakeTranscriptions:
    def create(self, **_kwargs):
        if _request_event is not None:
            _request_event.set()
        return "testo simulato"


class _FakeAudio:
    def __init__(self):
        self.transcriptions = _FakeTranscriptions()


class _FakeGroq:
    def __init__(self, **_kwargs):
        self.audio = _FakeAudio()


fake_groq = types.ModuleType("groq")
fake_groq.Groq = _FakeGroq
sys.modules["groq"] = fake_groq

# The benchmark replaces the stream below, so it does not need PortAudio.
fake_sounddevice = types.ModuleType("sounddevice")
fake_sounddevice.InputStream = None
sys.modules["sounddevice"] = fake_sounddevice

from whisper_engine import engine as engine_module  # noqa: E402
from whisper_engine import transcriber  # noqa: E402
from whisper_engine.constants import BLOCK_SIZE  # noqa: E402
from whisper_engine.ipc import handle_command  # noqa: E402


def _fake_http_client(_api_key):
    def handler(request):
        if _request_event is not None:
            _request_event.set()
        return httpx.Response(200, text="testo simulato", request=request)

    return httpx.Client(transport=httpx.MockTransport(handler))


transcriber.create_groq_client = _fake_http_client


class _FakeInputStream:
    def __init__(self, engine, ready_event, blocks):
        self.engine = engine
        self.ready_event = ready_event
        self.blocks = blocks

    def __enter__(self):
        block = np.zeros((BLOCK_SIZE, 1), dtype=np.float32)
        for _ in range(self.blocks):
            self.engine.audio_queue.put(block)
        self.ready_event.set()
        return self

    def __exit__(self, *_args):
        return False


def run_once(blocks: int, prewarm: bool = False) -> tuple[float, float]:
    global _request_event

    request_event = threading.Event()
    result_event = threading.Event()
    ready_event = threading.Event()
    failures = []
    _request_event = request_event
    engine = engine_module.WhisperEngine()
    engine.provider = "cloud"
    engine.groq_api_key = "fake-key"
    if prewarm:
        engine.prepare_groq_client()

    def log(event):
        if event.get("status") == "error":
            failures.append(event.get("message", "unknown engine error"))
        if event.get("status") == "result":
            result_event.set()

    engine.log = log
    stream_factory = lambda **_kwargs: _FakeInputStream(engine, ready_event, blocks)

    original_stream = engine_module.sd.InputStream
    engine_module.sd.InputStream = stream_factory
    try:
        worker = threading.Thread(
            target=engine.transcribe,
            args=(None, "small", "it"),
        )
        worker.start()
        if not ready_event.wait(1.0):
            raise RuntimeError(f"audio stream did not become ready: {failures}")
        deadline = time.perf_counter() + 1.0
        while not engine.audio_queue.empty() and time.perf_counter() < deadline:
            time.sleep(0.0001)
        if not engine.audio_queue.empty():
            raise RuntimeError("audio block was not consumed")

        stopped_at = time.perf_counter()
        handle_command("stop", {}, engine)
        if not request_event.wait(2.0):
            raise RuntimeError("fake Groq request did not start")
        requested_at = time.perf_counter()
        if not result_event.wait(2.0):
            raise RuntimeError("fake transcription result did not arrive")
        resulted_at = time.perf_counter()
        worker.join(2.0)
        if worker.is_alive():
            raise RuntimeError("transcription worker did not finish")
        return (
            (requested_at - stopped_at) * 1000,
            (resulted_at - stopped_at) * 1000,
        )
    finally:
        engine_module.sd.InputStream = original_stream
        _request_event = None


def summarize(label: str, samples: list[float]) -> None:
    print(label)
    print(f"median={statistics.median(samples):.3f}")
    print(f"p95={statistics.quantiles(samples, n=20)[18]:.3f}")
    print(f"mean={statistics.mean(samples):.3f}")
    print(f"min={min(samples):.3f}")
    print(f"max={max(samples):.3f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--iterations", type=int, default=50)
    parser.add_argument("--blocks", type=int, default=1)
    parser.add_argument("--prewarm", action="store_true")
    args = parser.parse_args()

    transcriber.close_groq_client()
    for _ in range(args.warmup):
        run_once(args.blocks, args.prewarm)

    request_samples = []
    result_samples = []
    for _ in range(args.iterations):
        requested, resulted = run_once(args.blocks, args.prewarm)
        request_samples.append(requested)
        result_samples.append(resulted)

    summarize("stop_to_request_ms", request_samples)
    summarize("stop_to_result_ms", result_samples)
    transcriber.close_groq_client()


if __name__ == "__main__":
    main()
