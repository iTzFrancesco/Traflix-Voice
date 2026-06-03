# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Build & Development Commands

```bash
# Development (hot reload)
cargo tauri dev

# Production build (Windows .msi + .exe)
cargo tauri build

# Rust linting (CI runs these)
cd src-tauri && cargo fmt --check
cd src-tauri && cargo clippy -- -D warnings

# Python syntax check
python -m py_compile src-tauri/whisper_engine.py

# Python tests (if test file exists)
python -m pytest src-tauri/test_whisper_engine.py -v

# Install dependencies
npm ci
pip install -r src-tauri/requirements.txt
```

## Architecture

Three-layer desktop app for offline voice-to-text dictation using Whisper:

**Tauri/Rust** (`src-tauri/src/lib.rs`) - Desktop shell: global hotkey registration, clipboard ops, system tray, Python sidecar process management with auto-restart (exponential backoff), audio device enumeration (cpal), settings/stats/history persistence with atomic writes.

**Frontend** (`src/main.js`, `src/index.html`, `src/overlay.html`) - Vanilla JS, no bundler. Tabbed UI (Home/IA/Tasti/Cronologia/Sistema). Canvas waveform visualizer driven by volume. Overlay is a transparent always-on-top widget shown when main window minimized.

**Python sidecar** (`src-tauri/whisper_engine.py`) - Spawned as child process. Uses pywhispercpp (bindings for whisper.cpp) for inference. Audio capture via sounddevice. Pre-loads Small model at startup.

## IPC Protocol (Rust <-> Python)

JSON line-delimited over stdin/stdout. Rust sends commands (`init`, `transcribe`, `stop`, `download`, `set_device`, `check_gpu`, `quit`). Python responds with status events (`listening`, `processing`, `result`, `volume`, `downloading`, `download_complete`, `error`, `gpu_info`).

Frontend communicates with Python through the Rust `send_to_python` Tauri command. Python output arrives as `python_output` events.

## Hotkey Handling

Default hotkey is Ctrl+Alt (hold-to-speak). Since `tauri-plugin-global-shortcut` can't bind Ctrl+Alt alone, a separate `rdev` keyboard listener thread tracks Ctrl and Alt press/release independently, emitting `hotkey_pressed`/`hotkey_released` events with deduplication. Other hotkeys (e.g. Ctrl+Space) use standard global shortcut registration.

## Data Persistence

Files in `AppData/Roaming/it.traflix.voice/`: `settings.json`, `stats.json`, `history.json` (last 50 entries), `models/ggml-{size}.bin`. All writes are atomic (write `.tmp` then rename).

## Key Implementation Details

- **Paste flow**: `execute_paste` writes to clipboard then simulates Ctrl+V via `rdev::simulate` with 50ms delay for OS clipboard sync.
- **Volume**: RMS computed in Python audio callback, throttled to ~20fps, drives waveform amplitude in both main UI and overlay.
- **Model preloading**: Background thread loads Small model at startup for zero cold-start latency.
- **Sidecar recovery**: Python process auto-restarts with exponential backoff (1s-10s cap), emits `python_restarted` event.
- **Transcription timeout**: 60-second limit per inference.
- **Crate name**: Rust lib is `traflix_voice_gui_lib` (required for Windows cargo name collision avoidance).

## CI

GitHub Actions (`.github/workflows/ci.yml`): Rust lint (fmt + clippy), Python lint (py_compile), Python tests (pytest, conditional), full Tauri build on Windows. Build artifacts uploaded as `traflix-voice-windows`.
