#!/usr/bin/env python3
"""Prepare the pinned, MIT-licensed Silero VAD resource for Windows packaging."""

import hashlib
from pathlib import Path
import urllib.request

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = REPO_ROOT / "src-tauri" / "target" / "speech-vad"
RESOURCES = (
    ("silero_vad.onnx", "https://raw.githubusercontent.com/snakers4/silero-vad/v5.0/files/silero_vad.onnx",
     "6b99cbfd39246b6706f98ec13c7c50c6b299181f2474fa05cbc8046acc274396", 2313101),
    ("silero_vad.LICENSE.txt", "https://raw.githubusercontent.com/snakers4/silero-vad/v5.0/LICENSE",
     "2e63e9a38b6e8fc0c7bc37ce174caca1862870856c6daf5697cfb785e925520b", 1075),
)


def prepare_speech_model():
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for name, url, expected_hash, expected_size in RESOURCES:
        destination = MODEL_DIR / name
        if destination.is_file() and hashlib.sha256(destination.read_bytes()).hexdigest() == expected_hash:
            continue
        with urllib.request.urlopen(url, timeout=30) as response:
            content = response.read(expected_size + 1)
        if len(content) != expected_size or hashlib.sha256(content).hexdigest() != expected_hash:
            raise RuntimeError(f"Pinned speech resource verification failed: {name}")
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(destination)
    return MODEL_DIR


if __name__ == "__main__":
    print(f"Verified speech model and license: {prepare_speech_model()}")
