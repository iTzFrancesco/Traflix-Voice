# Local dictation and Keep ready review

Historical review of the v3 dual-backend implementation. The current local
model is Parakeet Ultra on the native GGUF CPU/GPU runtime.

The release keeps engine choice automatic. Native GGUF/Vulkan accelerates
Parakeet v3 on supported GPUs; CPU uses the existing ONNX model, selected after
an apples-to-apples local measurement showed it was faster on this host.
A cached, model-free hardware probe avoids loading two models just to choose a
backend. GPU initialization and inference failures retry on CPU with the same
audio. Active snapshots retain their selected model across unload/provider changes.

The native portability configuration originally disabled all x86 SIMD tiers.
Dynamic GGML modules now select the best supported tier without requiring new
CPU instructions on older PCs. Their DLLs are copied from Cargo's dependency
metadata and tested from relocated Unicode paths, away from the Vulkan SDK.
Windows native linker paths and native-test DLL resolution are configured explicitly.
The native build cache is shared by CI and release jobs.

Keep ready is desktop-only and shared by cloud/local capture. Its 450 ms ring
is bounded to 28,800 bytes of PCM plus buffer overhead, and is never saved or
uploaded while idle. Settings expose an opt-out and apply device/mode changes
after active captures. Session ownership and callback generations prevent old
streams, completed tails or device disconnects from contaminating another clip.
Cold model loading starts after capture is attached and listening is announced.
Stop during opening cancels without loading a cold model. The original stop tail,
gain, silence handling, chunking, durations and result/provider fields are preserved.

Focused tests cover buffer bounds, sample order, active unload, CPU fallback,
probe caching, switching devices/providers, disconnect/reconnect, deferred settings,
rapid capture ownership, model-loading audio and early stop. Real speech smoke
checks exercise the packaged native runtime. Timing and memory observations are
recorded in [native transcription](native-transcription.md).

Windows hardware checks still require an interactive PC: microphone permission,
real hotkeys with the main window focused and another app active, clipboard paste,
physical unplug/replug, GPU driver recovery, and natural Italian recognition.
CI checks and synthetic speech do not establish those physical interactions.
The release preserves Android's on-demand microphone lifecycle as requested.
