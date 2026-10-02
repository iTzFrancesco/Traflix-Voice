#!/usr/bin/env python3
"""Opt-in Groq quality/latency probes; credentials come only from GROQ_API_KEY.

The manifest is a JSON list of {name, path, text, rate} synthetic fixtures.
Reports contain numerical evidence only, never audio, text, headers or keys.
Use invented speech, keep recordings/reports outside the repository, and pace
requests to respect the account's quotas. Stop on the first failed request.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics
import time
from pathlib import Path

import httpx

from benchmark_groq_network import REPO_ROOT, audio, load_wav, transcriber, word_error_rate
from whisper_engine.constants import GROQ_TRANSCRIPTION_URL, SAMPLE_RATE

CASES = ("text", "verbose", "large", "prompt")


def probe_payload(recording, case, prompt=""):
    prefix = transcriber._cloud_multipart_prefix("it")
    if case != "text":
        prefix = prefix.replace(b"\r\n\r\ntext\r\n", b"\r\n\r\nverbose_json\r\n", 1)
    if case == "large":
        prefix = prefix.replace(b"whisper-large-v3-turbo\r\n", b"whisper-large-v3\r\n", 1)
    if case == "prompt":
        prompt_field = (b"--" + transcriber._MULTIPART_BOUNDARY + b"\r\n"
                        b'Content-Disposition: form-data; name="prompt"\r\n\r\n'
                        + prompt.encode("utf-8") + b"\r\n")
        prefix = prefix.replace(transcriber._FILE_FIELD_PREFIX,
                                prompt_field + transcriber._FILE_FIELD_PREFIX)
    pcm = transcriber._encode_pcm16(recording, True)
    return b"".join((prefix, transcriber._encode_wav_header(pcm.nbytes),
                     memoryview(pcm), transcriber._MULTIPART_SUFFIX))


def measure(client, samples, reference, case, prompt=""):
    started = time.perf_counter()
    response = None
    row = {"success": False, "audio_seconds": samples.size / SAMPLE_RATE}
    try:
        recording = samples.copy()
        audio.apply_automatic_gain(recording)
        recording = transcriber.trim_cloud_silence(recording)
        request = httpx.Request("POST", GROQ_TRANSCRIPTION_URL, headers=client.headers,
                                content=probe_payload(recording, case, prompt))
        response = client.send(request, stream=False)
        row["http_status"] = response.status_code
        if response.status_code != 200:
            row["error_type"] = "HTTPStatusError"
            return row
        if case == "text":
            text = response.content.decode("utf-8").strip()
        else:
            data = response.json()
            text = data["text"].strip()
            for key in ("avg_logprob", "compression_ratio", "no_speech_prob"):
                values = [s[key] for s in data.get("segments", [])
                          if isinstance(s.get(key), (int, float)) and math.isfinite(s[key])]
                if values:
                    row[key + "_min"] = min(values)
                    row[key + "_max"] = max(values)
        row.update(success=True, word_error_rate=word_error_rate(reference, text),
                   transcript_characters=len(text))
    except Exception as error:
        row["error_type"] = type(error).__name__
    finally:
        row["total_ms"] = (time.perf_counter() - started) * 1000
        if response is not None:
            response.close()
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", nargs="+", choices=CASES, default=["text", "verbose"])
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--interval", type=float, default=3.5)
    parser.add_argument("--prompt", default="")
    args = parser.parse_args()
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        parser.error("GROQ_API_KEY is required; .env files are never loaded")
    if args.output.resolve().is_relative_to(REPO_ROOT):
        parser.error("Keep reports outside the repository")
    if args.rounds < 1 or args.interval < 0 or not math.isfinite(args.interval):
        parser.error("Use positive rounds and a finite nonnegative interval")
    if len(args.cases) != len(set(args.cases)):
        parser.error("Cases must be unique")
    if len(args.prompt.encode("utf-8")) > 224 or "\r" in args.prompt or "\n" in args.prompt:
        parser.error("Use a single-line prompt of at most 224 UTF-8 bytes")
    if "prompt" in args.cases and not args.prompt:
        parser.error("The prompt comparison needs --prompt")
    fixtures = json.loads(args.fixtures.read_text(encoding="utf-8-sig"))
    samples = {f["name"]: load_wav(Path(f["path"])) for f in fixtures}
    report = {"cases": args.cases, "rounds": args.rounds, "rows": []}
    rng = random.Random(1729)
    last_start = 0.0
    failed = False
    try:
        with transcriber.create_groq_client(key) as client:
            for round_index in range(args.rounds):
                jobs = [(f, case) for f in fixtures for case in args.cases]
                rng.shuffle(jobs)
                for fixture, case in jobs:
                    time.sleep(max(0.0, args.interval - (time.monotonic() - last_start)))
                    last_start = time.monotonic()
                    row = measure(client, samples[fixture["name"]], fixture["text"], case, args.prompt)
                    row.update(name=fixture["name"], rate=fixture["rate"], case=case, round=round_index)
                    report["rows"].append(row)
                    if not row["success"]:
                        failed = True
                        break
                if failed:
                    break
    except KeyboardInterrupt:
        report["interrupted"] = True
        failed = True
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    for case in args.cases:
        rows = [r for r in report["rows"] if r["case"] == case and r["success"]]
        if rows:
            print(json.dumps({"case": case, "samples": len(rows),
                              "median_ms": round(statistics.median(r["total_ms"] for r in rows), 1),
                              "mean_wer": round(statistics.mean(r["word_error_rate"] for r in rows), 4)}))
    if failed:
        print("Probe stopped; inspect numerical report for failure type.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
