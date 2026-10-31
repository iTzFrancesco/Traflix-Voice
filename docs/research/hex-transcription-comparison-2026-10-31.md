# Hex transcription comparison, 31 October 2026

Reviewed `anomalyco/hex` branch `dev` at `ec79045a927c` and Traflix Voice at
`5bcb0c83ffd4`. This comparison uses repository source and published project
benchmarks; it is not a device-to-device benchmark.

The subsequent implementation is documented in [native transcription](../native-transcription.md).
The comparison below records the state before that implementation.

## Runtime differences

Both applications offer Parakeet TDT 0.6B v3, but they do not run the same
artifact through the same decoder:

| | Traflix Voice | Hex |
| --- | --- | --- |
| Model artifact | Parakeet TDT 0.6B v3 INT8 ONNX | Parakeet TDT 0.6B v3 Q8_0 GGUF |
| Runtime | `sherpa-onnx` in the Python sidecar | `transcribe.cpp` in the native Rust app |
| Windows x64 inference | CPU; 4 or 6 worker threads, selected by CPU count | Vulkan GPU backend when available |
| Model lifecycle | Preloaded in the long-lived sidecar | Long-lived native transcriber; weights and GPU stream paths are prewarmed |
| Audio start | Opens a microphone stream for each recording | Can keep the microphone open and retain pre-roll |

Traflix's model artifact and CPU settings are in
[`parakeet.py`](../../src-tauri/whisper_engine/parakeet.py); its per-recording
stream is opened in [`engine.py`](../../src-tauri/whisper_engine/engine.py).
Hex pins the Q8_0 v3 artifact in
[`transcription_models.rs`](https://github.com/anomalyco/hex/blob/dev/src/transcription_models.rs)
and enables Vulkan for Windows x64 in
[`Cargo.toml`](https://github.com/anomalyco/hex/blob/dev/Cargo.toml).

The runtime and hardware dispatch are the strongest explanation for a speed
difference on a Windows x64 machine with a usable Vulkan GPU. The model name
alone does not establish that the inference path is equivalent.

## What the available benchmarks establish

Traflix measured 1.25–1.32 seconds to transcribe a 7.3-second Italian fixture
on an Intel i5-11600K using `sherpa-onnx` 1.13.7. Existing pause-aware
chunking reduced latency by 24.7–42.5% on tested long clips, with no WER
regression in those fixtures. The measurements and limits are in
[`parakeet-performance.md`](../parakeet-performance.md).

Hex's published backend comparison used an M2 Max and an English-oriented
Parakeet Unified model, not Parakeet v3 on Windows. It reported 37–44% lower
median inference time and 30–40% lower p95 latency for Metal Q8 versus ONNX
INT8, but provisional WER was 9.82% versus 8.07% for ONNX. The authors say
the references came from earlier ONNX outputs and the corpus is not a valid
quality gate. This supports investigating a native backend; it does not prove
that Hex's Windows configuration is faster or more accurate for Italian.
See Hex's [benchmark report](https://github.com/anomalyco/hex/blob/dev/docs/research/transcription-benchmark.md).

## Accuracy and capture observations

- In both apps, Parakeet v3 detects the language from audio; the visible
  Italian selection does not condition this model's decoder. Traflix accepts
  the language argument for a shared interface but ignores it in its Parakeet
  adapter. Hex's language/model capability definitions are in
  [`transcription_models.rs`](https://github.com/anomalyco/hex/blob/dev/src/transcription_models.rs).
- The screenshot shows Hex's Vocabulary set to None, so vocabulary hints do
  not explain that particular comparison.
- Hex's Keep ready mode retains microphone input and pre-roll. Traflix opens
  capture after the recording command. This can reduce hotkey-to-audio delay
  and protect the first syllable when someone speaks immediately; it does not
  make post-stop model inference faster. A similar mode should be optional and
  clearly disclose that microphone capture remains open while idle.
- Traflix already preloads the model and has measured silence trimming,
  silence skipping, and long-dictation chunking. Retuning thread counts or
  chunk sizes without new representative measurements is unlikely to beat a
  GPU backend and can regress recognition quality.

## Recommended optimization path

1. Measure cold and warm latency on the same Windows x64 PC, microphone, and
   independently transcribed Italian clips. Include short dictation, long
   dictation, proper names, noise, and immediate speech onset. Record model
   load time, stop-to-result latency, peak memory, and WER for both runtimes.
2. Prototype `transcribe.cpp` with its Vulkan backend behind a Windows x64
   feature flag, keeping the current sidecar path available as fallback. Adopt
   it only if the representative corpus shows a material latency gain without
   a meaningful WER regression and packaging/runtime checks pass.
3. Evaluate Keep ready as a separate opt-in capture improvement. It changes
   microphone lifetime, privacy expectations, device reconnection, and idle
   resource use, so it needs Windows runtime verification.
4. Consider local vocabulary or correction support only for user-supplied
   terms that actually occur in the user's dictation. Hex's screenshot has no
   vocabulary configured, and its repository notes that Parakeet vocabulary
   support depends on the selected runtime/model.

The highest-potential inference optimization is a Windows Vulkan backend, not
copying Hex's UI or changing the existing ONNX decoder parameters. The current
evidence is not sufficient to switch the production default or claim an
accuracy improvement.
