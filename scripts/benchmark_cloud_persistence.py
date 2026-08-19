"""Compare warm usage-cache writes with a disk-reload on every cloud result."""

import argparse
import statistics
import sys
import tempfile
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src-tauri"))

from whisper_engine import groq_tracker


def measure(models_dir, iterations, cold):
    groq_tracker._USAGE_CACHE.clear()
    durations = []
    for _ in range(iterations):
        if cold:
            # Pre-cache implementation equivalent: reload the persisted JSON
            # before every result instead of retaining the process snapshot.
            groq_tracker._USAGE_CACHE.clear()
        started = time.perf_counter_ns()
        groq_tracker.record_groq_usage(models_dir, duration_seconds=0.1)
        durations.append((time.perf_counter_ns() - started) / 1_000_000)
    return durations


def summarize(values):
    return {
        "median": statistics.median(values),
        "p95": sorted(values)[max(0, int(len(values) * 0.95) - 1)],
        "mean": statistics.mean(values),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=80)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as temp_dir:
        models_dir = str(Path(temp_dir) / "models")
        groq_tracker.record_groq_usage(models_dir, duration_seconds=0.1)
        for _ in range(3):
            measure(models_dir, args.iterations, cold=False)
            measure(models_dir, args.iterations, cold=True)
        warm = summarize(measure(models_dir, args.iterations, cold=False))
        cold = summarize(measure(models_dir, args.iterations, cold=True))

    reduction = (cold["median"] - warm["median"]) / cold["median"] * 100
    print(f"iterations={args.iterations}")
    print(
        "warm_cache_ms: "
        f"median={warm['median']:.4f} p95={warm['p95']:.4f} mean={warm['mean']:.4f}"
    )
    print(
        "reload_each_result_ms: "
        f"median={cold['median']:.4f} p95={cold['p95']:.4f} mean={cold['mean']:.4f}"
    )
    print(f"median_reduction_pct={reduction:.1f}")


if __name__ == "__main__":
    main()
