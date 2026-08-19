#!/usr/bin/env python3
"""Compare cloud silence trimming allocation strategies."""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src-tauri"))

from whisper_engine import transcriber  # noqa: E402
from whisper_engine.constants import (  # noqa: E402
    CLOUD_SILENCE_PADDING_SECONDS,
    CLOUD_SILENCE_THRESHOLD,
    SAMPLE_RATE,
)


def _legacy(recording: np.ndarray) -> np.ndarray:
    if recording.size == 0:
        return recording
    threshold = CLOUD_SILENCE_THRESHOLD
    if abs(recording[0]) >= threshold and abs(recording[-1]) >= threshold:
        return recording
    if recording.size <= SAMPLE_RATE * 8:
        active = np.abs(recording) >= threshold
        if not active.any():
            return recording[:0]
        first = int(active.argmax())
        last = recording.size - 1 - int(active[::-1].argmax())
    else:
        if recording.max() < threshold and recording.min() > -threshold:
            return recording[:0]
        first = None
        for chunk_start in range(0, recording.size, SAMPLE_RATE):
            chunk = recording[chunk_start : chunk_start + SAMPLE_RATE]
            active = np.abs(chunk) >= threshold
            if active.any():
                first = chunk_start + int(active.argmax())
                break
        if first is None:
            return recording[:0]
        for chunk_end in range(recording.size, first, -SAMPLE_RATE):
            chunk_start = max(first, chunk_end - SAMPLE_RATE)
            chunk = recording[chunk_start:chunk_end]
            active = np.abs(chunk) >= threshold
            if active.any():
                last = chunk_end - 1 - int(active[::-1].argmax())
                break
    padding = int(SAMPLE_RATE * CLOUD_SILENCE_PADDING_SECONDS)
    return recording[
        max(0, first - padding) : min(recording.size, last + padding + 1)
    ]


def _measure(function, recording: np.ndarray, iterations: int) -> list[float]:
    for _ in range(10):
        function(recording)
    samples = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        function(recording)
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
    return samples


def summary(label: str, samples: list[float]) -> None:
    print(
        f"{label}: median={statistics.median(samples):.4f}ms "
        f"p95={statistics.quantiles(samples, n=20)[18]:.4f}ms"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=300)
    args = parser.parse_args()
    padding = int(SAMPLE_RATE * CLOUD_SILENCE_PADDING_SECONDS)
    short = np.zeros(SAMPLE_RATE * 4, dtype=np.float32)
    short[padding + 100 : -padding - 100] = 0.03
    silent = np.zeros(SAMPLE_RATE * 4, dtype=np.float32)
    long = np.zeros(SAMPLE_RATE * 30, dtype=np.float32)
    long[padding + 100 : -(padding + 100)] = 0.03

    for label, recording in (
        ("short_speech", short),
        ("short_silence", silent),
        ("long_speech", long),
    ):
        before = _measure(_legacy, recording, args.iterations)
        after = _measure(transcriber.trim_cloud_silence, recording, args.iterations)
        summary(f"{label}_before_ms", before)
        summary(f"{label}_after_ms", after)
        print(f"{label}_equal={np.array_equal(_legacy(recording), transcriber.trim_cloud_silence(recording))}")


if __name__ == "__main__":
    main()
