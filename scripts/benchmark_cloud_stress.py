#!/usr/bin/env python3
"""Stress the cloud transcription seam with a deterministic fake transport."""

from __future__ import annotations

import argparse
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src-tauri"))

from whisper_engine import transcriber  # noqa: E402
from whisper_engine.constants import SAMPLE_RATE  # noqa: E402


class _FakeClient:
    headers = {"Authorization": "Bearer benchmark"}

    def __init__(self):
        self._lock = threading.Lock()
        self.requests = 0

    def send(self, request, stream=False):
        with self._lock:
            self.requests += 1
        return httpx.Response(200, content=b"stress ok\n", request=request)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    client = _FakeClient()
    original_acquire_client = transcriber.acquire_groq_client
    transcriber.acquire_groq_client = lambda _api_key: client
    recording = np.full(SAMPLE_RATE, 0.03, dtype=np.float32)

    def run_once(_index: int) -> tuple[float, list[dict]]:
        events: list[dict] = []
        started = time.perf_counter_ns()
        transcriber.transcribe_cloud(
            recording,
            "it",
            1.0,
            "benchmark-key",
            False,
            events.append,
            None,
        )
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
        return elapsed_ms, events

    try:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            results = list(executor.map(run_once, range(args.iterations)))
    finally:
        transcriber.acquire_groq_client = original_acquire_client

    samples = [elapsed for elapsed, _events in results]
    events = [event for _elapsed, event_list in results for event in event_list]
    result_count = sum(event.get("status") == "result" for event in events)
    failure_count = sum(event.get("status") in {"error", "rate_limit"} for event in events)

    if result_count != args.iterations or failure_count:
        raise SystemExit(
            f"stress failed: results={result_count} failures={failure_count}"
        )

    print(f"iterations={args.iterations}")
    print(f"workers={args.workers}")
    print(f"requests={client.requests}")
    print(f"results={result_count}")
    print(f"failures={failure_count}")
    print(f"median_ms={statistics.median(samples):.3f}")
    print(f"p95_ms={statistics.quantiles(samples, n=20)[18]:.3f}")


if __name__ == "__main__":
    main()
