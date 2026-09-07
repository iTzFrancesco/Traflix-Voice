<h1 align="center">Traflix Voice</h1>

<p align="center">
  <strong>Voice dictation for Windows and Android.</strong><br/>
  Transcribe speech and deliver the result to the active editor.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/platform-Windows-0078D6?style=flat-square&logo=windows&logoColor=white" alt="Platform: Windows" />
  <img src="https://img.shields.io/badge/platform-Android-3DDC84?style=flat-square&logo=android&logoColor=white" alt="Platform: Android" />
  <img src="https://img.shields.io/badge/Tauri-2-24C8DB?style=flat-square&logo=tauri&logoColor=white" alt="Tauri 2" />
  <img src="https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react&logoColor=111827" alt="React 19" />
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.12" />
  <img src="https://img.shields.io/badge/license-MIT-4493F8?style=flat-square" alt="License: MIT" />
</p>

<p align="center">
  <a href="#features">Features</a> ·
  <a href="#supported-workflow">Workflow</a> ·
  <a href="#installation">Installation</a> ·
  <a href="docs/">Documentation</a> ·
  <a href="LICENSE">MIT License</a>
</p>

<p align="center">
  <img src="docs/assets/readme/traflix-voice-desktop.webp" alt="Traflix Voice desktop application" width="620" />
</p>

Traflix Voice has two platform surfaces built from a shared product contract:
the Windows desktop app is local-first with optional Groq Cloud transcription,
while the Android preview is a native keyboard with Groq Cloud as its only
transcription provider.

## Platforms

### Windows desktop

The desktop application uses Tauri 2, Rust, React, TypeScript, and a Python
sidecar. It captures speech globally and pastes the result into the focused
Windows application.

### Android preview

