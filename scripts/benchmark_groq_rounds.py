#!/usr/bin/env python3
"""Compare 60 Groq preparation experiments against a frozen source snapshot.

The other 40 experiments are gain and Android upload comparisons. This script
uses synthetic samples and HTTPX MockTransport only. It never reads credentials,
records a microphone or contacts Groq. Pipeline timings include gain, trim, WAV,
HTTP request construction and result handling, but exclude capture, tail, network,
the desktop shell and UI. Snapshot audio.py and transcriber.py before editing.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import platform
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

import httpx
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src-tauri"))

from whisper_engine import audio, transcriber  # noqa: E402
from whisper_engine.constants import (  # noqa: E402
    GROQ_MULTIPART_BOUNDARY,
    SAMPLE_RATE,
)


def load_snapshot(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def profiles():
    fixtures = [
        ("single_block", 512, "quiet"),
        ("125ms", 2_000, "quiet"),
        ("250ms", 4_000, "quiet"),
        ("500ms", 8_000, "quiet"),
        ("1s_peak", 16_000, "peak"),
        ("2s_quiet", 32_000, "quiet"),
        ("4s_quiet", 64_000, "quiet"),
        ("4s_loud", 64_000, "loud"),
        ("8s_boundary", 128_000, "quiet"),
        ("8s_plus_sample", 128_001, "quiet"),
        ("12s_negative", 192_000, "negative"),
        ("30s_quiet", 480_000, "quiet"),
        ("60s_quiet", 960_000, "quiet"),
        ("120s_quiet", 1_920_000, "quiet"),
        ("180s_quiet", 2_880_000, "quiet"),
        ("1s_silence", 16_000, "silence"),
        ("30s_silence", 480_000, "silence"),
        ("30s_late_onset", 480_000, "late"),
        ("60s_hiss", 960_000, "hiss"),
        ("12s_strided", 192_000, "strided"),
    ]
    languages = ("it", "en", None, "es", "fr", "de", "pt", "ja")
    for index, (name, count, pattern) in enumerate(fixtures):
        phase = np.arange(count, dtype=np.float32) * np.float32(2 * np.pi * 220 / SAMPLE_RATE)
        samples = (np.sin(phase) * (0.15 if pattern == "loud" else 0.01)).astype(np.float32)
        samples[:min(1600, count // 4)] = 0
        samples[-min(3520, count // 4):] = 0
        if pattern == "silence":
            samples.fill(0)
        elif pattern == "negative":
            samples[count // 4:count * 3 // 4] = -0.0002
        elif pattern == "peak":
            samples[count // 2] = 0.95
        elif pattern == "late":
            samples[:SAMPLE_RATE * 4] = 0
            samples[-SAMPLE_RATE * 3:] = 0
        elif pattern == "hiss":
            samples[:] = 0.0002
        elif pattern == "strided":
            storage = np.zeros(count * 2, dtype=np.float32)
            storage[::2] = samples
            samples = storage[::2]
        yield name, samples, languages[index % len(languages)]


class OfflinePipeline:
    def __init__(self, module, gain_module):
        self.module = module
        self.gain = gain_module.apply_automatic_gain
        self.last_request = None
        self.client = httpx.Client(
            transport=httpx.MockTransport(self.respond),
            headers={
                "Authorization": "Bearer synthetic-benchmark-key",
                "Content-Type": f"multipart/form-data; boundary={GROQ_MULTIPART_BOUNDARY}",
            },
        )
        module.close_groq_client()
        self.original_create = module.create_groq_client
        module.create_groq_client = lambda _key: self.client
        module.get_groq_client("synthetic-benchmark-key")

    def respond(self, request):
        self.last_request = request
        return httpx.Response(200, content=b"benchmark transcript", request=request)

    def invocation(self, samples, language):
        # The private mutable gain input is copied outside the timed interval.
        recording = samples.copy()
        events = []

        def run():
            self.last_request = None
            self.gain(recording)
            self.module.transcribe_cloud(
                recording, language, samples.size / SAMPLE_RATE,
                "synthetic-benchmark-key", False, events.append, None,
            )
            request = self.last_request
            return (events, request.content if request is not None else None,
                    str(request.url) if request is not None else None)

        return run

    def close(self):
        self.module.close_groq_client()
        self.module.create_groq_client = self.original_create
        self.client.close()


def equal(left, right):
    if isinstance(left, np.ndarray):
        return np.array_equal(left, right, equal_nan=True)
    return left == right


def percentile95(values):
    return sorted(values)[math.ceil(len(values) * 0.95) - 1]


def peak_allocation(factory):
    invoke = factory()
    tracemalloc.start()
    try:
        result = invoke()
        _, peak = tracemalloc.get_traced_memory()
        del result
        return peak
    finally:
        tracemalloc.stop()


def compare(before_factory, after_factory, iterations, warmup):
    before_ms, after_ms = [], []
    for index in range(warmup + iterations):
        functions = [before_factory(), after_factory()]
        output = [None, None]
        elapsed = [0.0, 0.0]
        for side in ((0, 1) if index % 2 == 0 else (1, 0)):
            started = time.perf_counter_ns()
            output[side] = functions[side]()
            elapsed[side] = (time.perf_counter_ns() - started) / 1_000_000
        if not equal(*output):
            raise AssertionError("Candidate changed samples, request bytes or result events")
        if index >= warmup:
            before_ms.append(elapsed[0])
            after_ms.append(elapsed[1])
    before = statistics.median(before_ms)
    after = statistics.median(after_ms)
    change = (after / before - 1) * 100
    material = abs(before - after) >= 0.005 and abs(change) >= 5
    return {
        "before_median_ms": before,
        "after_median_ms": after,
        "before_p95_ms": percentile95(before_ms),
        "after_p95_ms": percentile95(after_ms),
        "before_peak_bytes": peak_allocation(before_factory),
        "after_peak_bytes": peak_allocation(after_factory),
        "change_percent": change,
        "equivalent": True,
        "result": ("faster" if after < before else "slower") if material else "no_material_change",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.iterations < 2 or args.warmup < 0:
        parser.error("Use at least two measured pairs and a non-negative warmup")
    reference = load_snapshot("groq_rounds_reference", args.baseline_dir / "transcriber.py")
    reference_audio = load_snapshot("groq_rounds_reference_audio", args.baseline_dir / "audio.py")
    before_pipeline = OfflinePipeline(reference, reference_audio)
    after_pipeline = OfflinePipeline(transcriber, audio)
    rows = []
    print("round stage profile before_ms after_ms change_percent equal")
    try:
        for stage, first_round in (("payload", 1), ("trim", 21), ("pipeline", 61)):
            for index, (name, samples, language) in enumerate(profiles()):
                original = samples.copy()
                if stage == "payload":
                    before_factory = lambda: lambda: reference.encode_cloud_multipart_from_recording(samples, language, True)
                    after_factory = lambda: lambda: transcriber.encode_cloud_multipart_from_recording(samples, language, True)
                elif stage == "trim":
                    before_factory = lambda: lambda: reference.trim_cloud_silence(samples)
                    after_factory = lambda: lambda: transcriber.trim_cloud_silence(samples)
                else:
                    before_factory = lambda: before_pipeline.invocation(samples, language)
                    after_factory = lambda: after_pipeline.invocation(samples, language)
                row = compare(before_factory, after_factory, args.iterations, args.warmup)
                np.testing.assert_array_equal(samples, original)
                row.update(round=first_round + index, stage=stage, profile=name,
                           sample_count=samples.size, language=language, input_unchanged=True)
                rows.append(row)
                print(f"{row['round']} {stage} {name} {row['before_median_ms']:.6f} "
                      f"{row['after_median_ms']:.6f} {row['change_percent']:+.1f} true")
    finally:
        before_pipeline.close()
        after_pipeline.close()
    report = {
        "environment": {"python": platform.python_version(), "numpy": np.__version__, "httpx": httpx.__version__,
                        "platform": platform.platform()},
        "baseline_sha256": {name: hashlib.sha256((args.baseline_dir / name).read_bytes()).hexdigest()
                            for name in ("audio.py", "transcriber.py")},
        "candidate_sha256": {name: hashlib.sha256((REPO_ROOT / "src-tauri/whisper_engine" / name).read_bytes()).hexdigest()
                             for name in ("audio.py", "transcriber.py")},
        "iterations_per_side": args.iterations, "warmup_pairs": args.warmup,
        "network": "HTTPX MockTransport only", "rounds": rows,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"comparisons={len(rows)} equivalent={sum(row['equivalent'] for row in rows)}")


if __name__ == "__main__":
    main()
