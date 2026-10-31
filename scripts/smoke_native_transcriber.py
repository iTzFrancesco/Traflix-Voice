#!/usr/bin/env python3
"""Exercise a relocated packaged helper with pinned public model/audio artifacts."""
import argparse
from array import array
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import wave

REV = "7045d1c0fe7cee37747b2792977421d435e75fca"
MODEL = "parakeet-tdt-0.6b-v3-Q8_0.gguf"
MODEL_REV = "85ac09ea12fc4b1112fa76810059364bc6adc9de"
MODEL_HASH = "5859f77944efcd8eafa23a6350731960b2b55b2203df51f319665c807d802cc7"


def fetch(url, destination, expected=None):
    digest = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=90) as response, destination.open("wb") as target:
        for block in iter(lambda: response.read(1024 * 1024), b""):
            digest.update(block)
            target.write(block)
    if expected and digest.hexdigest() != expected:
        raise RuntimeError("Artifact checksum mismatch")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--model", type=Path)
    args = parser.parse_args()
    args.executable = args.executable.resolve()
    with tempfile.TemporaryDirectory(prefix="traflix native ü ") as directory:
        root = Path(directory)
        runtime = root / "runtime"
        runtime.mkdir()
        for path in args.executable.parent.iterdir():
            if path == args.executable or path.name.endswith((".dll", ".so", ".dylib")) or ".so." in path.name:
                shutil.copy2(path, runtime / path.name)
        model = args.model.resolve() if args.model else root / MODEL
        if args.model is None:
            fetch(f"https://huggingface.co/handy-computer/parakeet-tdt-0.6b-v3-gguf/resolve/{MODEL_REV}/{MODEL}", model, MODEL_HASH)
        wav = root / "public.wav"
        fetch(f"https://raw.githubusercontent.com/anomalyco/transcribe.cpp/{REV}/samples/jfk.wav", wav, "59dfb9a4acb36fe2a2affc14bacbee2920ff435cb13cc314a08c13f66ba7860e")
        with wave.open(str(wav), "rb") as source:
            assert (source.getnchannels(), source.getsampwidth(), source.getframerate()) == (1, 2, 16000)
            pcm = array("h", source.readframes(source.getnframes()))
        if sys.byteorder != "little":
            pcm.byteswap()
        samples = array("f", (value / 32768 for value in pcm))
        if sys.byteorder != "little":
            samples.byteswap()
        header = lambda value: (json.dumps(value) + "\n").encode("utf-8")
        environment = os.environ.copy()
        sdk = environment.get("VULKAN_SDK", "")
        if sdk:
            environment["PATH"] = os.pathsep.join(
                part for part in environment.get("PATH", "").split(os.pathsep)
                if not part.lower().replace("\\", "/").startswith(sdk.lower().replace("\\", "/"))
            )
        for cpu_only in (False, True):
            payload = header({"command": "init", "model": str(model), "cpu_only": cpu_only})
            payload += header({"command": "transcribe", "samples": len(samples)}) + samples.tobytes()
            payload += header({"command": "quit"})
            result = subprocess.run([str(runtime / args.executable.name)], input=payload,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=root,
                                    env=environment, timeout=240, check=True)
            replies = [json.loads(line) for line in result.stdout.splitlines()]
            assert [r["status"] for r in replies] == ["ready", "result", "bye"], "Native protocol failed"
            assert "country" in replies[1]["text"].lower(), "Public speech fixture was not recognized"
            print(json.dumps({"native_smoke": "passed", "backend": replies[0]["backend"],
                              "cpu_only": cpu_only, "relocated_runtime": True,
                              "unicode_path": True, "speech_result": True}))


if __name__ == "__main__":
    main()
