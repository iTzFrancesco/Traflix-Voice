#!/usr/bin/env python3
"""Compare gain implementations on 20 synthetic profiles without cloud requests.

Pass a saved audio.py as --baseline and an external directory as --output-dir.
Fresh copies are prepared before each timer. Baseline and candidate alternate
execution order, and every timed pair must return identical float32 bits.
"""

from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import importlib.util
import json
import os
import platform
import statistics
import sys
import time
import tracemalloc
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src-tauri"))

from whisper_engine.audio import apply_automatic_gain  # noqa: E402
from whisper_engine.constants import (  # noqa: E402
    AUTO_GAIN_ACTIVITY_THRESHOLD,
    AUTO_GAIN_MAX,
    AUTO_GAIN_PEAK_CEILING,
    AUTO_GAIN_TARGET_RMS,
    SAMPLE_RATE,
)


@dataclass(frozen=True)
class Profile:
    name: str
    sample_count: int
    distribution: str
    layout: str = "contiguous"


PROFILES = (
    Profile("01_silence_one_sample", 1, "silence"),
    Profile("02_quiet_incomplete_frame", 319, "quiet"),
    Profile("03_invalid_incomplete_frame", 319, "invalid"),
    Profile("04_quiet_one_frame", 320, "quiet"),
    Profile("05_peak_in_incomplete_tail", 321, "tail_peak"),
    Profile("06_quiet_100ms", 1600, "quiet"),
    Profile("07_silence_250ms", 4000, "silence"),
    Profile("08_quiet_500ms", 8000, "quiet"),
    Profile("09_speech_with_pauses_1s", 16000, "pauses"),
    Profile("10_loud_1s", 16000, "loud"),
    Profile("11_outliers_and_tail_1s", 16013, "outliers"),
    Profile("12_below_activity_floor_2s", 32000, "below_floor"),
    Profile("13_sparse_invalid_2s", 32000, "invalid"),
    Profile("14_quiet_strided_3s", 48000, "quiet", "strided"),
    Profile("15_quiet_reversed_3s", 48000, "quiet", "reversed"),
    Profile("16_quiet_5s", 80000, "quiet"),
    Profile("17_quiet_15s", 240000, "quiet"),
    Profile("18_silence_30s", 480000, "silence"),
    Profile("19_mixed_amplitude_60s", 960000, "mixed"),
    Profile("20_quiet_180s", 2880000, "quiet"),
)


