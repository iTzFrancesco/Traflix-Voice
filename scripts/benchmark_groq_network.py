#!/usr/bin/env python3
"""Compare live Groq network variants using the desktop audio preparation path.

Read credentials only from GROQ_API_KEY. Never print or save credentials,
headers, response bodies, reference text, or transcripts. Input WAVs must be
mono PCM16 at 16 kHz. JSON evidence belongs outside the repository.

The baseline uses the production HTTP client, gain, trim, and multipart encoder.
Capture, the 220 ms stop tail, Rust, React, and clipboard insertion are excluded.
Trace timings describe client transport operations, not isolated inference or
physical upload times. Every call can consume API quota and incur provider fees.
The optional comparisons require h2 for HTTP/2 and soundfile for FLAC.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import platform
import random
import re
import statistics
import sys
import time
import wave
from pathlib import Path

import httpx
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src-tauri"))

from whisper_engine import audio, transcriber  # noqa: E402
from whisper_engine.constants import GROQ_TRANSCRIPTION_URL, SAMPLE_RATE  # noqa: E402

CASES = ("baseline", "cold", "http2", "auto", "flac")
TRACE_OPERATIONS = {
    "connection.connect_tcp": "connect_ms",
    "connection.start_tls": "tls_ms",
    **{
        f"{protocol}.{operation}": metric
        for protocol in ("http11", "http2")
        for operation, metric in (
            ("send_request_body", "body_send_ms"),
            ("receive_response_headers", "response_wait_ms"),
            ("receive_response_body", "body_read_ms"),
        )
    },
}


def load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, SAMPLE_RATE):
            raise ValueError("Input must be mono PCM16 WAV at 16 kHz")
        recording = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
    if not recording.size:
        raise ValueError("Input audio is empty")
    return recording.astype(np.float32) / 32768.0


def word_error_rate(reference: str, transcript: str) -> float:
    expected = re.findall(r"\w+", reference.casefold())
    actual = re.findall(r"\w+", transcript.casefold())
    if not expected:
        raise ValueError("Reference text must contain words")
    previous = list(range(len(actual) + 1))
    for index, word in enumerate(expected, 1):
        current = [index]
        for column, other in enumerate(actual, 1):
            current.append(min(current[-1] + 1, previous[column] + 1,
                               previous[column - 1] + (word != other)))
        previous = current
    return previous[-1] / len(expected)


def create_client(api_key: str, case: str) -> httpx.Client:
    if case not in {"cold", "http2"}:
        return transcriber.create_groq_client(api_key)
    client = httpx.Client(
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={transcriber.GROQ_MULTIPART_BOUNDARY}",
        },
        timeout=httpx.Timeout(30.0, connect=10.0, read=25.0, pool=5.0),
        limits=httpx.Limits(max_connections=1, max_keepalive_connections=1,
                            keepalive_expiry=0.0 if case == "cold" else 60.0),
        http2=case == "http2",
    )
    client.headers.pop("Connection", None)
    client.headers.pop("Accept-Encoding", None)
    client.cookies.extract_cookies = transcriber._ignore_response_cookies
    return client


def encode_payload(recording: np.ndarray, language: str | None, case: str) -> bytes:
    if case != "flac":
        return transcriber.encode_cloud_multipart_from_recording(recording, language, True)
    import soundfile

    pcm = transcriber._encode_pcm16(recording, True)
    buffer = io.BytesIO()
    soundfile.write(buffer, pcm, SAMPLE_RATE, format="FLAC", subtype="PCM_16")
    prefix = transcriber._cloud_multipart_prefix(language).replace(
        b'filename="audio.wav"', b'filename="audio.flac"'
    ).replace(b"Content-Type: audio/wav", b"Content-Type: audio/flac")
    return b"".join((prefix, buffer.getbuffer(), transcriber._MULTIPART_SUFFIX))


def measure(client: httpx.Client, samples: np.ndarray, language: str,
            case: str, reference: str | None = None) -> dict:
    recording = samples.copy()
    row = {"success": False, "input_audio_seconds": samples.size / SAMPLE_RATE}
    starts = {}

    def trace(name, _info):
        operation, _, event = name.rpartition(".")
        metric = TRACE_OPERATIONS.get(operation)
        if metric is None:
            return
        if event == "started":
            starts[operation] = time.perf_counter()
        elif event == "complete" and operation in starts:
            row[metric] = row.get(metric, 0.0) + (time.perf_counter() - starts.pop(operation)) * 1000

    started = time.perf_counter()
    response = None
    try:
        audio.apply_automatic_gain(recording)
        recording = transcriber.trim_cloud_silence(recording)
        if not recording.size:
            row["error_type"] = "SilentInput"
            return row
        cloud_language = None if case == "auto" else transcriber._normalize_cloud_language(language)
        payload = encode_payload(recording, cloud_language, case)
        row.update(payload_bytes=len(payload), uploaded_audio_seconds=recording.size / SAMPLE_RATE)
        request = httpx.Request("POST", GROQ_TRANSCRIPTION_URL, headers=client.headers,
                                content=payload, extensions={"trace": trace})
        prepared_at = time.perf_counter()
        row["prepare_ms"] = (prepared_at - started) * 1000
        response = client.send(request, stream=False)
        row.update(http_status=response.status_code, http_version=response.http_version,
                   http_ms=(time.perf_counter() - prepared_at) * 1000)
        if response.status_code != 200:
            row["error_type"] = "HTTPStatusError"
            return row
        transcript = response.content.decode("utf-8", errors="replace").strip()
        row.update(success=True, transcript_characters=len(transcript))
        if reference is not None:
            row["word_error_rate"] = word_error_rate(reference, transcript)
        for metric in set(TRACE_OPERATIONS.values()):
            row.setdefault(metric, 0.0)
        row["new_connection"] = row["connect_ms"] > 0
    except Exception as error:
        # Exception messages and trace info may contain credentials or bodies.
        row["error_type"] = type(error).__name__
        row["success"] = False
    finally:
        row["total_ms"] = (time.perf_counter() - started) * 1000
        if response is not None:
            response.close()
    return row


def summarize(rows: list[dict]) -> dict:
    successes = [row for row in rows if row["success"] and not row["warmup"]]
    summary = {"samples": len(successes), "failures": sum(not row["success"] for row in rows)}
    if not successes:
        return summary
    for metric in ("total_ms", "prepare_ms", "http_ms", "connect_ms", "tls_ms",
                   "body_send_ms", "response_wait_ms", "body_read_ms", "payload_bytes",
                   "word_error_rate"):
        values = [row[metric] for row in successes if metric in row]
        if values:
            summary[metric] = {"median": statistics.median(values),
                               "p95": sorted(values)[math.ceil(len(values) * 0.95) - 1],
                               "min": min(values), "max": max(values)}
    summary["new_connections"] = sum(row["new_connection"] for row in successes)
    summary["http_versions"] = sorted({row["http_version"] for row in successes})
    return summary


def paired_savings(rows: list[dict], case: str) -> dict:
    reference = {row["round"]: row["total_ms"] for row in rows
                 if row["case"] == "baseline" and row["success"] and not row["warmup"]}
    differences = [reference[row["round"]] - row["total_ms"] for row in rows
                   if row["case"] == case and row["success"] and not row["warmup"]
                   and row["round"] in reference]
    return {"pairs": len(differences), "faster_pairs": sum(value > 0 for value in differences),
            "median_saving_ms": statistics.median(differences) if differences else None}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wav", type=Path, nargs="+", required=True)
    parser.add_argument("--language", default="it")
    parser.add_argument("--cases", choices=CASES, nargs="+", default=list(CASES))
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=8)
    parser.add_argument("--interval", type=float, default=3.2,
                        help="Minimum seconds between requests, including warmups")
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--references", type=Path,
                        help="Optional JSON array of {name: WAV stem, text: reference}")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.iterations < 1 or args.warmup < 0 or not math.isfinite(args.interval) or args.interval < 0:
        parser.error("Use positive iterations, non-negative warmup and a finite non-negative interval")
    if len(args.cases) != len(set(args.cases)):
        parser.error("Cases must be unique")
    if args.output and args.output.resolve().is_relative_to(REPO_ROOT):
        parser.error("Save numeric benchmark evidence outside the repository")
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        parser.error("Set GROQ_API_KEY in the process environment")

    references = {}
    try:
        if args.references:
            references = {entry["name"]: entry["text"]
                          for entry in json.loads(args.references.read_text(encoding="utf-8-sig"))}
            for reference in references.values():
                word_error_rate(reference, reference)
        recordings = [load_wav(path) for path in args.wav]
        if "flac" in args.cases:
            import soundfile  # noqa: F401
        if "http2" in args.cases:
            import h2.connection  # noqa: F401
    except Exception as error:
        parser.error(f"Input validation failed: {type(error).__name__}")

    clients = {}
    setup_ms = {}
    rows = []
    failed = False
    try:
        for case in args.cases:
            started = time.perf_counter()
            clients[case] = create_client(api_key, case)
            setup_ms[case] = (time.perf_counter() - started) * 1000
        rng = random.Random(args.seed)
        last_request_at = -math.inf
        for round_index in range(args.warmup + args.iterations):
            for clip_index, samples in enumerate(recordings):
                order = list(args.cases)
                rng.shuffle(order)
                for case in order:
                    wait = args.interval - (time.perf_counter() - last_request_at)
                    if wait > 0:
                        time.sleep(wait)
                    last_request_at = time.perf_counter()
                    row = measure(clients[case], samples, args.language, case,
                                  references.get(args.wav[clip_index].stem))
                    row.update(case=case, clip=f"clip_{clip_index + 1}", round=round_index,
                               warmup=round_index < args.warmup)
                    rows.append(row)
                    print(f"{row['clip']} round={round_index} case={case} "
                          f"success={row['success']} total_ms={row['total_ms']:.1f} "
                          f"connect_ms={row.get('connect_ms', 0):.1f} "
                          f"tls_ms={row.get('tls_ms', 0):.1f}", flush=True)
                    if not row["success"]:
                        failed = True
                        break
                if failed:
                    break
            if failed:
                break
    except (Exception, KeyboardInterrupt) as error:
        failed = True
        print(f"Benchmark stopped: {type(error).__name__}", flush=True)
    finally:
        for client in clients.values():
            client.close()

    summaries = {}
    comparisons = {}
    for index in range(len(recordings)):
        clip = f"clip_{index + 1}"
        clip_rows = [row for row in rows if row["clip"] == clip]
        summaries[clip] = {case: summarize([row for row in clip_rows if row["case"] == case])
                           for case in args.cases}
        comparisons[clip] = {case: paired_savings(clip_rows, case)
                             for case in args.cases if case != "baseline"}
    report = {
        "environment": {"platform": platform.platform(), "python": platform.python_version(),
                        "numpy": np.__version__, "httpx": httpx.__version__},
        "scope": "gain, production trim and payload, HTTP; excludes capture, tail, UI and paste",
        "inference_isolated": False, "seed": args.seed, "interval_seconds": args.interval,
        "iterations": args.iterations, "warmup_rounds": args.warmup,
        "client_setup_ms": setup_ms, "completed": not failed,
        "request_count": len(rows),
        "submitted_audio_seconds": sum(row.get("uploaded_audio_seconds", 0) for row in rows),
        "summaries": summaries, "paired_savings": comparisons, "rows": rows,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"completed={not failed} request_count={len(rows)}")
    print("clip case samples median_ms p95_ms paired_saving_ms faster_pairs")
    for clip, cases in summaries.items():
        for case, summary in cases.items():
            if not summary["samples"]:
                print(f"{clip} {case} samples=0 failures={summary['failures']}")
                continue
            paired = comparisons[clip].get(case, {})
            saving = paired.get("median_saving_ms")
            saving_text = f"{saving:.1f}" if saving is not None else "n/a"
            print(f"{clip} {case} {summary['samples']} "
                  f"{summary['total_ms']['median']:.1f} {summary['total_ms']['p95']:.1f} "
                  f"{saving_text} {paired.get('faster_pairs', 'n/a')}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
