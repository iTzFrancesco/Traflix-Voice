# Cloud and local dictation review, 13 October 2026

This review covers the Windows desktop flow at version 1.7.10. It examines
capture, session ownership, stop ordering, local model lifetime, cloud request
preparation, optional correction and speech filtering, IPC, and frontend result
delivery. Android behavior and release configuration are outside this patch.

## Plan and implemented changes

1. Reproduce transcript loss and unsafe correction before editing production code.
2. Retain audio blocks that finish copying during stream shutdown for both providers.
3. Keep the cloud correction setting independent of the speech-filter setting.
4. Restrict correction substitutions and retain punctuation at its original word boundaries.
5. Run regression tests, the full desktop/frontend suite, real local inference,
   live Groq comparisons, and desktop runtime checks.

### Audio capture and stop

Rust polls global shortcuts and forwards their events to the frontend. The
frontend sends line-delimited commands to the Python sidecar. A dedicated
capture worker owns a session queue; a separate, serial worker performs inference.
Stop immediately reports processing and retains a 220 ms capture tail.

The callback copies each mono block before enqueueing it. If that copy overlaps
the stop timer, the sentinel can enter the queue first. The capture loop then
exits before consuming the final block. A deterministic test reproduces this
ordering with a real thread and queue, holding the array copy until stream closure.
The original code loses 512 samples, or 32 ms at 16 kHz.

The patch drains the session queue after the input stream closes. It retains
completed blocks in their existing order, including a clip whose only block
finishes after the sentinel. A second capture verifies session isolation.
It adds no callback lock and does not alter the stop tail, gain, trim, padding,
sample rate, model parameters, or chunk boundaries.