def _make_samples(profile: Profile, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    samples = rng.normal(0.0, 0.01, profile.sample_count).astype(np.float32)
    if profile.distribution == "silence":
        samples.fill(0.0)
        samples[::2] = np.float32(-0.0)
    elif profile.distribution == "loud":
        samples *= np.float32(30.0)
    elif profile.distribution == "below_floor":
        samples *= np.float32(0.01)
    elif profile.distribution == "pauses":
        samples[:3200] = 0.0
        samples[6400:9600] = 0.0
        samples[-1600:] = 0.0
    elif profile.distribution == "invalid":
        samples[::997] = np.nan
        samples[1::997] = np.inf
        samples[2::997] = -np.inf
    elif profile.distribution == "outliers":
        samples[103] = np.float32(0.9)
        samples[1001] = np.float32(-0.95)
        samples[-1] = np.float32(0.97)
    elif profile.distribution == "tail_peak":
        samples[:320] = np.float32(0.01)
        samples[-1] = np.float32(0.9)
    elif profile.distribution == "mixed":
        factors = (0.01, 0.5, 1.0, 3.0, 8.0, 30.0)
        for index, segment in enumerate(np.array_split(samples, len(factors))):
            segment *= np.float32(factors[index])
    return samples


def _fresh(samples: np.ndarray, layout: str) -> np.ndarray:
    if layout == "strided":
        storage = np.full(samples.size * 2, -0.123, dtype=np.float32)
        storage[::2] = samples
        return storage[::2]
    if layout == "reversed":
        return samples.copy()[::-1]
    return samples.copy()


def _load_baseline(path: Path):
    spec = importlib.util.spec_from_file_location("gain_baseline", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load baseline: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.apply_automatic_gain


def _check_pair(before: np.ndarray, after: np.ndarray) -> None:
    np.testing.assert_array_equal(before.view(np.uint32), after.view(np.uint32))
    if before.base is not None:
        np.testing.assert_array_equal(
            before.base.view(np.uint32), after.base.view(np.uint32)
        )


def _measure_pair(before_fn, after_fn, samples, layout, index):
    inputs = (_fresh(samples, layout), _fresh(samples, layout))
    functions = (before_fn, after_fn)
    timings = [0, 0]
    order = (0, 1) if index % 2 == 0 else (1, 0)
    for position in order:
        started = time.perf_counter_ns()
        result = functions[position](inputs[position])
        timings[position] = time.perf_counter_ns() - started
        if result is not inputs[position]:
            raise AssertionError("Gain did not return its original input")
    _check_pair(*inputs)
    return timings


def _peak_bytes(function, samples, layout):
    recording = _fresh(samples, layout)
    gc.collect()
    tracemalloc.start()
    try:
        function(recording)
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def _append_decisions(path: Path, results, evidence: Path):
    fields = ("ts", "phase", "decision", "why", "evidence", "result")
    existing = path.exists()
    with path.open("a", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, delimiter="\t")
        if not existing:
            writer.writerow(fields)
        for result in results:
            writer.writerow(
                (
                    datetime.now(timezone.utc).isoformat(),
                    result["name"],
                    "Keep gain math unchanged; compare the finite-input fast path",
                    "Exact float32 samples are required; timing alone is insufficient",
                    f"{evidence}#{result['name']}",
                    f"bits identical; improvement={result['improvement_percent']:.2f}%; "
                    f"delta={result['saved_median_ns']}ns; "
                    f"peak={result['before_peak_bytes']}/{result['after_peak_bytes']}B",
                )
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--decisions", type=Path)
    parser.add_argument("--repeats", type=int, default=101)
    parser.add_argument("--allocation-repeats", type=int, default=7)
    parser.add_argument("--seed", type=int, default=20261002)
    args = parser.parse_args()
    if args.repeats < 2 or args.allocation_repeats < 1:
        parser.error("Use at least two timing repeats and one allocation repeat")
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / "results.json"
    timings_path = output_dir / "timings.tsv"
    if results_path.exists() or timings_path.exists():
        parser.error("Choose a new output directory to preserve earlier measurements")
    before_fn = _load_baseline(args.baseline.resolve())
    results = []
    with timings_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(("profile", "repeat", "first", "before_ns", "after_ns"))
        for case_index, profile in enumerate(PROFILES):
            samples = _make_samples(profile, args.seed + case_index)
            for warmup in range(8):
                _measure_pair(
                    before_fn, apply_automatic_gain, samples, profile.layout, warmup
                )
            before_times, after_times = [], []
            for repeat in range(args.repeats):
                before_ns, after_ns = _measure_pair(
                    before_fn, apply_automatic_gain, samples, profile.layout, repeat
                )
                before_times.append(before_ns)
                after_times.append(after_ns)
                writer.writerow(
                    (
                        profile.name,
                        repeat,
                        "baseline" if repeat % 2 == 0 else "candidate",
                        before_ns,
                        after_ns,
                    )
                )
            before_peaks, after_peaks = [], []
            for repeat in range(args.allocation_repeats):
                order = (before_fn, apply_automatic_gain)
                if repeat % 2:
                    order = order[::-1]
                peaks = {
                    function: _peak_bytes(function, samples, profile.layout)
                    for function in order
                }
                before_peaks.append(peaks[before_fn])
                after_peaks.append(peaks[apply_automatic_gain])
            before_median = statistics.median(before_times)
            after_median = statistics.median(after_times)
            gain_output = _fresh(samples, profile.layout)
            apply_automatic_gain(gain_output)
            result = {
                "name": profile.name,
                "sample_count": profile.sample_count,
                "seconds": profile.sample_count / SAMPLE_RATE,
                "distribution": profile.distribution,
                "layout": profile.layout,
                "before_median_ns": before_median,
                "after_median_ns": after_median,
                "before_p95_ns": float(np.percentile(before_times, 95)),
                "after_p95_ns": float(np.percentile(after_times, 95)),
                "paired_improvement_median_percent": statistics.median(
                    (1.0 - after / before) * 100.0
                    for before, after in zip(before_times, after_times)
                ),
                "improvement_percent": (1.0 - after_median / before_median) * 100.0,
                "saved_median_ns": before_median - after_median,
                "before_peak_bytes": statistics.median(before_peaks),
                "after_peak_bytes": statistics.median(after_peaks),
                "before_peak_bytes_samples": before_peaks,
                "after_peak_bytes_samples": after_peaks,
                "identical_bits": True,
                "output_sha256": hashlib.sha256(gain_output.tobytes()).hexdigest(),
            }
            results.append(result)
            print(
                f"{profile.name}: {before_median / 1e6:.4f} -> "
                f"{after_median / 1e6:.4f} ms; "
                f"{result['improvement_percent']:+.2f}%; "
                f"peak {result['before_peak_bytes']} -> "
                f"{result['after_peak_bytes']} B; identical bits"
            )
    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "baseline_path": str(args.baseline.resolve()),
        "baseline_sha256": hashlib.sha256(args.baseline.read_bytes()).hexdigest(),
        "candidate_sha256": hashlib.sha256(
            (REPO_ROOT / "src-tauri/whisper_engine/audio.py").read_bytes()
        ).hexdigest(),
        "python": sys.version,
        "numpy": np.__version__,
        "platform": platform.platform(),
        "cpu_affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
        "repeats": args.repeats,
        "allocation_repeats": args.allocation_repeats,
        "seed": args.seed,
        "profile_count": len(results),
        "constants": {
            "sample_rate": SAMPLE_RATE,
            "activity_threshold": AUTO_GAIN_ACTIVITY_THRESHOLD,
            "target_rms": AUTO_GAIN_TARGET_RMS,
            "max_gain": AUTO_GAIN_MAX,
            "peak_ceiling": AUTO_GAIN_PEAK_CEILING,
        },
        "limits": [
            "Synthetic input only; no microphone, desktop runtime, or Groq requests",
            "Fresh copies are outside timers; gain alone is measured",
            "Tracemalloc measures traced allocation peaks, not total process RSS",
            "RMS still uses the original float32 squared-frame temporary",
        ],
    }
    results_path.write_text(
        json.dumps({"metadata": metadata, "results": results}, indent=2) + "\n",
        encoding="utf-8",
    )
    decisions = args.decisions or output_dir / "decisions.tsv"
    decisions.parent.mkdir(parents=True, exist_ok=True)
    _append_decisions(decisions, results, results_path)


if __name__ == "__main__":
    main()
