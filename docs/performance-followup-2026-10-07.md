# Dictation performance follow-up, 7 October 2026

The comparison starts from Windows 1.7.7, commit `b4eabbf`, after the
20-second Parakeet chunking changes documented in
[Parakeet performance](parakeet-performance.md). Two investigations covered
native inference and the capture/cloud pipeline. Experiments used existing
local models and synthetic Italian fixtures. No audio was sent to Groq.

## Native inference candidates rejected

The batch comparison reused one six-thread recognizer, with one warmup per
mode and three measured runs in rotating order. Measurements include gain,
local preprocessing, native inference and result generation.

| Candidate, 432 words | Current serial | Candidate | Decision |
| --- | --- | --- | --- |
| Two streams per batch | 10.96 s | 11.07 s | No speed improvement |
| Three streams per batch | 10.96 s | 11.34 s | Slower |

Batch decoding changed the transcript and reduced synthetic WER from 0.69%
to 0.23%, but it did not address latency. The Nemo implementation batches the
encoder and decodes the individual TDT streams in a loop. See the
[versioned native decoder](https://github.com/k2-fsa/sherpa-onnx/blob/v1.13.7/sherpa-onnx/csrc/offline-transducer-greedy-search-nemo-decoder.cc).

A separate screening compared 12- and 16-second targets with the current
20-second target on 211-, 221- and 432-word inputs. The search margin and
minimum chunk duration retained their current 40% and 60% ratios. Digital
pause compaction and edge context stayed the same.

For 211 words, both shorter targets took 7.37 s versus 6.58 s. WER increased
from 0% to 0.47% for 16 seconds and 1.42% for 12 seconds. Neither candidate
passed all quality guards, so the production chunk parameters remain 20 s.
These screening timings are single measured runs, not a confirmed speedup.

## Capture onset and widget visibility

The reported symptom is a 0.5–1 s interval between the hotkey and the start
cue/widget, on both providers. A physical microphone probe discarded every
sample and recorded only timings. Four openings per profile used the same
Realtek input, mono float32 at 16 kHz with 512-sample blocks.

| Profile | Open and start, median | First callback, median |
| --- | --- | --- |
| Current default MME | 54.6 ms | 96.5 ms |
| MME, low latency requested | 53.5 ms | 95.1 ms |
| WASAPI shared, automatic conversion | 54.2 ms | 97.6 ms |
| WASAPI shared, low latency requested | 64.0 ms | 107.6 ms |

The first MME opening took 196.9 ms to start and 238.7 ms to deliver a callback.
This probe excludes Rust hotkeys, IPC, WebView scheduling and sound playback.
It does not reproduce the complete reported delay and does not justify an
audio-backend change.

A candidate patch shows the overlay from Rust on the actual `listening`
event, before forwarding that event to JavaScript. Currently the hidden
overlay's JavaScript handler requests its own visibility. The candidate
uses `show()` without taking keyboard focus and keeps the existing sound
and state handling. Its native show duration is logged without audio or text.
It passed Rust formatting, Clippy and the 29-test Rust suite, but was removed
from this round because desktop runtime verification was unavailable.

[Microsoft documents reduced rendering and task scheduling for hidden
WebViews](https://learn.microsoft.com/en-us/microsoft-edge/webview2/reference/win32/icorewebview2controller?view=webview2-1.0.3537.50#get_isvisible).
That supports testing native wakeup; it does not establish a fixed delay
for Tauri events. The full shortcut-to-cue improvement still needs a desktop
runtime comparison with the main window visible and hidden, including rapid
stop/start. The user's latest observation did not reliably distinguish those
states. The installed application inspected during the investigation was
1.7.6 and did not contain this candidate. The reported delay remains unresolved.

## Cloud connection maintenance

The existing connection probe runs when capture starts. Its idle threshold
is 240 s and HTTP keepalive expiry is 300 s. A long dictation can therefore
start while a connection is considered fresh and finish after it expires.

The follow-up patch rechecks the existing prewarm opportunity every 60 s
while that cloud capture is active. The idle gate and single-flight protection
still decide whether a GET is necessary. Stop, capture failure and shutdown
cancel the session timer; credential rotation and late callbacks retain their
session guards. Six deterministic tests cover renewal and those lifecycle
cases. The complete Python suite passes with 227 tests, 134 subtests and two
skips. Network latency savings have not been measured live.

Lossless FLAC encoding was also evaluated. It reduced the 195.70-second WAV
from 6.25 MB to 3.42 MB but added about 76 ms of preparation. Groq
[accepts FLAC](https://console.groq.com/docs/speech-to-text), but its encoder
dependencies are absent from the distributed sidecar. Adoption requires a
paired network measurement and an input-size threshold.

## Local predecode prototype

The prototype predecodes completed chunks while capture continues, using one native worker.
The scheduling prototype closes nine chunks before the end of the 432-word
fixture and leaves about 15 s of audio pending. This is an audio-duration
observation, not a measured post-stop inference time.

A follow-up measured native inference with exact-input caching. One warmup
preceded three alternating comparisons per fixture on the same six-thread
recognizer. The residual column measures cache lookup and decoding of final
chunks that cannot be reused. It excludes capture drain, final global gain,
IPC, clipboard and UI. These are prototype measurements, not application
stop-to-result timings.

| Words | Current complete pipeline, median | Prototype residual, median | Exact cached final chunks |
| --- | --- | --- | --- |
| 211 | 6.518 s | 0.904 s | 4 of 5 |
| 221 | 6.020 s | 3.340 s | 2 of 5 |
| 432 | 12.246 s | 1.818 s | 8 of 10 |

The reconstructed transcript matched the current transcript exactly in all
nine comparisons. WER stayed at 0%, 0.45% and 0.69%, respectively. A FIFO
simulation using measured early-job durations completed every early job
before the original audio ended. That simulation does not reproduce an
overloaded desktop or validate microphone callbacks.

Speculation can increase total CPU work. On the 221-word fixture, discarded
early chunks raised native work to about 7.68 s versus 6.00 s. The benefit is
less waiting after stop. Batch decoding and smaller chunks failed the speed
or quality gates; predecode is the next candidate, pending lifecycle and
desktop checks. Production local inference remains the released 1.7.7 path.

Use speculative caching to preserve the current recognition behavior. At
stop, run the existing complete-recording gain, trimming and pause selection.
Reuse an early transcript only when its prepared samples, boundaries and
context exactly match the final chunk. Otherwise decode that chunk normally.
This matters because a later loud word or click can change global gain and
pause thresholds.

Keep the recognizer alive per session, retain raw audio for fallback, preserve
the 220 ms tail, emit one final result with the original duration and leave
short captures on the existing path. Validate late loud speech, weak syllables,
noise, repeated words, stop/start, unload, shutdown and failed early decoding
before adoption. Each offline stream must receive one complete waveform;
its [native input method](https://github.com/k2-fsa/sherpa-onnx/blob/v1.13.7/sherpa-onnx/csrc/offline-stream.cc)
finalizes feature extraction immediately.

Bound pending jobs and cache memory. At stop, cancel speculation that has not
started so it cannot delay finalization. A failed, canceled or unmatched
candidate must become an ordinary cache miss. The partial integration was
removed when the user requested that this round conclude.
