#!/usr/bin/env python3
"""Micro-benchmark for the sidecar's stdout JSON line serializer."""

from __future__ import annotations

import io
import json
import statistics
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src-tauri"))

from whisper_engine import ipc  # noqa: E402


VOLUME_EVENT = {"status": "volume", "value": 42}
RESULT_EVENT = {"status": "result", "text": "ciao mondo", "duration": 1.25}
ITERATIONS = 20_000


def current_serializer(data, output):
    output.write(json.dumps(data) + "\n")
    output.flush()


def candidate_serializer(data, output):
    if type(data.get("value")) is int and data.get("status") == "volume":
        output.write('{"status":"volume","value":' + str(data["value"]) + "}\n")
    else:
        output.write(json.dumps(data) + "\n")
    output.flush()


def compact_serializer(data, output):
    output.write(json.dumps(data, separators=(",", ":")) + "\n")
    output.flush()


def measure(serializer, data) -> float:
    samples = []
    original_stdout = sys.stdout
    for _ in range(7):
        output = io.StringIO()
        sys.stdout = output
        started = time.perf_counter()
        for _ in range(ITERATIONS):
            serializer(data, output)
        samples.append((time.perf_counter() - started) * 1000)
        sys.stdout = original_stdout
    return statistics.median(samples)


def main() -> None:
    # Importing the application module gives us the exact current benchmark
    # target while the local candidate keeps the comparison deterministic.
    before = measure(current_serializer, VOLUME_EVENT)
    candidate = measure(candidate_serializer, VOLUME_EVENT)
    application = measure(lambda data, _output: ipc.log(data), VOLUME_EVENT)
    before_result = measure(current_serializer, RESULT_EVENT)
    candidate_result = measure(compact_serializer, RESULT_EVENT)
    application_result = measure(lambda data, _output: ipc.log(data), RESULT_EVENT)
    print(f"iterations={ITERATIONS}")
    print(f"current_style_ms={before:.3f}")
    print(f"candidate_ms={candidate:.3f}")
    print(f"application_ms={application:.3f}")
    print(f"result_before_ms={before_result:.3f}")
    print(f"result_after_ms={candidate_result:.3f}")
    print(f"result_application_ms={application_result:.3f}")
    print(f"current_bytes={len(json.dumps(VOLUME_EVENT) + chr(10))}")
    print(f"candidate_bytes={len('{\"status\":\"volume\",\"value\":42}' + chr(10))}")


if __name__ == "__main__":
    main()
