# ChatJimmy transcription cleanup

Windows cloud dictation uses ChatJimmy for optional text cleanup after Groq
Whisper transcription. In **Motore IA**, select **Cloud** and enable
**Correzione con ChatJimmy (sperimentale)**. This reuses the existing
`cloudCorrectionEnabled` setting; disabling it skips ChatJimmy entirely.
Android and local dictation do not use this cleanup step.

The endpoint is `https://chatjimmy.ai/api/chat`, with model `llama3.1-8B` and
`topK: 1`. No ChatJimmy key or `.env` file is required. Groq still requires its
own key for audio transcription. Only the transcription and bounded personal
vocabulary are sent to ChatJimmy, including the default spelling “Traflix Voice”.
Groq credentials, cookies, and audio are excluded from that request.

The personal vocabulary is also supplied to Whisper as a recognition hint.
ChatJimmy can propose similar spellings from this vocabulary even when Whisper
reports high confidence. Cleanup skips silence, code-like text, text over 4,000
characters, and dictations shorter than three words. With no vocabulary supplied
to the cleanup function, it retains the original selective confidence/grammar
gate and five-word minimum.

The response is accepted only with a complete successful ChatJimmy stats trailer
and conservative validation. Vocabulary replacements must be textually similar;
other changes retain the existing spelling and agreement restrictions. Numbers,
negations, punctuation, and names outside the vocabulary remain protected.
Unrelated rewrites and changes to word count outside vocabulary replacements are
rejected. This is deliberately conservative and does not guarantee correction of
every recognition error or remove filler words.

Connection and read timeouts are one and two seconds respectively. Errors,
incomplete responses, and rejected edits preserve the recognized text (with the
existing local orthographic cleanup). Rate limits temporarily suspend cleanup.
ChatJimmy usage does not increment Groq token counters. Transcripts and response
bodies are not logged by the corrector.

ChatJimmy is a public demo, currently reachable without authentication, with no
guarantee of continued free access or a stable API. The official Taalas API is a
separate authenticated service. Review [Taalas terms](https://taalas.com/terms-conditions/)
before distributing an integration that relies on the demo.

## Live synthetic probe

Run `py -3 scripts/benchmark_chatjimmy.py --output <path-outside-repository.json>`
to exercise the actual cleanup function with eight invented Italian phrases.
It uses no audio, user transcripts, or credentials. The default is five rounds
with a 3.5-second interval; `--rounds` and `--interval` can adjust this. It stops
on HTTP 429 instead of retrying or bypassing the service limit.

The report separates successful HTTP responses, errors, skipped calls, rejected
edits, and exact expected output. Timing includes the HTTP round trip and local
validation, excluding audio transcription and paste. The first request uses a
new connection; subsequent requests can reuse it. Count a fallback as successful
cleanup only if its output actually matches the expected text.
