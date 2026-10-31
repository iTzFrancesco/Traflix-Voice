#!/usr/bin/env python3
"""Compile the pinned transcribe.cpp helper independently of the Tauri shell."""
from pathlib import Path
import subprocess
import json
import shutil
import sys

NATIVE_DIR = Path(__file__).resolve().parents[1] / "src-tauri" / "native-transcriber"


def build_native_transcriber():
    result = subprocess.run(
        ["cargo", "build", "--locked", "--release", "--message-format=json-render-diagnostics"],
        cwd=NATIVE_DIR, check=True, stdout=subprocess.PIPE, text=True, encoding="utf-8",
    )
    runtime_dir = None
    for line in result.stdout.splitlines():
        event = json.loads(line)
        if event.get("reason") == "build-script-executed" and "traflix-transcriber" in event.get("package_id", ""):
            runtime_dir = Path(Path(event["out_dir"]).joinpath("runtime-path.txt").read_text(encoding="utf-8"))
    if runtime_dir is None:
        raise RuntimeError("Native runtime location missing from Cargo output")
    name = "traflix-transcriber.exe" if sys.platform == "win32" else "traflix-transcriber"
    executable = NATIVE_DIR / "target" / "release" / name
    if not executable.is_file():
        raise FileNotFoundError(executable)
    libraries = []
    for path in runtime_dir.iterdir():
        if path.name.endswith((".dll", ".dylib", ".so")) or ".so." in path.name:
            shutil.copy2(path, executable.parent / path.name)
            libraries.append(path.name)
    if not libraries:
        raise RuntimeError("No native runtime libraries were produced")
    (executable.parent / "native-libraries.json").write_text(json.dumps(libraries), encoding="utf-8")
    return executable


if __name__ == "__main__":
    print(build_native_transcriber())
