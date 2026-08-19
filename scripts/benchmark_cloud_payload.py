#!/usr/bin/env python3
"""Benchmark the cloud WAV-to-multipart payload construction."""

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
from whisper_engine.constants import SAMPLE_RATE  # noqa: E402


def _candidate_fallback(recording: np.ndarray) -> bytes:
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
    return b"".join(
        (
            transcriber._MULTIPART_PREFIXES["it"],
            wav_header + pcm_data,
            transcriber._MULTIPART_SUFFIX,
        )
    )


def _before(recording: np.ndarray) -> bytes:
    return transcriber.encode_cloud_multipart(
        transcriber.encode_wav(recording),
        "it",
    )


def _after(recording: np.ndarray) -> bytes:
    builder = getattr(transcriber, "encode_cloud_multipart_from_recording", None)
    if builder is not None:
        return builder(recording, "it", assume_normalized=True)
    return _candidate_fallback(recording)


def _measure(function, recording: np.ndarray, iterations: int) -> list[float]:
    for _ in range(10):
        function(recording)
    samples = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        function(recording)
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
    parser.add_argument("--iterations", type=int, default=300)
    args = parser.parse_args()

    recording = np.sin(
        np.linspace(0, 400, SAMPLE_RATE * 4, dtype=np.float32)
    ) * 0.05

    before = _measure(_before, recording, args.iterations)
    after = _measure(_after, recording, args.iterations)
    before_payload = _before(recording)
    after_payload = _after(recording)

    _summary("payload_before_ms", before)
    _summary("payload_after_ms", after)
    print(f"payload_bytes_before={len(before_payload)}")
    print(f"payload_bytes_after={len(after_payload)}")
    print(f"payload_equal={before_payload == after_payload}")


if __name__ == "__main__":
    main()
