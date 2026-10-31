# Native Parakeet transcription

Desktop local dictation selects the engine automatically. A usable GPU enables
the same `transcribe.cpp` revision and Parakeet TDT 0.6B v3 Q8_0 artifact as
Hex 3.0.0. CPU dictation retains the faster existing Sherpa-ONNX backend. The standalone Rust helper retains
model weights, warms up inference before reporting readiness, chooses its
backend automatically, and frees inference scratch after each segment.
Windows x64 builds enable Vulkan. Other builds use the available native
backends, including CPU. This does not change the Android cloud recorder.

Python owns the provider-independent Keep ready microphone, gain, conservative edge trimming,
pause-aware chunks, result duration and external JSON IPC. Normal audio passes
to the helper through a binary pipe and is never written to a temporary file.
The helper has one serialized inference session at a time. Active dictations
retain ownership when the UI unloads the model; the last owner terminates the
helper, releasing both RAM and GPU allocations. A crashed/timed-out helper is
terminated and can be recreated on the next dictation.

The settings model ID remains `parakeet-tdt-0.6b-v3-int8` for compatibility.
The actual new artifact is `parakeet-tdt-0.6b-v3-Q8_0.gguf`, 739,508,576 bytes.
It is pinned to Hugging Face revision `85ac09ea12fc4b1112fa76810059364bc6adc9de`
and verified with SHA-256 before loading. Existing ONNX installations download this artifact only when a GPU is available.
Their CPU files are retained. A probe detects devices before loading weights.
GPU initialization or inference failure automatically falls back to CPU ONNX;
missing CPU files are downloaded when required. The original recording is retried
and still produces one final result. The CPU artifact is pinned at Hugging Face
revision `2bda32ec70b097a55adaa07d9a7173915b43cc78`.

## Development and packaging

Install Rust, CMake and the platform C++ build tools. Windows x64 also needs the
Vulkan SDK and SPIRV-Headers; CI installs them with the composite action under
`.github/actions/setup-native-transcriber`. Build the helper before starting
the desktop development app:

```sh
python scripts/build_native_transcriber.py
```

The Windows packaging script builds the helper with the committed lockfile and
copies it alongside `whisper_engine.exe`, inside the existing bundled resources.
It also includes the third-party notices. The native dependency is separate
from the Tauri crate, so Android does not compile or package it.

## Memory measurement

Use the installed model directory (not a private reference transcript) to
measure the native process. This command runs actual model load, warmup and
inference, reports RSS in MiB, and excludes GUI/Python RSS and GPU memory:

```sh
python scripts/benchmark_native_memory.py --model-dir /path/to/model-directory
```

Optionally pass `--wav /path/to/audio.wav` for mono PCM16 at 16 kHz. Audio and
recognized text are not printed. An omitted WAV uses five seconds of silence,
which is useful for allocations but does not establish transcription quality.
On Windows, RSS is the working set from GetProcessMemoryInfo. On Linux, it is
VmRSS from /proc. The inference peak is sampled every 20 ms. A GPU measurement
also requires the dedicated/shared GPU memory counters for the helper; RSS
alone does not include VRAM or prove the total system-memory cost.

Windows hardware, clipboard, microphone, model migration and Vulkan execution
still require an interactive desktop check. CPU-only Linux verification does
not establish Windows speed or recognition accuracy on natural Italian speech.

## Initial scalar baseline on 31 October 2026

The pinned helper compiled on Linux and passed its Rust framing test, formatting
and Clippy. The Python suite passed with 257 tests, 170 subtests and 3 skips;
TypeScript checking passed. The runtime loaded the checksum-verified GGUF and
returned a nonempty transcript for 6.5925 seconds of synthetic Italian speech
made with espeak-ng. This establishes inference plumbing, not recognition
quality on natural speech.

On this constrained CPU-only Linux host (about 1.6 GiB physical RAM), the
helper's RSS after load/warmup was 505.8 MiB, the sampled inference peak was
684.6 MiB, and RSS after inference was 651.9 MiB. Idle swap was 109.6 MiB;
the peak sampled sum of RSS and swap was 832.0 MiB. These values exclude
Python, the desktop shell, WebView and VRAM. They must not be presented as a
Windows total RAM measurement. The measured run loaded/warmed in 13.86 s
and inferred in 15.935 s, so this CPU-only run does not establish a speed
improvement. Windows Vulkan latency and memory remain unmeasured.

The initial verification host has no desktop display or accessible PulseAudio server. Physical
microphone, hotkey, paste, packaged Windows execution and GPU validation remain
outstanding. The Windows CI build installs the Vulkan toolchain and compiles
and checks the helper before packaging it; that workflow was not run locally.

A real engine integration replay also passed through model loading and the
production local preprocessing/result path. It emitted one result, preserved
provider and original duration, kept the helper alive after unloading the
engine's owner while an active snapshot remained, and terminated the helper
when that snapshot was released. Only the unavailable sounddevice module was
mocked; native model loading and inference used the real helper and GGUF.

## Performance and capture follow-up

The native build now ships dynamic backend libraries and portable CPU variants.
GGML selects compatible SIMD kernels at runtime; the generic x64 fallback remains
available on older processors. GPU initialization failures are retried in a fresh
CPU-only helper. The packaging script copies the dependency-reported libraries
beside the helper, and the Windows workflow exercises this relocated layout with
a pinned public speech fixture, Unicode paths and the Vulkan SDK removed from PATH.

Keep ready opens the selected microphone at desktop initialization for either
provider. Only 450 ms of idle mono float32 audio is retained (28,800 bytes plus
small buffer overhead). No idle volume events, file writes or cloud uploads occur.
Recording ownership and callback generations fence successive clips, device
changes and disconnections. Turning the option off during capture applies after
that capture finishes. A failed device is reopened on the next dictation.

The first syllables remain queued while a cold local model loads. Existing gain,
trim, pause boundaries and the 220 ms stop tail still apply to the captured clip.
The mode is default-on and has an explicit desktop settings opt-out. Android
retains its existing on-demand microphone lifecycle.

## Automatic CPU/GPU decision verified

A follow-up comparison used the same 6.5925-second synthetic Italian input and
production gain/edge processing. Three warm measurements gave a median of
1.143 s for Sherpa-ONNX 2.0.1 and 3.904 s for the optimized GGUF CPU path, with
the same normalized WER (20% on this artificial voice). This is why production
retains ONNX on CPU and uses the native GGUF path for GPU acceleration. The
15.190-to-5.195 s kernel experiment measured two native CPU builds only; it
must not be described as an improvement over the original ONNX application.

A real CPU auto-selection run also verified that existing ONNX files were
reused without a GGUF download. The constrained host swapped heavily: Python
plus ONNX reached 716 MiB resident HWM and about 353 MiB swapped after inference,
excluding the GUI. The separately measured native helper reached 736 MiB RSS
and 943 MiB for the sampled peak RSS plus swap, excluding Python/GUI/VRAM.
These Linux figures are not Windows total-memory promises.