The installed sounddevice context manager calls stop and close on exit. The
[PortAudio API](https://portaudio.com/docs/v19-doxydocs/portaudio_8h.html)
defines stop as terminating stream processing. Native driver failures remain
outside the simulated stream test; sounddevice ignores close errors by default.

### Cloud filtering and correction

Groq Whisper Turbo produces the recognition. Optional detailed metadata drives
speech filtering and selective correction. The existing correction helper also
discarded any transcript marked as no speech, even with the speech filter disabled.
That coupling could discard a legitimate short or quiet utterance such as the
synthetic test response "Grazie".

Filtering now happens explicitly in the transcription pipeline only when enabled.
The correction helper preserves its input when metadata suppresses correction.
The existing positive voice-detector override and usage accounting are retained.
Tests cover all four correction/filter combinations and unavailable voice detection.

The previous edit-distance guard accepted different words with similar spelling,
including `francesco` to `francesca` and `trasmettere` to `trasmetterle`. It also
accepted changed mathematical operators and a statement converted to a question.
The patch accepts the existing explicit typo mapping and contextual agreement
edits. Other speculative word substitutions retain the original recognition.
Punctuation and operators are compared in each gap between words, preventing
both substitution and relocation. The tradeoff is fewer automatic spelling fixes.

### Local inference and delivery

Parakeet model snapshots already pin the native recognizer through capture and
queued inference. Existing tests cover unload, provider changes, and shutdown.
Those mechanisms remain intact. The frontend continues to consume the same
statuses, paste successful text, and save history and statistics.

One pre-existing issue remains: the local 60-second timeout reports error and ready,
but executor context exit still waits for native inference. Changing it to
nonblocking shutdown would permit overlapping native work and would not recover
a hung recognizer. A separate design is needed for a reliable hard timeout.
This patch does not claim to solve that issue.

## Verification evidence

- Before editing: 234 Python tests passed, two optional live benchmarks skipped.
- New regression tests failed on the original code for lost callback samples,
  the correction/filter coupling, and unsafe substitutions.
- Before the subsequent motion follow-up, the combined Python and browser suite
  passed: 269 tests and 145 subtests,
  with two optional live benchmarks skipped.
  Browser tests execute the real React code and Python pipeline with controlled
  native/HTTP boundaries; they do not prove physical microphone or clipboard behavior.
- `npm run build`, Python compilation, and `git diff --check` passed.
- A second source review found no actionable regression in the patch.

The user authorized sending the supplied 28.1135-second audio clip to Groq.
The production local and cloud inference paths were run before and after editing,
using the installed Parakeet model and configured Groq credential. Credentials
and transcript text were not printed or added to the repository. Numeric evidence
and hashes are retained outside the repository.

| Recognition path | Before words | After words | Text hash identical |
| --- | ---: | ---: | --- |
| Local Parakeet | 49 | 49 | Yes |
| Cloud, correction disabled | 55 | 55 | Yes |
| Cloud, correction enabled | 55 | 55 | Yes |

These comparisons prove stability on this sample, not general recognition accuracy.
The supplied clip has no verified reference transcript. Single-run timings vary
and are not used to claim an inference speedup.

A separate 35-word synthetic Italian fixture was generated with the installed
Windows speech synthesizer. Real Parakeet inference returned identical text with
zero normalized word error rate before and after in normal, low-amplitude, and
edge-silence variants. This is a controlled regression fixture, not a benchmark
of natural speech across speakers or microphones.

The existing 20-iteration capture/IPC benchmark with eight synthetic blocks and
prewarming measured stop-to-request median 231.15 ms before and 233.89 ms after;
p95 was 234.87 ms and 235.51 ms. It includes the same 220 ms tail and excludes
real network and inference time. These Windows measurements do not establish a
statistically significant speed change.

## REA and desktop runtime coverage

REA identified the original debug PE executable by SHA-256:
`8af7b7e036bcfe7c53f196818e2a442f658030c69fec09b316bc1dbef490ea5b`.
Its resource evidence is
`ev_382079e860f6cd5fb0699d2e6991bb017745322c0517835898f3641292167e2b`.
Resource inspection establishes artifact identity, not transcription behavior.

A development executable was compiled and launched with the current source.
REA discovered its main and overlay WebViews and passively inspected the main
page through the loopback WebView2 debugging endpoint. Evidence
`ev_3fd32e7c118b70fb31be3941961538f4603a8f61845c363882883067f0e4afcf`
observes the DEV page, DOM and script inventory. Accessibility text, console text,
storage values, credentials, and transcript content were excluded.

REA process capture reports an explicit unsupported Windows capability. The
Windows Computer Use helper also reports that its native pipe is unavailable.
The application was launched and its sidecar restarted to load the patch.
Automated desktop input remains unavailable. The user subsequently tested the
running app and reported that both cloud and local transcription work. No
separate confirmation of external-editor paste or hold-to-speak was supplied;
those flows were not changed by this patch.

A further capture probe used the physical Windows microphone and real
sounddevice InputStream. It deliberately held the first callback's array copy
through the stop sentinel and native stream closure. With both provider choices,
the baseline dropped that 512-sample block and the patched engine retained it.
The probe bypassed inference and collected only numeric counts and status names.
Samples were discarded in memory, with no upload or audio persistence. This
strengthens the stream-closure evidence, while not testing hotkey or clipboard UI.

## Widget refinement after desktop feedback

The user requested a softer entry and a slightly smaller widget after confirming
both transcription providers in the app. The entry previously translated 8 px,
scaled from 0.92 to an overshoot of 1.018, and applied blur. It now translates
3 px with a monotonic scale from 0.985 to 1 and no blur or bounce, over 280 ms.
The recording-to-processing transition retains its existing timing and easing.

The visual pill uses a 40 px layout height instead of 42, with a 24 px logo
instead of 26, smaller internal spacing, and 28 px audio bars instead of 30.
The user found that first reduction insufficiently noticeable. The outer wrapper
now scales the whole widget to 90%, giving a visible 36 px height and reducing
its width as well. Entry transforms remain on the inner pill, independent of
the wrapper scale. The processing state hides the development badge slot to
keep the complete status label visible within the existing 170 by 50 native window.

The collaborative browser measured the new entry at selected animation times,
confirming scale never exceeds 1 and vertical movement settles without reversal.
REA also captured the updated overlay in the actual app's WebView2 viewport,
evidence `ev_989485a05370be4807d2376a478d5323bc98eb4c40c1a1e80f5d845e47f28b99`.
Existing DPI, clipping, repeated-status and rapid-restart tests remain in place;
new tests cover gentle motion and full processing-label visibility.
After the final wrapper-scale adjustment, all 17 overlay tests and the frontend
build passed again. The native overlay screenshot was visually inspected.

### Idle-to-recording continuity and hover cleanup

The visible idle widget now keeps its outer pill visible while its name
collapses and the separator/audio bars expand. It no longer replays the outer
appearance animation when recording starts in always-visible mode. The rule
that disabled internal transitions during appearance was removed, so the
recording-only mode also retains intermediate content states. Native appearance,
exit reversal, duplicate statuses, immediate recording feedback and sounds keep
their existing handling. Reduced-motion preferences settle the inner layout
without a spatial transition.

The hover hint was positioned below the pill and extended past the native
50 px viewport. That produced the clipped white writing reported in the supplied
screenshot. The external hint and its unused version-loading code were removed;
dragging and opening the main window remain available.

The new regression cases failed before the fix and passed after it. In the
collaborative browser, at 120 ms the name was still 21.70 px wide while the audio
area had expanded to 16.24 px. The pill stayed at opacity 1 throughout, confirming
a continuous transition rather than a slide-like replacement. A real hover in
that browser left every visible direct child inside the native viewport.
REA captured the updated native overlay, evidence
`ev_383002f3937a5f0ea214572e33af6bbf3d73ead16e91046f89e2abe167c1a56e`.

All 33 browser E2E tests passed, including 22 overlay tests. The frontend build
and diff whitespace check passed. Backend code was unchanged in this follow-up.

This investigation preserved the release workflows, updater contracts and
signing configuration. Publication follows [the release guide](releasing.md).
