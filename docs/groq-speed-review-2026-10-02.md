# Groq client speed review, 2 October 2026

The 100-round comparison covers the existing Groq client, not a different model.
It starts from the working tree after the word-preservation fixes in the
[dictation flow review](dictation-flow-review-2026-10-02.md), rather than from
unmodified `514972c`.

One round is a comparative experiment on a named input profile. These are 100
experiments, not 100 independent optimizations or 100 forced code edits.
The measurements use synthetic PCM, HTTPX MockTransport, and a loopback JVM
HTTP server. None of them measures live Groq recognition or mobile hardware.

## Comparison coverage

| Rounds | Area | Profiles | Measured pairs per profile | Required equivalence |
| --- | --- | --- | --- | --- |
| 1-20 | PCM WAV and multipart construction | 20 | 201 | Complete request bytes |
| 21-40 | Silence-edge trimming | 20 | 201 | Exact selected samples and unchanged input |
| 41-60 | Automatic gain | 20 | 201 | Exact float32 bits, mutation, and view ownership |
| 61-80 | Gain through request and result handling | 20 | 201 | Complete request bytes and result events |
| 81-100 | JVM upload | 20 | 10 | Multipart bytes, content length, and request count |

The Python pairs alternate baseline-first and candidate-first execution.
Mutable gain inputs are copied before timing. The pipeline measurement includes
gain, trim, encoding, request construction, mock HTTP dispatch, and result
handling. It excludes capture, the stop tail, the desktop shell, and UI.
The strided pipeline fixture becomes contiguous during its untimed input copy.

The upload profiles combine five durations, two server read sizes, and two
server pause settings. Their p95 values have only ten samples per mode.
Follow-up measurements use the same 20 profiles and do not add to the round count.
All 100 experiments preserve their required output invariants.

## Python changes retained

### A single final multipart copy

`_encode_pcm16` preserves the previous conversion. `_encode_wav_header` preserves
the WAV framing. `encode_cloud_multipart_from_recording` joins the multipart
prefix, WAV header, PCM memoryview, and suffix once. It no longer creates a PCM
bytes object and a complete intermediate WAV before the final request body.

The returned body still owns its bytes. No buffer is shared across recordings,
and the public WAV helper still returns a `BytesIO`. HTTP request construction,
client leases, key rotation, response cleanup, language fields, and error
handling remain unchanged.

### Bounded edge scans on long speech

For clips longer than eight seconds, `trim_cloud_silence` checks the first
one-second block before running full-recording extrema scans. An onset in that
block proves that the clip is not silent. The function then scans the trailing
edge without reading the whole interior.

The silence threshold remains `1 / 32767`. Padding remains 320 ms. Internal
pauses and weak word edges remain unchanged. Long clips with an empty initial
block retain the full-silence check and the existing search behavior.

### Finite-input gain fast path

`apply_automatic_gain` checks one boolean finite mask instead of always running
the sanitizer's three masks and replacement passes. Invalid, read-only, and
non-floating inputs retain the original sanitizer behavior.

Frame RMS, percentile selection, incomplete-frame handling, gain limits, and
in-place float32 multiplication remain unchanged. The raw microphone meter is
separate. Exact-bit tests cover signed zero, invalid samples, subnormal values,
outliers, reversed views, and strided views.

## Representative Python measurements

Environment: Linux x86-64, Python 3.14.4, NumPy 2.5.3, and HTTPX 0.28.1.
All figures are medians in milliseconds unless the table names another unit.

| Measurement | Baseline | Candidate | Change |
| --- | ---: | ---: | ---: |
| Multipart, quiet 4 s | 0.037841 | 0.029726 | -21.4% |
| Multipart, quiet 30 s | 0.239380 | 0.164198 | -31.4% |
| Multipart, quiet 180 s | 3.247371 | 1.846990 | -43.1% |
| Trim, quiet 30 s | 0.070693 | 0.037871 | -46.4% |
| Trim, quiet 180 s | 0.803620 | 0.090480 | -88.7% |
| Gain, quiet 180 s | 14.1014 | 7.0875 | -49.7% |
| Local pipeline, quiet 4 s | 0.731263 | 0.639973 | -12.5% |
| Local pipeline, quiet 30 s | 2.467886 | 1.591060 | -35.5% |
| Local pipeline, quiet 180 s | 17.849424 | 9.728618 | -45.5% |
| Local pipeline p95, quiet 180 s | 21.217261 | 12.132524 | -42.8% |

The multipart allocation peak for 180 seconds falls from 17,280,283 to
11,521,163 traced bytes. The gain-only peak falls from 14,400,912 to
11,689,448 traced bytes. These are temporary allocations measured with
`tracemalloc`, not total process RAM.

