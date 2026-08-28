# AGENTS.md

Guidance for contributors and coding agents working in the Traflix Voice repository.

## Project overview

Traflix Voice is a Tauri 2 desktop application for voice dictation. It combines:

- a Rust/Tauri desktop shell for global hotkeys, clipboard integration, the system tray, persistence, and process supervision;
- a React and TypeScript frontend built with Vite;
- a Python sidecar for audio capture, Whisper model management, local inference, and optional Groq transcription.

Windows is the primary supported platform. Do not assume that platform-specific behavior works unchanged on macOS or Linux.

## Development commands

Install dependencies:

```powershell
npm ci
python -m pip install -r src-tauri/requirements.txt
```

Run the development application:

```powershell
npm run tauri dev
```

Build the frontend:

```powershell
npm run build
```

Build the Windows installer:

```powershell
npm run tauri build
```

## Validation commands

Run Rust formatting, linting, and tests from `src-tauri`:

```powershell
cd src-tauri
cargo fmt --check
cargo clippy -- -D warnings
cargo test
cd ..
```

Run Python validation from the repository root:

```powershell
python -m py_compile src-tauri/whisper_engine.py
python -m pytest src-tauri/test_whisper_engine.py -v
```

When changing timing-sensitive behavior, also perform a manual runtime check with the desktop application. Static tests do not fully cover audio capture, global hotkeys, clipboard paste, overlay behavior, or model loading.

## Architecture

### Tauri and Rust

The Rust layer owns the application lifecycle, global hotkey polling, clipboard operations, system-tray behavior, settings and statistics persistence, and Python sidecar supervision. The sidecar is restarted with bounded backoff after an unexpected exit.

### React frontend

The frontend is under `src/`. `App.tsx` coordinates application state, while the tab components provide the home, AI, hotkey, history, and system views. `overlay.tsx` implements the transparent always-on-top status widget.

### Python sidecar

`src-tauri/whisper_engine.py` is the sidecar entry point. The `src-tauri/whisper_engine/` package handles audio capture, local Whisper inference, model downloads, Groq requests, usage accounting, and line-delimited JSON IPC.

## Hotkeys and recording

The default hotkey is `XBUTTON2` (the forward mouse button) in click-to-toggle mode. The implementation also supports configurable combinations of modifier keys, letters, digits, function keys, Space, and supported mouse buttons.

When the main window has focus, keyboard listeners provide a local fallback for supported shortcuts. Any change to hotkey handling must be checked both with the main window focused and while another application is active.

## IPC contract

Rust sends line-delimited JSON commands to Python. Important commands include:

- `init` to configure models, compute device, provider, and the optional Groq key;
- `transcribe` to record and transcribe audio;
- `stop` to stop the active recording;
- `download` to download a local Whisper model;
- `set_provider` to switch between local and cloud transcription;
- `set_groq_api_key` to update the optional cloud credential;
- `quit` to shut down the sidecar cleanly.

Python reports status through JSON events such as `listening`, `processing`, `result`, `volume`, `downloading`, `download_complete`, `ready`, `rate_limit`, `warning`, and `error`.

Preserve this contract when changing either side of the boundary. Add or update focused tests for new commands and status payloads.

## Data and credential handling

- Normal application use does not require a `.env` file.
- `.env`, `.env.*`, and `*.env` files must never be committed.
- Never place API keys, tokens, passwords, private keys, or real user data in source files, tests, documentation, screenshots, or logs.
- The optional Groq API key is entered in the application settings and passed to the sidecar at runtime. Do not print it or include it in error messages.
- Application data belongs in the OS application-data directory, not in the repository.
- Keep generated builds, downloaded models, caches, logs, and user recordings out of commits.

The optional live Groq benchmark may read `GROQ_API_KEY` from the process environment. It must not load `.env` files or print credentials.

## CI and releases

- CI runs Rust formatting, Clippy, Rust tests, Python checks, Python tests, and a Windows MSI build for pushes and pull requests targeting `main`.
- The release workflow runs for tags matching `v*` and publishes the Windows MSI with generated release notes.
- Do not change release behavior, signing configuration, or updater settings without verifying the resulting artifact and its security implications.

## Change guidelines

- Keep changes focused and preserve existing IPC, settings, and persistence contracts.
- Prefer small, testable changes over broad rewrites.
- Use English for new public documentation and contributor guidance.
- Avoid adding comments or abstractions that do not explain a real constraint.
- After editing React or Tauri behavior, run the relevant checks and perform a manual runtime verification when the change affects user-visible or timing-sensitive behavior.
