# Parakeet long-dictation performance

The local Parakeet adapter now processes long dictations in chunks near quiet
pauses. This addresses the disproportionate increase in inference time when
the previous adapter sent an entire long capture to one native stream.

Chunks target 20 seconds. A boundary requires at least 160 ms of quiet audio;
the quiet threshold scales with the 90th percentile of frame peaks, with an
absolute ceiling of 0.001. Each new boundary receives 120 ms of digital
context. That context corrected word substitutions and omissions observed
in the first chunking experiment. When no suitable pause exists, a larger
stream preserves continuous speech.

Zero-only pauses longer than one second are compacted to 640 ms, retaining
320 ms on each side. Every nonzero sample is preserved, including samples
below PCM16 resolution. The original capture duration is still reported in
the single final IPC result. An active transcription retains its native
recognizer until all its chunks finish, including when the UI unloads the
model during processing.

Measurements on Windows used an Intel Core i5-11600K, six inference threads,
sherpa-onnx 1.13.7 and the existing Parakeet TDT 0.6B v3 INT8 files. Italian
fixtures were generated with Microsoft Elsa Desktop outside the repository.
The controlled chunking run alternated whole-clip and production inference
using the same native sessions. Medians below cover three measured runs per
mode after warmup. Gain, edge preprocessing and local result generation are
included; capture, Rust, overlay and clipboard work are excluded.

| Words | Audio duration | Whole clip | Chunked | Latency reduction | WER before | WER after |
| --- | --- | --- | --- | --- | --- | --- |
| 211 | 96.42 s | 7.03 s | 5.30 s | 24.7% | 0.47% | 0% |
| 221 | 99.28 s | 7.50 s | 5.41 s | 27.8% | 1.36% | 0.45% |
| 432 | 195.70 s | 21.56 s | 12.39 s | 42.5% | 1.62% | 0.69% |

An eleven-repetition short-clip check measured 0.284 s before and 0.287 s
after for ten words, and 1.147 s before and 1.146 s after for 47 words.
These inputs keep one native stream and showed equivalent WER.

The final digital-pause compaction leaves these three inputs unchanged. A
separate final run checked five variants with two measured repetitions per
mode after warmup. Quiet speech and light background noise retained the
speed improvement. Strong background noise and deliberately continuous
speech used a single stream and showed no material improvement. A 211-word
fixture containing an added 12-second digital pause improved from 13.66 s
to 5.92 s, with WER falling from 0.95% to 0%. All five variants passed the
guard against a WER increase.

An accelerated synthetic capture replay also exercised the real Python
sidecar and native model through `init`, `transcribe`, `stop`, `unload_model`,
`get_status` and `quit`. The 195.70-second fixture used ten chunks, produced
one `processing` and one `result` event, preserved the original duration and
final word, and completed 12.54 seconds after stop. Model unload and clean
process exit succeeded. This replay replaced the microphone input stream;
it does not verify physical microphone capture or desktop interaction.
The manual desktop check returned `Computer Use native pipe is unavailable`,
including after retry and session reset, and remains outstanding.

The Python suite passes with 221 tests, 134 subtests and two skipped tests.
Regression coverage includes sample preservation,
quiet speech with a loud click, uncertain noisy pauses, late first pauses,
word order and repetitions, context padding, unload during active inference,
digital pause compaction and original result duration.

To repeat a comparison, prepare mono PCM16 WAVs at 16 kHz and a JSON manifest
outside the repository. Reference text is used for the existing Italian/Latin
word-error scorer. Relative WAV paths resolve from the manifest directory.

```json
[
  {"file": "short.wav", "text": "Reference transcript for the short fixture."},
  {"file": "long.wav", "text": "Reference transcript for the long fixture."}
]
```

```powershell
py scripts/benchmark_parakeet.py `
  --models-dir "$env:APPDATA\it.traflix.voice\models" `
  --manifest "$env:TEMP\parakeet-fixtures\manifest.json" `
  --reps 3 --warmup 1 --min-long-speedup 1.25 `
  --json-out "$env:TEMP\parakeet-fixtures\comparison.json"
```

The benchmark uses existing models and local fixtures. Its default quality
guard rejects any increase in normalized WER. A speed guard applies to
fixtures that produce multiple chunks. Numeric reports include individual
timings and do not include reference or recognized text. The benchmark's
whole-clip mode reproduces the adapter used in Windows 1.7.6.

The native `decode_stream` profile includes both encoder inference and token
decoding, as shown by the [Sherpa-ONNX Nemo implementation](https://github.com/k2-fsa/sherpa-onnx/blob/v1.13.7/sherpa-onnx/csrc/offline-recognizer-transducer-nemo-impl.h).
The profiling evidence identifies the native inference call as the dominant
cost; it does not independently time the encoder and token decoder.