Very short clips have little encoding work left to remove. Their multipart
differences are mostly below 5 microseconds. Not every individual stage improves:
the 30-second silence trim adds 6.7 microseconds, while its complete local
pipeline improves from 1.205 to 0.786 ms. Invalid gain input also pays for the
finite check before the original fallback, adding about 3.3 microseconds for
319 samples and 13.1 microseconds for a sparse-invalid two-second array.

## Stop latency with production workers

`benchmark_cloud_latency.py` now starts capture through the production IPC
command and uses the capture and deferred-transcription workers. Request and
result timestamps are recorded where the events occur, rather than after a
waiting benchmark thread wakes. Workers close after each sample.

These separate checks use 20 samples after two warmups and a prewarmed client.
The fake audio stream supplies constant synthetic PCM. They include the real
220 ms stop tail, concatenation, gain, request preparation, and a mock response.
They still exclude the network, Groq inference, Rust, and paste into another app.

| Stop to mock result | Baseline median | Candidate median | Baseline p95 | Candidate p95 |
| --- | ---: | ---: | ---: | ---: |
| 8 blocks, 256 ms PCM | 222.191 ms | 222.096 ms | 222.534 ms | 222.542 ms |
| 5,625 blocks, 180 s PCM | 252.217 ms | 241.105 ms | 257.392 ms | 242.912 ms |

The short-clip difference is not a material improvement. The long-clip median
saves 11.1 ms without shortening the tail. Neither table supports a claim that
Groq inference or real end-to-end dictation is 45% faster.

## Android upload evaluation

`GroqMultipartBody` owns the multipart framing and overflow-checked `Long`
content length. Its tests preserve the old envelope, including UTF-8 fields,
and check cancellation before every copy chunk. Missing or changed recordings
fail instead of completing a malformed body. The helper does not own the
output stream, credentials, retries, or result delivery.

Fixed-length streaming is rejected rather than presented as a speed improvement.
The final client retains the existing transport buffering and a 64 KiB output
buffer. The helper uses one 64 KiB copy buffer, removing the separate buffered
input allocation. `HttpURLConnection` still buffers the complete body internally.
This is not end-to-end bounded-memory streaming.

| Upload strategy | Profiles with lower median | Median profile-level paired saving |
| --- | ---: | ---: |
| Raw fixed-length reference | 8 of 20 | -0.531 ms |
| Fixed-length with 64 KiB output buffer | 3 of 20 | -0.686 ms |
| Retained helper with default transport buffering | 10 of 20 | -0.010 ms |

Positive saving means faster. The raw reference is from an earlier run and is
not paired directly against the two follow-up strategies. The final comparison
measures 600 uploads across three strategies. No general Android upload speedup
is established. The retained changes improve cancellation checks, file
validation, framing ownership, and application buffer allocation.

The loopback benchmark does not model TLS, Android's HTTP implementation,
provider inference, or mobile radios.

Fixed-length streaming changes automatic authentication and redirect replay.
The loopback controls confirm that the default buffered mode can replay a
followed 307 POST, while fixed-length mode does not. With redirects disabled,
301, 302, 303, 307, 308, 401, and 407 each produce one request and no
redirect-target request. Redirects remain disabled in the retained client.
No manual retry or redirected credential forwarding is added.

The JDK HTTP-server benchmark now lives in `scripts/android`, outside Android's
test source set. Android's SDK compiler cannot resolve `com.sun.net.httpserver`.
The standalone runner compiles it with JDK 17 without changing app dependencies,
Gradle settings, or release behavior. The 12 helper tests remain in Android's
ordinary test suite.

## Verification and remaining limits

- Python unit and browser end-to-end suite: 168 tests and 98 subtests passed.
- TypeScript and Vite production build: passed.
- Python compilation and `git diff --check`: passed.
- Android Gradle compilation and JVM tests: passed, including all 12 multipart
  helper tests and the previous 21 tests.
- Standalone upload benchmark: independently rerun after the move, passing all
  20 profiles, 600 measured uploads, and replay and early-delivery checks.
- Additional cloud seam stress: 100 synthetic requests, 100 results, zero failures.
- No connected Android device or Windows desktop runtime is available.
- No Rust toolchain is installed. No Rust source changes are made in this work.
- The two existing Android TV manifest lint errors remain outside this change.

Two incorrect cloud mocks now patch `acquire_groq_client`, which is the method
the transcriber actually calls. A transport failure test also asserts that
`send` ran. A new regression exercises five consecutive production IPC sessions,
client reuse, one result per recording, and audio queued during the unchanged
tail. Independent read-only reviews found no actionable Python or Android
upload defects.

The numerical artifacts, `round-results.tsv`, and frozen pre-edit source remain
outside the repository under `/tmp/opencode/traflix-groq-100-ses-f047d/`.
Generated audio, build products, and logs are not committed. Benchmark and
hardware checks are listed in
[Verify the dictation flow](verify-dictation-flow.md).
