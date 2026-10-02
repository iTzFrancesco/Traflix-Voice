#!/usr/bin/env python3
"""Build the self-contained Windows Python runtime bundled in desktop MSIs."""

from pathlib import Path
import hashlib
import subprocess
import sys
import venv
from prepare_speech_model import prepare_speech_model


REPO_ROOT = Path(__file__).resolve().parents[1]
TAURI_DIR = REPO_ROOT / "src-tauri"
OUTPUT_DIR = TAURI_DIR / "python-backend"
WORK_DIR = TAURI_DIR / "target" / "python-backend-build"
RUNTIME_REQUIREMENTS = TAURI_DIR / "requirements.txt"
BUILD_REQUIREMENTS = TAURI_DIR / "requirements-build.txt"


def build_python() -> Path:
    fingerprint = hashlib.sha256(
        sys.version.encode("utf-8")
        + RUNTIME_REQUIREMENTS.read_bytes()
        + BUILD_REQUIREMENTS.read_bytes()
    ).hexdigest()[:16]
    env_dir = TAURI_DIR / "target" / f"python-backend-env-{fingerprint}"
    python_exe = env_dir / "Scripts" / "python.exe"
    ready_marker = env_dir / ".requirements-installed"

    if not python_exe.exists():
        venv.create(env_dir, with_pip=True)

    if not ready_marker.exists():
        subprocess.run(
            [
                str(python_exe),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--requirement",
                str(RUNTIME_REQUIREMENTS),
                "--requirement",
                str(BUILD_REQUIREMENTS),
            ],
            check=True,
        )
        ready_marker.write_text(fingerprint, encoding="ascii")

    return python_exe


def main() -> int:
    if sys.platform != "win32":
        print("Skipping bundled Python backend: MSI packaging is Windows-only.")
        return 0

    isolated_python = build_python()
    speech_model_dir = prepare_speech_model()
    entry_point = TAURI_DIR / "whisper_engine.py"
    command = [
        str(isolated_python),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--console",
        "--name",
        "whisper_engine",
        "--distpath",
        str(OUTPUT_DIR),
        "--workpath",
        str(WORK_DIR),
        "--specpath",
        str(WORK_DIR),
        "--paths",
        str(TAURI_DIR),
    ]

    command.extend(("--hidden-import", "sherpa_onnx"))
    command.extend(("--collect-binaries", "sherpa_onnx"))
    command.extend(("--add-data", f"{speech_model_dir};speech-vad"))

    command.append(str(entry_point))
    subprocess.run(command, cwd=TAURI_DIR, check=True)

    executable = OUTPUT_DIR / "whisper_engine" / "whisper_engine.exe"
    if not executable.is_file():
        raise FileNotFoundError(f"PyInstaller did not produce {executable}")

    print(f"Bundled Python sidecar: {executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
