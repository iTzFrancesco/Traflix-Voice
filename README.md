# Traflix Voice

Privacy-focused desktop voice dictation for Windows, built with Tauri, Rust, React, TypeScript, and Python.

Traflix Voice converts speech into text and can paste the transcription into the active application. It follows a local-first workflow: the default provider runs Whisper locally, while an optional Groq provider offers cloud transcription when enabled by the user.

> Windows is the primary supported platform. macOS and Linux support may require additional validation.

## Features

- **Local transcription** powered by [whisper.cpp](https://github.com/ggerganov/whisper.cpp) through `pywhispercpp`.
- **Optional cloud transcription** using Groq's `whisper-large-v3-turbo` model.
- **Global hotkeys** with configurable keyboard and mouse combinations.
- **Click-to-toggle** and **hold-to-speak** recording modes.
- **Automatic paste** into the currently focused application.
- **On-demand model downloads** from Hugging Face.
- **CPU and optional CUDA** compute-device selection.
- **Real-time audio waveform** while recording.
- **Always-on-top overlay** with recording and processing status.
- **System tray integration** for quick access while the application is running.
- **Local history and usage statistics** stored on the device.
- **Multiple transcription languages**, including automatic language detection.

## Privacy and provider modes

### Local mode

Audio is processed on the local machine after a Whisper model has been downloaded. No transcription request is sent to an external provider.

### Cloud mode

Audio is sent to Groq for transcription. The API key is entered in the application's **System** tab and stored in the application's local settings. Review Groq's terms and privacy policy before enabling this provider.

No `.env` file is required for normal application use. The repository's `.env.example` file documents the optional benchmark variable without containing a credential. Never commit API keys, tokens, or other credentials to the repository.

## Measured cloud performance

The repository includes a live Groq benchmark in the latency report. In the final recorded run, one warm-up request and ten measured requests all returned a valid transcription result:

| Measurement | Result | Notes |
| --- | ---: | --- |
| Live Groq transcription path | **188.6 ms median** | Includes network and remote-provider time |
| Live Groq transcription path | **178.3 ms mean** | Same ten measured requests |
| Observed live range | **119.2–276.9 ms** | Same benchmark run |
| Local stop-to-request path | **0.179 ms median / 0.303 ms p95** | Excludes network and Groq inference |
| Silence-trimming scenario | **1,281.5 → 193.4 ms median** | Controlled 4.5-second clip with 0.5 seconds of speech; 84.9% reduction |

These are measurements from a specific environment, not service-level guarantees. Network conditions, provider load, model execution, and audio content can change the result. The detailed methodology and regression history are available in [`docs/latency-optimization-report.md`](docs/latency-optimization-report.md).

## Requirements

| Component | Requirement |
| --- | --- |
| Operating system | Windows 10 or Windows 11 |
| Node.js | Node.js 24 recommended; npm included |
| Python | Python 3.12 |
| Rust | Stable Rust toolchain with `cargo` |
| Windows runtime | Microsoft Edge WebView2 Runtime |
| Optional acceleration | A compatible CUDA environment |

The first local transcription requires a model download. The currently available models are approximately **145 MB** for Base and **466 MB** for Small.

## Installation

Clone the repository and install the frontend and Python dependencies:

```powershell
git clone https://github.com/iTzFrancesco/Traflix-Voice.git
cd Traflix-Voice
npm ci
python -m pip install -r src-tauri/requirements.txt
```

Start the application in development mode:

```powershell
npm run tauri dev
```

On the first launch, open the **AI** tab and download at least one local model. The **Small** model is the recommended starting point for general dictation.

## Usage

1. Start Traflix Voice.
2. Select a microphone and transcription language in **System**.
3. In **AI**, choose a local model or enable the optional cloud provider.
4. Press the default hotkey, `XBUTTON2` (the forward mouse button), and speak.
5. Press the hotkey again to stop recording.
6. When automatic paste is enabled, the transcription is inserted into the focused application.

The hotkey, recording mode, provider, model, language, audio device, and compute device can be changed from the application settings.

When the main window is hidden, the compact overlay remains available. It shows the current state, displays the audio waveform while recording, and can be double-clicked to reopen the main window.

## Whisper models

| Model | Download size | Approx. RAM | Intended use |
| --- | ---: | ---: | --- |
| **Base** | 145 MB | ~1 GB | Lower resource usage and faster startup |
| **Small** | 466 MB | ~2 GB | Recommended balance of speed and accuracy |

Cloud mode uses `whisper-large-v3-turbo` through Groq and does not require a local Whisper model.

## Architecture

```text
                    JSON lines over stdin/stdout
┌──────────────────────┐     ◄──────────────────►     ┌──────────────────────┐
│ Tauri desktop shell  │                              │ Python sidecar       │
│ Rust                 │                              │ Whisper engine       │
│                      │                              │                      │
│ • Global hotkeys    │                              │ • Audio capture     │
│ • Clipboard/paste   │                              │ • Local Whisper     │
│ • System tray       │                              │ • Groq transcription │
│ • Settings and IPC  │                              │ • Model management  │
└──────────┬───────────┘                              └──────────────────────┘
           │ Tauri commands and events
           ▼
┌──────────────────────┐
│ React + TypeScript   │
│ Vite frontend        │
│                      │
│ • Main settings UI   │
│ • Overlay window     │
│ • Model catalog      │
│ • Waveform and stats │
└──────────────────────┘
```

- **Tauri/Rust** provides the desktop shell, global hotkey polling, clipboard integration, system tray, local persistence, and Python process supervision.
- **React + TypeScript + Vite** provides the main interface and overlay window.
- **Python** captures microphone input, downloads and loads Whisper models, performs local inference, and optionally calls the Groq transcription API.
- Communication between Rust and Python uses a line-delimited JSON protocol.

## Data storage

Application data is stored in the operating system's application-data directory under `it.traflix.voice`. The application may create:

- `settings.json` for user preferences and the optional Groq API key;
- `stats.json` for dictation statistics;
- `history.json` for recent transcriptions;
- `groq_usage.json` for local cloud-usage accounting;
- `models/` for downloaded Whisper model files.

These files remain local to the user's machine and are not part of the repository.

## Development and testing

Build the frontend:

```powershell
npm run build
```

Run the Rust checks and tests:

```powershell
cd src-tauri
cargo fmt --check
cargo clippy -- -D warnings
cargo test
cd ..
```

Run the Python checks and tests:

```powershell
python -m py_compile src-tauri/whisper_engine.py
python -m pytest src-tauri/test_whisper_engine.py -v
```

Create a production Windows installer:

```powershell
npm run tauri build
```

The MSI installer is written to `src-tauri/target/release/bundle/msi/`.

GitHub Actions runs Rust, Python, frontend, and Windows build checks for pushes and pull requests targeting `main`. A GitHub Release is created only for version tags matching `v*`.

## Project structure

```text
src/                         React and TypeScript frontend
src-tauri/src/               Tauri and Rust application code
src-tauri/whisper_engine/    Python transcription engine
src-tauri/whisper_engine.py  Python sidecar entry point
src-tauri/test_*.py          Python tests
scripts/                     Benchmarks and development utilities
docs/                        Technical reports and design notes
```

## Third-party components

Traflix Voice uses Whisper/whisper.cpp, `pywhispercpp`, Hugging Face model hosting, and the optional Groq API. Each component remains subject to its own license and terms. Traflix Voice is an independent project and is not affiliated with OpenAI, Groq, or Hugging Face.

## License

Traflix Voice is licensed under the [MIT License](LICENSE).