The Android port is maintained on the
[`main`](https://github.com/iTzFrancesco/Traflix-Voice/tree/main)
branch. It provides a native Traflix Voice keyboard with hold-to-speak or
toggle recording, Groq Cloud transcription, encrypted API-key persistence, and
a small overview/settings/history Hub. The Hub checks GitHub for newer Android
releases after startup and only considers the `android-vX.Y.Z` tag family and
the signed `app-universal-release.apk` asset; Windows releases are ignored. A
newer mobile release is downloaded, verified, and sent to the Android installer
automatically. While the Hub task remains open, the compact control stays
available over other apps; it is also allowed to remain visible on the lock
screen. Closing the Hub task cancels active capture, pending transcription, and
the recording notification.

The Android port is currently a private preview. Read the
[Android architecture plan](docs/android-architecture-plan.md) and the
[merge-readiness checklist](docs/android-merge-readiness.md) for the supported
mobile boundaries. The current [Android preview release](https://github.com/iTzFrancesco/Traflix-Voice/releases/tag/android-v0.1.13)
contains the installable signed APK. Never distribute an `*-unsigned.apk`;
Android requires a signed APK for direct installation.

## Features

- Local Whisper transcription through `whisper.cpp` and `pywhispercpp`.
- Optional Groq transcription using `whisper-large-v3-turbo`.
- Configurable global hotkeys, click-to-toggle, and hold-to-speak recording.
- Automatic paste into the focused application.
- Downloadable Base and Small local models from Hugging Face.
- CPU and optional CUDA device selection.
- Live waveform, always-on-top status overlay, and system-tray access.
- Local history and usage statistics.
- Multiple languages with automatic language detection.

## Supported workflow

### Windows desktop

1. Start the application and select a microphone in **System**.
2. Choose a local model in **AI**, or explicitly enable Groq Cloud mode.
3. Press the configured hotkey and speak.
4. Press it again to stop. The transcription is shown in the app and can be
   pasted into the focused application.

### Android

1. Install a signed Android preview from the `main` branch or its release.
2. Open the Hub, configure Groq Cloud once, grant microphone access, and
   enable/select **Traflix Voice Keyboard** in Android settings.
3. In any supported text field, choose Hold to Speak or Toggle in the Hub.
4. Press the Traflix microphone key. The transcript is committed through the
   active `InputConnection` and local history remains on the device.

Windows 10 and Windows 11 are the supported desktop platforms. Android 13+
is the target for the private mobile preview. macOS and Linux are not
currently validated. Desktop local transcription requires a downloaded model;
Android uses Groq Cloud only in the current preview.

## Installation

### Windows desktop

Prerequisites: Node.js 24, Python 3.12, a stable Rust toolchain, and the
Microsoft Edge WebView2 Runtime.

```powershell
git clone https://github.com/iTzFrancesco/Traflix-Voice.git
cd Traflix-Voice
npm ci
python -m pip install -r src-tauri/requirements.txt
npm run tauri dev
```

On first use, open **AI** and download a local model. The Small model is a
reasonable starting point for general dictation.

### Android preview

The Android implementation is maintained on
[`main`](https://github.com/iTzFrancesco/Traflix-Voice/tree/main). Build and
signing instructions are in
[Android merge readiness](docs/android-merge-readiness.md). A release APK must
be signed; files ending in `-unsigned.apk` are build intermediates and are not
valid direct-install packages. The current preview can be downloaded from the
[Android v0.1.13 release](https://github.com/iTzFrancesco/Traflix-Voice/releases/tag/android-v0.1.13).

The mobile updater checks for a newer Android tag after the Hub opens and on
return from the installer permission screen. It downloads only the expected APK
asset, verifies its SHA-256 and device ABI, and opens Android’s package installer
automatically. Android still requires the user to confirm the update and, on
some devices, allow installs from this app. Desktop updater behavior is
unchanged.

## Development and testing

```powershell
npm run build
python -m pytest src-tauri/test_*.py -v
cd src-tauri
cargo fmt --check
cargo clippy -- -D warnings
cargo test
```

For Android, also build the configured target with the Android SDK/NDK and a
keystore kept outside the repository. Then run `apksigner verify --verbose` on
the generated APK before sharing it. See the
[Android architecture plan](docs/android-architecture-plan.md) for the device
matrix and the [merge-readiness checklist](docs/android-merge-readiness.md) for
the release gates.

Focused benchmark scripts and technical reports are under `scripts/` and
`docs/`. Their measurements are environment-specific and are not guarantees.

## Privacy and data handling

Desktop local mode processes audio on the device after the selected Whisper
model has been downloaded. Desktop cloud mode and the Android preview send
recorded audio to Groq only after the user configures cloud access. The Android
preview stores its BYOK key in Android Keystore-backed storage and does not put
it in the APK or repository. A public Android release must use the Traflix
gateway instead of a client-held provider key.

History, settings, statistics, usage data, and downloaded models are stored in
the operating system's application-data directory. Never commit API keys,
tokens, passwords, or a populated `.env` file; use [`.env.example`](.env.example)
only as documentation.

## Architecture

- **Rust/Tauri** owns the desktop shell, hotkeys, clipboard, tray, settings,
  and Python process supervision.
- **React/TypeScript/Vite** provides the main interface and overlay.
- **Python** captures audio, manages Whisper models, performs local inference,
  and optionally calls Groq.
- **Android/Kotlin** owns the IME, microphone capture, native indicator,
  Android Keystore secret storage, `InputConnection` text insertion, and the
  mobile-only GitHub release updater.

The platform entry points are intentionally separated: `src/desktop/` contains
the desktop console, `src/mobile/` contains the Android Hub, and
`src-tauri/gen/android/` contains the Android Gradle/Kotlin project. Shared
types and persistence contracts are kept small so a platform change does not
silently alter the other runtime.

## Third-party components

Traflix Voice uses Whisper/whisper.cpp, `pywhispercpp`, Hugging Face model
hosting, and the optional Groq API. These components remain subject to their
own licenses and terms. Traflix Voice is independent and is not affiliated
with OpenAI, Groq, or Hugging Face.

## License

Traflix Voice is available under the [MIT License](LICENSE).
