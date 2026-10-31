#!/usr/bin/env python3
"""Compile the pinned transcribe.cpp helper independently of the Tauri shell."""
from pathlib import Path
import subprocess
import sys

NATIVE_DIR = Path(__file__).resolve().parents[1] / "src-tauri" / "native-transcriber"


def build_native_transcriber():
    subprocess.run(["cargo", "build", "--locked", "--release"], cwd=NATIVE_DIR, check=True)
    name = "traflix-transcriber.exe" if sys.platform == "win32" else "traflix-transcriber"
    executable = NATIVE_DIR / "target" / "release" / name
    if not executable.is_file():
        raise FileNotFoundError(executable)
    return executable


if __name__ == "__main__":
    print(build_native_transcriber())
