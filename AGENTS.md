# AGENTS.md

Guidance for OpenCode when working in this repository.

## Build & Development Commands

```bash
cargo tauri dev                    # development (hot reload)
cargo tauri build                  # production build (.msi + .exe)
npm run tauri build                # equivalent using npm script

# Rust
cd src-tauri && cargo fmt --check
cd src-tauri && cargo clippy -- -D warnings
cd src-tauri && cargo test         # unit tests in lib.rs

# Python
python -m py_compile src-tauri/whisper_engine.py
python -m pytest src-tauri/test_whisper_engine.py -v

# Install dependencies
npm ci
pip install -r src-tauri/requirements.txt
```

## Architecture

Three-layer desktop app for offline/cloud voice-to-text dictation:

**Tauri/Rust** (`src-tauri/src/lib.rs`) - Desktop shell. Global hotkey via `GetAsyncKeyState` polling thread (~60Hz, no hooks). Clipboard ops via `SendInput` + `ClipboardManager` plugin. System tray (Menu: Mostra/Esci). Python sidecar management with auto-restart (exponential backoff, 1s-10s cap). Audio device enumeration via `cpal`. Atomic file writes (`.tmp` → rename). Entrypoint: `src-tauri/src/main.rs` just calls `traflix_voice_gui_lib::run()`.

**Frontend** (`src/`) - Vanilla JS, no bundler. Tabbed UI (Home/IA/Tasti/Cronologia/Sistema). Canvas waveform visualizer driven by smoothed RMS volume from Python (throttled ~0.05s). Overlay is a transparent, always-on-top, skip-taskbar widget shown when main window is *hidden* (CloseRequested → `window.hide()`, not minimize).

**Python sidecar** (`src-tauri/whisper_engine.py`) - Spawned as `shell.command("python")` with args. Uses `pywhispercpp` (whisper.cpp bindings) for local inference or `groq` for cloud transcription. `huggingface-hub` for model downloads from `ggerganov/whisper.cpp`. Models stored as `ggml-{size}.bin`.

## Hotkey Handling

Default hotkey is `XBUTTON2` (mouse forward button), click-to-toggle mode (`hold_to_speak: false`). The hotkey polling thread wakes every 16ms, reads `GetAsyncKeyState` for each VK code in the configured combination, and emits `hotkey_pressed`/`hotkey_released` Tauri events. Supports any combination of Ctrl, Alt, Shift, letter/digit/function keys, Space, and mouse buttons (XBUTTON1, XBUTTON2, MButton).

When the main window has focus, keyboard event listeners (keydown/keyup) act as local fallback for Ctrl+Alt.

`cargo test` includes tests for `str_to_vk`, `parse_hotkey`, and `AtomicPtr` hotkey config swapping.

## IPC Protocol (Rust ↔ Python)

JSON line-delimited over stdin/stdout. Rust sends commands:
- `init` - sets models_dir, compute_device, model, groq_api_key, provider; starts model preload on background thread (only for `"local"` provider)
- `transcribe` - device, model, language, provider
- `stop` - sets `is_recording = false`
- `download` - model size (downloads via hf_hub_download)
- `set_provider` - switches between `"local"` and `"cloud"`; unloads local model on cloud switch
- `quit` - unloads model, breaks stdin loop

Python responses: `listening`, `processing`, `result`, `volume`, `downloading`, `download_complete`, `error`, `ready`, `rate_limit`, `warning`, `info`.

## Data Persistence

Files in `AppData/Roaming/it.traflix.voice/`: `settings.json`, `stats.json`, `history.json` (last 50 entries), `groq_usage.json`, `models/ggml-{size}.bin`. All writes atomic (write `.json.tmp` then rename).

`AppSettings` fields: `hotkey`, `model`, `autoPaste`, `minimizeTray`, `selectedDevice`, `selectedLanguage`, `computeDevice`, `holdToSpeak`, `groqApiKey`, `provider`.

## Key Implementation Details

- **Paste flow**: `execute_paste` writes text to clipboard, 50ms delay, `SendInput` for Ctrl+V, 100ms delay, restores previous clipboard content.
- **Model download**: Runs in a daemon thread via `hf_hub_download` from `ggerganov/whisper.cpp` repo. Validates downloaded file (exists, non-empty) before reporting success.
- **Cloud support**: Provider toggle sends `set_provider` command. Groq usage tracked locally in both `groq_usage.json` (Python side) and `localStorage` (frontend). Limits: 28,800s/day, 7,200s/hour.
- **Transcription timeout**: 60s per local inference (`concurrent.futures.ThreadPoolExecutor` + `TRANSCRIPTION_TIMEOUT`).
- **Notification sounds**: `start.wav` and `stop.wav` in `src/assets/sounds/`.
- **Crate name**: `traflix_voice_gui_lib` (Windows cargo name collision avoidance, see `Cargo.toml`).
- **WebView2Loader.dll**: Copied by `build.rs` from the Cargo build output dir.
- **No bundler**: `tauri.conf.json` → `frontendDist: "../src"` serves raw HTML/CSS/JS.
- **Vanilla JS**: imported via `<script>` tags, no framework. `export-functions.js` loaded separately for export functionality.

## CI

GitHub Actions (`.github/workflows/ci.yml`): Rust lint (fmt + clippy), Python lint (py_compile), Python tests (pytest, conditional), full Tauri build on Windows. Build artifacts uploaded as `traflix-voice-windows` (`.msi` + `.exe`).

`ci-failure-issue.yml` auto-creates issues with `ci-failure` label when CI fails on push.

On CI failure, verify fixes locally with:
```bash
cd src-tauri && cargo fmt --check && cargo clippy -- -D warnings && cargo test
python -m py_compile src-tauri/whisper_engine.py && python -m pytest src-tauri/test_whisper_engine.py -v
```
