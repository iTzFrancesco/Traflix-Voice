# Windows Groq latency review, 2 October 2026

This report records the baseline analysis before implementation. See
[desktop improvements](groq-desktop-improvements-2026-10-02.md) for the changes
adopted in desktop 1.6.9 and their subsequent verification.

Longer connection retention is the simplest implementation candidate. After a
real 65-second idle period, a client configured with 300-second expiry reused
its connection and saved 258.6 ms against the production 60-second expiry.
That is one paired observation and requires repetition before adoption.
Opening the connection during recording is a separate candidate. An explicit
live probe saved a median 119.1 ms in six paired first-upload tests.
Lossless FLAC saved a median 61.4 ms in eight paired tests of a 40.7-second clip,
but added latency on the short clip. HTTP/2 did not improve this connection.

This work adds a reusable benchmark and its tests. The runtime improvements
below are recommendations, with desktop verification required before adoption.

## Source and measurement scope

The working checkout was fast-forwarded by 24 commits to `b880eed`, desktop
1.6.8. The installed Windows application also reports 1.6.8. Its saved
configuration uses Groq Cloud, Italian, click-to-toggle recording, and
`keepClipboardResult=true`.

Environment: Windows 11 build 26200, Python 3.12.10, NumPy 1.26.4, HTTPX 0.28.1,
HTTPCore 1.0.2, h2 4.1.0, and soundfile 0.13.1.

The definitive comparison used the application's configured credential only
through the child process environment. An earlier pilot used a different
user-environment credential and is excluded from the tables. No `.env` file
was loaded. No microphone or private dictation history was used.

Three non-personal Italian passages were synthesized with Windows
`System.Speech`, Microsoft Elsa Desktop, as mono PCM16 WAV at 16 kHz.
Their input durations are 4.840, 15.600, and 40.695 seconds. All cases apply
the production gain and conservative silence trim to the same input.

The live comparison contains 135 successful transcription requests: five cases,
three clips, one warmup round, and eight measured rounds. Request starts are at
least 3.5 seconds apart. Case order is shuffled using seed 1729 for each clip
and round. Uploaded audio totals 2,703.15 seconds after the production trim.

The baseline uses the production HTTP client and WAV multipart encoder.
The cold control retains its SSL context but expires idle connections
immediately. HTTP/2 changes the transport; automatic language omits the language
field; FLAC encodes exactly the PCM16 samples that the WAV case would send.
The model remains `whisper-large-v3-turbo` throughout.

Timings include gain, trim, encoding, request construction, HTTP, and reading
the text result. They exclude microphone capture, the stop tail, Rust/WebView
delivery, clipboard insertion, and cached client construction. Transport traces
record event names and elapsed times only. Neither raw trace information nor
headers, credentials, response bodies, or transcripts are printed or saved.

## Live comparison

These are per-case medians in milliseconds. Every cell has eight measured
successful requests; warmups are excluded.

| Input duration | Current WAV, HTTP/1.1, Italian | Cold connection | HTTP/2 | Automatic language | FLAC |
| --- | ---: | ---: | ---: | ---: | ---: |
| 4.840 s | 203.9 | 491.7 | 295.6 | 265.2 | 253.4 |
| 15.600 s | 301.5 | 582.3 | 383.1 | 296.4 | 294.6 |
| 40.695 s | 476.5 | 719.3 | 578.1 | 479.7 | 427.3 |

All eight measured baseline requests per clip reuse their connection. All cold
controls open a new one. The HTTP/2 comparison actually negotiates HTTP/2.
Zero requests failed or reached a rate limit. Normalized reference word error
rate is zero on all three clean synthetic passages in every case. This does
not establish accuracy on natural speech, background noise, or weak word ends.

Paired savings subtract each candidate from the baseline in the same round.
They need not equal the difference between the two independent medians above.
Positive values mean faster.

