#!/usr/bin/env python3
"""Measure native helper RSS, excluding the GUI, Python host and GPU memory."""
import argparse
import ctypes
import json
from pathlib import Path
import sys
import threading
import time
import wave
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src-tauri"))
from whisper_engine import native_parakeet as native


def rss(process):
    if sys.platform == "win32":
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in ("peak_rss", "rss", "peak_paged", "paged", "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile")]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        query = ctypes.windll.psapi.GetProcessMemoryInfo
        query.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        query.restype = wintypes.BOOL
        if not query(wintypes.HANDLE(int(process._handle)), ctypes.byref(counters), counters.cb):
            raise ctypes.WinError()
        return counters.rss
    fields = Path(f"/proc/{process.pid}/status").read_text().splitlines()
    return int(next(line for line in fields if line.startswith("VmRSS:")).split()[1]) * 1024


def swap_bytes(process):
    if sys.platform != "linux":
        return None
    fields = Path(f"/proc/{process.pid}/status").read_text().splitlines()
    return int(next(line for line in fields if line.startswith("VmSwap:")).split()[1]) * 1024


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--wav", type=Path)
    args = parser.parse_args()
    if native.helper_path() is None:
        parser.error("build the native helper first")
    if not native.verify(args.model_dir, checksum=True):
        parser.error("a verified Parakeet v3 Q8_0 GGUF is required")
    audio = np.zeros(5 * 16_000, dtype=np.float32)
    if args.wav:
        with wave.open(str(args.wav), "rb") as source:
            if (source.getnchannels(), source.getframerate(), source.getsampwidth()) != (1, 16_000, 2):
                parser.error("WAV must be mono PCM16 at 16 kHz")
            audio = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float32) / 32768
    started = time.perf_counter()
    session = native.NativeSession(native.helper_path(), args.model_dir / native.FILENAME)
    load_seconds = time.perf_counter() - started
    idle = rss(session.process)
    idle_swap = swap_bytes(session.process)
    measurements = [idle]
    accounted = [idle + (idle_swap or 0)]
    stop = threading.Event()
    def sample():
        while not stop.wait(0.02):
            try:
                resident = rss(session.process)
                measurements.append(resident)
                accounted.append(resident + (swap_bytes(session.process) or 0))
            except (OSError, StopIteration):
                return
    sampler = threading.Thread(target=sample)
    sampler.start()
    try:
        started = time.perf_counter()
        text = session.transcribe(audio)
        elapsed = time.perf_counter() - started
        after = rss(session.process)
        print(json.dumps({**session.metadata, "scope": "native helper RSS only; excludes GUI/Python and VRAM",
            "load_and_warmup_seconds": round(load_seconds, 3), "audio_seconds": round(audio.size / 16_000, 3),
            "inference_seconds": round(elapsed, 3), "nonempty_result": bool(text),
            "idle_mib": round(idle / 2**20, 1), "peak_inference_mib": round(max(measurements + [after]) / 2**20, 1),
            "after_inference_mib": round(after / 2**20, 1),
            "idle_swap_mib": None if idle_swap is None else round(idle_swap / 2**20, 1),
            "peak_rss_plus_swap_mib": None if idle_swap is None else round(max(accounted) / 2**20, 1)}, indent=2))
    finally:
        stop.set()
        sampler.join()
        session.close()


if __name__ == "__main__":
    main()
