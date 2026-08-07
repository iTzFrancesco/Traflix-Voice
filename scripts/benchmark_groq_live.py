#!/usr/bin/env python3
"""Measure the real cloud transcription path without exposing the API key.

The key must be supplied through GROQ_API_KEY. This script intentionally does
not load .env files or print request headers. It measures the HTTP request and
Groq inference time, while the deterministic benchmarks cover local pipeline
overhead separately.
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
import wave
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src-tauri"))

from whisper_engine.constants import SAMPLE_RATE  # noqa: E402
from whisper_engine.transcriber import transcribe_cloud  # noqa: E402


def load_recording(path: str | None) -> tuple[np.ndarray, float]:
    if path:
        with wave.open(path, "rb") as wav:
            if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
                raise ValueError("Il WAV deve essere mono PCM 16-bit")
            if wav.getframerate() != SAMPLE_RATE:
                raise ValueError(f"Il WAV deve essere a {SAMPLE_RATE} Hz")
            frames = wav.readframes(wav.getnframes())
        recording = (
            np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
        )
        return recording, len(recording) / SAMPLE_RATE

    duration = 0.5
    recording = (
        np.sin(np.linspace(0, 1600, int(SAMPLE_RATE * duration), dtype=np.float32))
        * 0.03
    ).astype(np.float32)
    return recording, duration


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wav", help="WAV mono PCM 16-bit a 16 kHz da trascrivere")
    parser.add_argument("--language", default="it")
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=5)
    args = parser.parse_args()

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise SystemExit("Imposta GROQ_API_KEY nell'ambiente del processo")
    if args.iterations < 1 or args.warmup < 0:
        raise SystemExit("warmup >= 0 e iterations >= 1 sono richiesti")

    recording, duration = load_recording(args.wav)
    statuses: list[str] = []

    def log(event: dict) -> None:
        status = event.get("status")
        if status in {"result", "error", "rate_limit"}:
            statuses.append(str(status))

    for _ in range(args.warmup):
        transcribe_cloud(recording, args.language, duration, api_key, False, log, None)

    samples_ms: list[float] = []
    for _ in range(args.iterations):
        started = time.perf_counter()
        transcribe_cloud(recording, args.language, duration, api_key, False, log, None)
        samples_ms.append((time.perf_counter() - started) * 1000)

    print("groq_live_ms")
    print(f"statuses={','.join(statuses)}")
    print(f"median={statistics.median(samples_ms):.1f}")
    print(f"p95={statistics.quantiles(samples_ms, n=20)[18] if len(samples_ms) > 1 else samples_ms[0]:.1f}")
    print(f"mean={statistics.mean(samples_ms):.1f}")
    print(f"min={min(samples_ms):.1f}")
    print(f"max={max(samples_ms):.1f}")


if __name__ == "__main__":
    main()
