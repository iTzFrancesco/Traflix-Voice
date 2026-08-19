#!/usr/bin/env python3
"""Compare the cloud audio hot path before and after its micro-optimizations."""

from __future__ import annotations

import argparse
import io
import statistics
import sys
import time
from pathlib import Path
from queue import SimpleQueue

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src-tauri"))

from whisper_engine import audio, transcriber  # noqa: E402
from whisper_engine.constants import (  # noqa: E402
    SAMPLE_RATE,
    VOLUME_CEILING_DB,
    VOLUME_DB_SCALE,
    VOLUME_FLOOR_DB,
)


def _volume_before(indata: np.ndarray) -> int:
    samples = np.asarray(indata, dtype=np.float32)
    if samples.size == 0:
        return 0
    samples = np.nan_to_num(
        samples, nan=0.0, posinf=0.0, neginf=0.0, copy=False
    )
    rms = float(np.sqrt(np.mean(np.square(samples))))
    peak = float(np.max(np.abs(samples)))
    effective_level = max(rms, peak * 0.08)
    level_db = 20.0 * np.log10(max(effective_level, 1e-6))
    normalized = (level_db - VOLUME_FLOOR_DB) / (
        VOLUME_CEILING_DB - VOLUME_FLOOR_DB
    ) * 100.0
    return int(np.clip(normalized, 0.0, 100.0))


def _volume_after(indata: np.ndarray) -> int:
    samples = np.asarray(indata, dtype=np.float32)
    if samples.size == 0:
        return 0
    samples = np.nan_to_num(
        samples, nan=0.0, posinf=0.0, neginf=0.0, copy=False
    )
    flat = samples.reshape(-1)
    peak = float(np.max(np.abs(flat)))
    rms = float(np.sqrt(np.dot(flat, flat) / samples.size))
    effective_level = max(rms, peak * 0.08)
    level_db = 20.0 * np.log10(max(effective_level, 1e-6))
    normalized = (level_db - VOLUME_FLOOR_DB) * VOLUME_DB_SCALE
    return int(np.clip(normalized, 0.0, 100.0))


def _audio_before(indata: np.ndarray) -> None:
    mono = indata[:, 0] if indata.ndim > 1 else indata
    queue = SimpleQueue()
    queue.put(mono.copy())
    audio.calculate_volume(indata)
    queue.get_nowait()


def _audio_after(indata: np.ndarray) -> None:
    mono = indata[:, 0] if indata.ndim > 1 else indata
    queued = mono.copy()
    queue = SimpleQueue()
    queue.put(queued)
    audio.calculate_volume(queued)
    queue.get_nowait()


def _wav_after(recording: np.ndarray) -> io.BytesIO:
    audio_int16 = np.empty(recording.size, dtype=np.int16)
    np.multiply(recording, 32767.0, out=audio_int16, casting="unsafe")
    pcm_data = audio_int16.tobytes()
    data_size = len(pcm_data)
    wav_header = transcriber._WAV_HEADER.pack(
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        SAMPLE_RATE,
        SAMPLE_RATE * 2,
        2,
        16,
        b"data",
        data_size,
    )
    return io.BytesIO(wav_header + pcm_data)


def _measure(function, value, iterations: int) -> list[float]:
    for _ in range(10):
        function(value)
    samples = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        function(value)
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
    return samples


def _summary(label: str, samples: list[float]) -> None:
    print(
        f"{label}: median={statistics.median(samples):.4f}ms "
        f"p95={statistics.quantiles(samples, n=20)[18]:.4f}ms "
        f"mean={statistics.mean(samples):.4f}ms"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=500)
    args = parser.parse_args()

    block = np.sin(np.linspace(0, 50, 480, dtype=np.float32)).reshape(-1, 1)
    recording = np.sin(np.linspace(0, 400, SAMPLE_RATE * 4, dtype=np.float32)) * 0.05

    audio_before = _measure(_audio_before, block, args.iterations)
    audio_after = _measure(_audio_after, block, args.iterations)
    volume_before = _measure(_volume_before, block, args.iterations)
    volume_after = _measure(_volume_after, block, args.iterations)
    wav_before = _measure(transcriber.encode_wav, recording, args.iterations)
    wav_after = _measure(_wav_after, recording, args.iterations)

    _summary("audio_before_ms", audio_before)
    _summary("audio_after_ms", audio_after)
    _summary("volume_before_ms", volume_before)
    _summary("volume_after_ms", volume_after)
    _summary("wav_before_ms", wav_before)
    _summary("wav_after_ms", wav_after)


if __name__ == "__main__":
    main()
