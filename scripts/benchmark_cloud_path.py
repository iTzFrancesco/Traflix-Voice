#!/usr/bin/env python3
"""Benchmark the Cloud/Groq request path without making a network request.

The fake Groq adapter keeps the measurement focused on client construction and
audio payload preparation. Network latency must be measured separately with a
real API key and is intentionally not part of this deterministic benchmark.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
import types
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src-tauri"))


class _FakeTranscriptions:
    def create(self, **_kwargs):
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

from whisper_engine import transcriber  # noqa: E402


def run_once(recording: np.ndarray) -> None:
    transcriber.transcribe_cloud(
        recording,
        "it",
        1.0,
        "fake-key",
        False,
        lambda _event: None,
        None,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--iterations", type=int, default=100)
    args = parser.parse_args()

    recording = (
        np.sin(np.linspace(0, 200, 16000, dtype=np.float32)) * 0.05
    ).astype(np.float32)

    for _ in range(args.warmup):
        run_once(recording)

    samples_ms = []
    for _ in range(args.iterations):
        started = time.perf_counter()
        run_once(recording)
        samples_ms.append((time.perf_counter() - started) * 1000)

    print("cloud_path_deterministic_ms")
    print(f"iterations={len(samples_ms)}")
    print(f"median={statistics.median(samples_ms):.3f}")
    print(f"p95={statistics.quantiles(samples_ms, n=20)[18]:.3f}")
    print(f"mean={statistics.mean(samples_ms):.3f}")
    print(f"min={min(samples_ms):.3f}")
    print(f"max={max(samples_ms):.3f}")


if __name__ == "__main__":
    main()
