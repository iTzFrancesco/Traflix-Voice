#!/usr/bin/env python3
"""Compare whole-clip and production Parakeet inference on local WAV fixtures.

Both modes reuse the same recognizer and run the complete local preprocessing
and result path. Alternating measurement order reduces warm-cache bias. No
microphone, network requests, credentials, or model downloads are used.
Manifest entries contain {file, text}; WAVs must be mono PCM16 at 16 kHz.
"""

import argparse
import json
from pathlib import Path
import statistics
import sys
import time
from types import SimpleNamespace
import wave

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src-tauri"))

from benchmark_local import wer  # noqa: E402
from whisper_engine import audio as audio_module, parakeet, transcriber  # noqa: E402
from whisper_engine.constants import SAMPLE_RATE  # noqa: E402


class WholeClipRecognizer:
    """Reproduce the pre-chunking adapter using the same native sessions."""

    def __init__(self, recognizer):
        self.recognizer = recognizer

    def transcribe(self, recording, language=""):
        stream = self.recognizer.create_stream()
        stream.accept_waveform(sample_rate=SAMPLE_RATE, waveform=recording)
        self.recognizer.decode_stream(stream)
        return [SimpleNamespace(text=stream.result.text.strip())]


def load_audio(path):
    with wave.open(str(path), "rb") as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, SAMPLE_RATE):
            raise ValueError(f"Expected mono PCM16 at {SAMPLE_RATE} Hz: {path.name}")
        return np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float32) / 32768


def measure(model, audio):
    events = []
    start = time.perf_counter()
    recording = audio.copy()
    audio_module.apply_automatic_gain(recording)
    transcriber.transcribe_local(model, recording, "auto", audio.size / SAMPLE_RATE, False, events.append)
    elapsed = time.perf_counter() - start
    results = [event for event in events if event.get("status") == "result"]
    if len(results) != 1:
        raise RuntimeError(f"Expected one local result, got statuses {[event.get('status') for event in events]}")
    return elapsed, results[0]["text"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--threads", type=int)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--min-long-speedup", type=float, default=1.0)
    parser.add_argument("--max-wer-increase", type=float, default=0.0)
    args = parser.parse_args()
    if args.reps < 1 or args.warmup < 0:
        parser.error("--reps must be positive and --warmup must be non-negative")

    fixtures = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    model = parakeet.load(str(args.models_dir), lambda event: None, num_threads=args.threads)
    baseline = WholeClipRecognizer(model._recognizer)
    results = []
    failed = []
    try:
        for fixture in fixtures:
            path = Path(fixture["file"])
            if not path.is_absolute():
                path = args.manifest.parent / path
            audio = load_audio(path)
            prepared = audio.copy()
            audio_module.apply_automatic_gain(prepared)
            prepared = transcriber.pad_abrupt_clip_edges(transcriber.trim_cloud_silence(prepared))
            compacted = parakeet._compact_digital_pauses(prepared)
            chunks = parakeet._split_at_pauses(compacted)
            models = {"before": baseline, "after": model}
            for _ in range(args.warmup):
                for candidate in models.values():
                    measure(candidate, audio)
            times = {mode: [] for mode in models}
            errors = {mode: [] for mode in models}
            for repetition in range(args.reps):
                order = ("before", "after") if repetition % 2 == 0 else ("after", "before")
                for mode in order:
                    elapsed, text = measure(models[mode], audio)
                    times[mode].append(elapsed)
                    errors[mode].append(wer(text, fixture["text"]))
            before, after = (statistics.median(times[mode]) for mode in ("before", "after"))
            speedup = before / after
            before_wer, after_wer = (max(errors[mode]) for mode in ("before", "after"))
            result = {
                "clip": path.name,
                "words": len(fixture["text"].split()),
                "audio_seconds": round(audio.size / SAMPLE_RATE, 3),
                "digital_silence_removed_seconds": round((prepared.size - compacted.size) / SAMPLE_RATE, 3),
                "chunk_seconds": [round(chunk.size / SAMPLE_RATE, 3) for chunk in chunks],
                "before_seconds": round(before, 4),
                "after_seconds": round(after, 4),
                "latency_reduction_percent": round((1 - after / before) * 100, 2),
                "before_wer": round(before_wer, 6),
                "after_wer": round(after_wer, 6),
                "times": times,
            }
            results.append(result)
            print(json.dumps({key: value for key, value in result.items() if key != "times"}), flush=True)
            if after_wer > before_wer + args.max_wer_increase + 1e-9:
                failed.append(f"{path.name}: WER increased by {after_wer - before_wer:.4f}")
            if len(chunks) > 1 and speedup < args.min_long_speedup:
                failed.append(f"{path.name}: speedup {speedup:.2f}x < {args.min_long_speedup:.2f}x")
    finally:
        model.close()
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps({
            "threads": parakeet._worker_threads() if args.threads is None else args.threads,
            "reps": args.reps,
            "scope": "gain, local preprocessing, inference and result; excludes capture, UI and paste",
            "results": results,
            "failures": failed,
        }, indent=2), encoding="utf-8")
    if failed:
        raise SystemExit("\n".join(failed))


if __name__ == "__main__":
    main()