| Candidate | 4.840 s saving, wins | 15.600 s saving, wins | 40.695 s saving, wins |
| --- | ---: | ---: | ---: |
| Cold control | -279.1 ms, 0/8 | -286.5 ms, 0/8 | -242.3 ms, 0/8 |
| HTTP/2 | -64.3 ms, 2/8 | -81.8 ms, 0/8 | -74.0 ms, 1/8 |
| Automatic language | -5.0 ms, 3/8 | +12.7 ms, 5/8 | -8.9 ms, 1/8 |
| FLAC | -23.9 ms, 4/8 | +6.4 ms, 6/8 | +61.4 ms, 6/8 |

FLAC reduces multipart size from 144,093 to 76,010 bytes for the short clip,
488,413 to 254,463 bytes for the medium clip, and 1,291,453 to 696,698 bytes
for the long clip. Preparation medians increase from 1.7/3.0/3.8 ms for WAV
to 6.6/11.8/18.3 ms for FLAC. Compression pays off most clearly on the long
input here. It should not become the unconditional format for short dictation.

The baseline p95 values are 269.4, 314.9, and 704.8 ms. With only eight samples,
the nearest-rank p95 is the maximum observed value, not a reliable tail estimate.
All live results describe this machine, connection, account, and service period.
The HTTP wait combines transfer, routing, provider processing, and response
delivery. It is not an isolated measurement of Groq inference.

## Connection prewarming probe

