# Groq desktop improvements, 2 October 2026

Desktop 1.6.9 keeps `whisper-large-v3-turbo` for every cloud audio transcription.
The initial [latency review](groq-live-latency-review-2026-10-02.md) records the
baseline before these runtime changes.

## Fast path

The HTTP/1.1 connection pool retains idle connections for 300 seconds. An
authenticated models request can establish an expired connection while audio
capture is already running. Warmup is single-flight, has a separate connection
slot, and never delays capture or waits before the transcription POST. Failed
warmups have a cooldown; credential rotation and shutdown retire leased clients.

Live synthetic-audio measurements using the application's saved credential
showed a median 119.1 ms saving in six paired first-upload tests. One paired
65-second idle test saved 258.6 ms. These are connection-specific observations,
not a guaranteed saving on every dictation. HTTP/2 and unconditional FLAC were
not adopted. The existing audio tail and clipboard timing remain intact.

## Vocabulary and selective correction

The widget logo opens the vocabulary editor. Each bullet is a name or phrase;
Enter adds another line. Existing comma-separated entries remain readable.
Settings persist the list; Python normalizes it into a bounded prompt in the
same Whisper request. There is no fuzzy substitution of similar words.

Whisper returns segment confidence with `verbose_json`. The 32-call text versus
verbose comparison had the same word error rate and a paired median overhead
of -0.6 ms. On 16 invented Italian fixtures, including faster synthetic speech,
the vocabulary prompt reduced aggregate word error rate from 1.74% to 1.39%.
This small synthetic corpus does not establish accuracy on natural fast speech.

Common unambiguous Italian typography is fixed locally. An optional correction
request uses `openai/gpt-oss-20b` only for eligible uncertain passages or specific
clear agreement errors. Reliable fast speech alone does not trigger it. Short
utterances, code, URLs and excessive text skip it. The response must preserve
word count, names, numbers, negation and most wording; unsafe edits are rejected.

Twelve invented correction requests matched expected output, with a median
331.7 ms request time and about 313 total tokens. Correction consumes Groq's
separate text-model quota. Usage displays persisted input/output token counts.
Rate limits, unavailable models, malformed responses and timeouts return the
original text without retries. Request timeouts apply per network operation;
there is no claim of a strict two-second total deadline.

## Silence handling

A pinned MIT-licensed Silero V5 voice detector runs locally before upload and
does not cut detected speech. It is loaded in the background before processing.
The Windows sidecar bundle includes the ONNX model and license; the build checks
their exact SHA-256 hashes before packaging. Missing or broken resources produce
a warning and fall back to Whisper's silence metadata.

The native detector classified 66 synthetic speech/noise fixtures over ten
rounds with no errors, including quiet speech and short Italian words. Voiced
clips had a median detection time of 0.79 ms and p95 of 2.07 ms. Background noise
requires scanning the recording: roughly 4.6 ms per second in this fixture set.
Exact digital silence is handled immediately. No voice means no ASR POST, result,
history entry or paste. A detected spoken "grazie" remains valid dictation.

## Verification

Python unit and native-resource tests cover recording lifecycle, HTTP warmup,
metadata parsing, correction safety, quota fallback and voice detection. Rust
tests cover settings migration and sidecar usage-file compatibility. Browser E2E
tests exercise start/stop through the real Python engine with mocked audio/HTTP,
no-voice handling, multiline vocabulary persistence and selective correction.
Windows native verification uses a separate application identifier and invented
synthetic audio, with the real saved Groq credential. Generated audio, numeric
evidence, app data and builds stay outside commits; credentials are never logged.

Reproduction tools are `scripts/benchmark_groq_network.py` and
`scripts/benchmark_groq_quality.py`. Live tools read `GROQ_API_KEY` exclusively
from the process environment, stop on failure, pace requests and write numeric
evidence outside the repository. They never load `.env` files.
