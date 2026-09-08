#!/usr/bin/env python3
"""Sandbox benchmark for LOCAL transcription speed.

Mirrors the conventions of scripts/benchmark_cloud_path.py (warmup +
iterations, median/p95, optional JSON results) but measures only the local
inference path: whisper.cpp (pywhispercpp) and Parakeet (sherpa-onnx).

The Groq/cloud code path is never exercised here.

Usage:
    python scripts/benchmark_local.py --backend parakeet --reps 5
    python scripts/benchmark_local.py --backend turbo --clip CLIP.wav --reps 2 \\
        --whisper-param beam_size=1 --json-out /tmp/round.json

Fixtures: 16 kHz mono WAV clips + reference transcripts in a manifest JSON
(default /tmp/bench_clips/manifest.json, entries {file, dur, text}).
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
import wave
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src-tauri"))

# The sidecar needs PortAudio only for capture; the bench feeds arrays.
sys.modules.setdefault("sounddevice", MagicMock())
sys.modules.setdefault("pywhispercpp", MagicMock())
sys.modules.setdefault("pywhispercpp.model", MagicMock())

from whisper_engine import parakeet as parakeet_backend  # noqa: E402
from whisper_engine import transcriber as transcriber_module  # noqa: E402
from whisper_engine.constants import PARAKEET_MODEL_ID  # noqa: E402

MODELS_DIR = Path("/tmp/tvmodels")
TURBO_MODEL_ID = "large-v3-turbo-q5_0"
DEFAULT_MANIFEST = Path("/tmp/bench_clips/manifest.json")

_WORD_RE = re.compile(r"[^a-zà-ÿ0-9' ]+", re.IGNORECASE)


def normalize(text: str) -> list[str]:
    text = _WORD_RE.sub(" ", text.lower()).replace("'", " ")
    return text.split()


def wer(hypothesis: str, reference: str) -> float:
    hyp, ref = normalize(hypothesis), normalize(reference)
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i in range(1, len(ref) + 1):
        cur = [i]
        for j in range(1, len(hyp) + 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ref[i - 1] != hyp[j - 1])))
        prev = cur
    return prev[len(hyp)] / len(ref)


def load_wav(path: str) -> np.ndarray:
    with wave.open(path, "rb") as w:
        n = w.getnframes()
        audio = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
    return np.ascontiguousarray(audio, dtype=np.float32)


def load_parakeet(num_threads: int | None):
    import sherpa_onnx  # noqa: F401  (checked for a clear error message)

    events: list[dict] = []
    kwargs = {} if num_threads is None else {"num_threads": num_threads}
    return parakeet_backend.load(str(MODELS_DIR), events.append, **kwargs)


def load_turbo(n_threads: int | None):
    import pywhispercpp  # noqa: F401  (real module restored below)
    from pywhispercpp.model import Model

    kwargs = {} if n_threads is None else {"n_threads": n_threads}
    return Model(
        str(MODELS_DIR / f"ggml-{TURBO_MODEL_ID}.bin"),
        print_realtime=False,
        print_progress=False,
        **kwargs,
    )


def transcribe_once(model, recording: np.ndarray, language: str, whisper_params: dict) -> tuple[str, float]:
    """Run the production local path and return (text, seconds)."""
    if isinstance(model, parakeet_backend.ParakeetRecognizer):
        start = time.perf_counter()
        segments = model.transcribe(recording, language=language)
        elapsed = time.perf_counter() - start
        return " ".join(s.text for s in segments).strip(), elapsed

    start = time.perf_counter()
    segments = model.transcribe(recording, language=language, **whisper_params)
    elapsed = time.perf_counter() - start
    return " ".join(s.text for s in segments).strip(), elapsed


def summarize(times: list[float]) -> dict:
    ordered = sorted(times)
    return {
        "n": len(times),
        "min": round(min(times), 3),
        "median": round(statistics.median(times), 3),
        "max": round(max(times), 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["parakeet", "turbo"], required=True)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--clip", action="append", default=None)
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--threads", type=int, default=None)
    parser.add_argument("--trim", action="store_true",
                        help="apply silence trimming before inference")
    parser.add_argument("--language", default="it")
    parser.add_argument("--whisper-param", action="append", default=[],
                        help="extra whisper transcribe kwarg, e.g. beam_size=1")
    parser.add_argument("--profile", action="store_true",
                        help="parakeet: split accept_waveform vs decode_stream timings")
    parser.add_argument("--json-out", default=None)
    parser.add_argument("--label", default="")
    args = parser.parse_args()

    # Restore the real pywhispercpp for the turbo backend (mocked above only
    # so that importing whisper_engine never requires PortAudio/whisper).
    if args.backend == "turbo":
        for name in [n for n in list(sys.modules) if n.startswith("pywhispercpp")]:
            del sys.modules[name]

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if args.clip:
        wanted = {Path(c).name for c in args.clip}
        manifest = [m for m in manifest if Path(m["file"]).name in wanted or m["file"] in args.clip]
    if not manifest:
        raise SystemExit("no clips selected")

    whisper_params: dict = {}
    for item in args.whisper_param:
        key, _, value = item.partition("=")
        if value == "true":
            parsed: object = True
        elif value == "false":
            parsed = False
        else:
            try:
                parsed = float(value) if "." in value else int(value)
            except ValueError:
                parsed = value
        if "." in key:
            outer, _, inner = key.partition(".")
            whisper_params.setdefault(outer, {})[inner] = parsed
        else:
            whisper_params[key] = parsed

    print(f"[{args.label or args.backend}] loading model...", flush=True)
    t0 = time.perf_counter()
    model = load_parakeet(args.threads) if args.backend == "parakeet" else load_turbo(args.threads)
    print(f"[{args.label or args.backend}] loaded in {time.perf_counter() - t0:.1f}s", flush=True)

    results = []
    for entry in manifest:
        recording = load_wav(entry["file"])
        if args.trim:
            recording = np.ascontiguousarray(
                transcriber_module.trim_cloud_silence(recording), dtype=np.float32
            )
        for _ in range(args.warmup):
            transcribe_once(model, recording, args.language, whisper_params)
        times, texts = [], []
        profile_acc = {"accept": [], "decode": []}
        for _ in range(args.reps):
            if args.profile and isinstance(model, parakeet_backend.ParakeetRecognizer):
                stream = model._recognizer.create_stream()
                s = time.perf_counter()
                stream.accept_waveform(sample_rate=16000, waveform=recording)
                profile_acc["accept"].append(time.perf_counter() - s)
                s = time.perf_counter()
                model._recognizer.decode_stream(stream)
                profile_acc["decode"].append(time.perf_counter() - s)
                text = stream.result.text.strip()
                times.append(profile_acc["accept"][-1] + profile_acc["decode"][-1])
                texts.append(text)
            else:
                text, elapsed = transcribe_once(model, recording, args.language, whisper_params)
                times.append(elapsed)
                texts.append(text)
        stats = summarize(times)
        stats["rtf"] = round(entry["dur"] / stats["median"], 2) if stats["median"] else 0.0
        stats["wer"] = round(wer(texts[-1], entry["text"]), 3)
        result = {
            "clip": Path(entry["file"]).name,
            "dur": entry["dur"],
            "times": [round(t, 3) for t in times],
            **stats,
            "text": texts[-1],
        }
        if args.profile:
            result["profile_accept"] = round(statistics.median(profile_acc["accept"]), 3)
            result["profile_decode"] = round(statistics.median(profile_acc["decode"]), 3)
        results.append(result)
        print(
            f"{result['clip']} ({entry['dur']}s): median {stats['median']}s "
            f"RTF x{stats['rtf']} WER {stats['wer']}",
            flush=True,
        )
        print(f"  -> {texts[-1][:100]}", flush=True)

    payload = {
        "label": args.label or args.backend,
        "backend": args.backend,
        "threads": args.threads,
        "trim": args.trim,
        "language": args.language,
        "whisper_params": whisper_params,
        "reps": args.reps,
        "results": results,
    }
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"wrote {args.json_out}", flush=True)


if __name__ == "__main__":
    main()