The existing [prewarm method](../src-tauri/whisper_engine/engine.py#L191) only
constructs the client. DNS/TCP and TLS still occur in the first POST.

A separate probe compared six pairs of fresh production clients on the short
clip. Before the candidate's timed POST, it made and fully consumed an
authenticated `GET /openai/v1/models` on the same client and origin. Each pair
alternates which side runs first; all 12 POSTs and six GETs succeeded.

| Short first upload | Median POST path | New POST connections |
| --- | ---: | ---: |
| Fresh client, no network prewarm | 488.7 ms | 6/6 |
| Fresh client, prior models GET | 377.2 ms | 0/6 |

Median paired saving is 119.1 ms, with six of six pairs faster. The cold
connection's DNS/TCP and TLS medians are 57.7 and 48.8 ms. Both stages disappear
from the candidate POST. A prior small GET does not reproduce all the benefits
of a connection that has already uploaded audio; do not attribute the entire
242-286 ms cold-control penalty to DNS and TLS.

The models GET itself takes a median 322.4 ms. Starting it sequentially after
stop would add work to the wait. Start it during recording and keep capture
independent. The 220 ms tail alone cannot reliably hide the complete warmup.
The production pool has one connection, so an unfinished warmup must not block
the transcription POST. Preserve client leases across key rotation and shutdown,
deduplicate warmups, bound their time, and handle overlap without waiting for
warmup completion. Avoid a continuous background keepalive loop.

Before adoption, measure the actual desktop after startup and long idle,
including very short recordings, failed warmups, key changes, and shutdown.
Prove that the timed POST reused the connection and that microphone readiness
and result order did not regress.

## Connection retention after real idle

The production [client configuration](../src-tauri/whisper_engine/transcriber.py#L87)
expires an idle connection after 60 seconds. A separate live probe first
transcribed the short fixture through two otherwise equivalent clients, one
with this production expiry and one with 300-second expiry. Both then remained
idle for at least 65 seconds. All four POSTs succeeded.

| After the idle period | POST path | DNS/TCP | TLS | New connection |
| --- | ---: | ---: | ---: | --- |
| 60-second expiry | 481.9 ms | 57.7 ms | 42.7 ms | Yes |
| 300-second expiry | 223.3 ms | 0.0 ms | 0.0 ms | No |

The observed saving is 258.6 ms. This verifies that the provider kept the
connection usable beyond the local 60-second expiry during this probe, and
that the candidate avoids a reconnection without an extra warmup request.
It does not establish reuse after 300 seconds: the tested idle was 65 seconds.
Only one pair was measured, with the production side running first, so service
variation and order may contribute to the exact saving. The presence or absence
of TCP/TLS establishes the mechanism; repeat 65-, 120-, and 300-second idle
episodes before choosing a production expiry. Also check server-closed sockets,
network changes, first-use failure handling, and key rotation. An ambiguous
transcription failure must not introduce automatic duplicate POSTs.

## Local stop and paste costs

The deterministic IPC benchmark uses production capture and processing workers
with a fake stream and HTTP response. It measures elapsed timestamps at the
request boundary and includes the real stop tail, queue drain, concatenation,
gain, and request preparation.

| Synthetic capture | Measured sessions | Stop to request median | Stop to request p95 |
| --- | ---: | ---: | ---: |
| 32 blocks, 1.024 s PCM | 50 | 232.7 ms | 234.9 ms |
| 1,272 blocks, 40.704 s PCM | 30 | 231.5 ms | 240.9 ms |

The [220 ms tail](../src-tauri/whisper_engine/constants.py#L26) is the dominant
local cost. It intentionally captures weak final consonants and samples arriving
after stop. Static tests do not justify shortening it. Use the recording window
for connection work before considering a change to audio preservation.

[Native paste](../src-tauri/src/commands.rs#L239) also waits 50 ms between the
clipboard write and `Ctrl+V`. The later 100 ms clipboard restore is disabled in
the current configuration and occurs after insertion when enabled. Reducing the
first wait to 20 ms has a theoretical 30 ms benefit, but requires repeated
insertion checks in real Windows editors and browsers, with Traflix visible
and hidden. Success from `SendInput` alone does not prove the text was inserted.

React already invokes paste before state updates and persistence. Moving paste
into Rust could remove a WebView round trip, but its benefit is unmeasured.
The short-clip live preparation median is only 1.7 ms, so further Python
micro-optimizations are a lower priority than connection handling and fixed waits.

## Recommended order

1. Verify longer connection retention, then preconnect during recording for
   first-use and expired connections. Avoid blocking audio or a short POST.
2. Evaluate optional FLAC for longer dictation across natural voice, noise,
   more durations, and slower uplinks. The tested long-clip paired saving is
   61.4 ms. Bundle and verify the additional `soundfile`/libsndfile dependency
   if it becomes production behavior.
3. Test a shorter clipboard settle window on Windows before changing it.
4. Keep the current HTTP/1.1, Turbo model, and explicit Italian setting. The
   comparison provides no general speedup from HTTP/2 or automatic language.
5. Retain the 220 ms audio tail until microphone and final-word checks establish
   that an alternative preserves speech.

Groq's current [speech documentation](https://console.groq.com/docs/speech-to-text)
supports the existing Turbo, mono 16 kHz, WAV, and explicit-language choices.
It also supports lossless FLAC for smaller uploads. The measurements above
determine whether that compression helps this workload. Transport observations
use the documented [HTTPCore trace extension](https://www.encode.io/httpcore/extensions/).

## Verification and reproduction

The Python suite passes all 168 tests. Nine benchmark tests cover equivalence
with the production POST, exact FLAC PCM, safe trace capture, exception/body
redaction, exclusion of failed and warmup calls, reference scoring, and stopping
at the first rate limit while saving partial numeric evidence. Python compilation
and whitespace checks pass. No runtime capture, hotkey, paste, IPC, or release
behavior was edited; an end-to-end microphone-to-editor timing was not measured.

The benchmark reads `GROQ_API_KEY` only from its process environment. With that
already set, a PowerShell reproduction is:

```powershell
$bench = Join-Path $env:LOCALAPPDATA 'TraflixVoice\benchmarks\groq-cloud-2026-10-02'
python scripts\benchmark_groq_network.py `
  --wav (Join-Path $bench 'short.wav') (Join-Path $bench 'medium.wav') (Join-Path $bench 'long.wav') `
  --references (Join-Path $bench 'synthetic-fixtures.json') `
  --iterations 8 --warmup 1 --interval 3.5 `
  --output (Join-Path $bench 'live-app-comparison.json')
python -m unittest discover -s src-tauri -p test_groq_network_benchmark.py -q
```

The optional comparisons require `h2` and `soundfile`. Evidence stays under
the application-data benchmark directory above: `live-app-comparison.json`,
`preconnect-comparison.json`, `idle-comparison.json`, the two `offline-stop-*.json` files, synthetic
fixtures, and `reproducibility.json`. The latter records source and fixture
hashes; the exact measured benchmark source is preserved beside the evidence.
The standalone preconnect and idle probes are also kept there. None contains
credentials, private recordings, or real transcripts.
