# Dictation flow review, 2 October 2026

This review covers recent desktop and Android changes through `514972c`,
desktop 1.6.7 and Android preview 0.1.19. It follows microphone capture,
audio preparation, transcription, widget state, and transcript insertion.
Release signing, model selection, and the JSON IPC commands remain unchanged.

## Recent changes reviewed

| Commits | Area | Outcome |
| --- | --- | --- |
| `b140dbe`, `e987cef` | Desktop word-edge padding, pre-roll, and immediate stop feedback | The 220 ms tail remains. The pre-roll did not have an idle microphone stream and could prepend stale callbacks. The stale buffer has been removed. |
| `f56ce96`, `f388e58`, `7c1b134` | Local Parakeet inference, silence trimming, backend status, and result attribution | Parakeet remains the local backend. The shared trim now retains quiet word edges. |
| `2efb4f3`, `7f6fbcb` | Automatic gain and Groq Turbo payload | Desktop gain and the raw meter remain separate. Groq still uses `whisper-large-v3-turbo`. Android now has bounded gain too. |
| `5e55068`, `e8f1dc2`, `864e435`, `765b23b`, `67cc665` | Desktop startup and model preload | The existing startup recovery tests pass. Stopping during model loading now emits `ready` for the current session. |
| `c0a176b`, `7142a9e` | Responsive mobile startup and bounded runtime snapshots | Existing mobile startup tests pass without changing the bridge contracts. |
| `e99bdc6`, `3db45bd` | Desktop clipboard recovery and manual updates | Clipboard recovery tests pass. Installer and updater artifacts have not been exercised on Windows. |
| `1cbb300` | Native transcript recovery, history deletion, and data reset | Native storage contracts remain unchanged. Recovery now also covers failures in the new editor insertion path. |
| `3bbe3a0`, `a40c5e8`, `514972c` | Android JVM test initialization and release variant | `testUniversalReleaseUnitTest` runs successfully with Java 17. |

## Confirmed defects and corrections

### Quiet audio was treated as silence

`trim_cloud_silence` used a fixed amplitude threshold of `0.003` for both
Groq and local inference. A recording below that threshold became empty.
Weak word edges farther than 320 ms from a louder vowel were also removed.
Regression tests reproduced both defects with short and long sample arrays.

The trim threshold is now one PCM16 quantization step, `1 / 32767`.
The existing 320 ms padding remains. Internal pauses are never removed.
This favors speech preservation over smaller uploads. Background hiss may
remain in the payload, and inference can take longer on noisy recordings.
These tests prove sample preservation, not a measured improvement in word
error rate on real speech.

### Desktop readiness preceded microphone readiness

The desktop emitted `listening` before opening `sounddevice.InputStream`.
The widget could therefore invite speech before the microphone was ready.
The event now follows successful stream startup. Failed startup never emits
`listening`, and a stop during model loading returns the current session to
`ready`.

No microphone stream remains open between sessions. Audio spoken before
microphone startup cannot be recovered by this change. Late inactive
callbacks are discarded rather than prepended to another session.
Recording duration comes from the captured sample count, not startup or
teardown wall time.

### Android stopped before capturing weak word endings

Android previously called `AudioRecord.stop()` immediately on user stop.
Normal stop now allows a 220 ms tail, measured with a monotonic clock.
Reads use 512-sample blocks, so the tail can include the final 32 ms block.
Repeated stop requests cannot extend the deadline. Cancellation, shutdown,
and audio-focus loss still stop immediately.

`VoicePcmGain` applies constant gain after capture, with a maximum of 4x
and a 0.98 peak ceiling for amplification. It neither cuts samples nor
filters consonants. Meter values remain raw. The final WAV retains the
sample count, and incomplete file writes fail instead of sending a partial
recording. Duration comes from PCM bytes.

The stop sound now plays after microphone closure. The keyboard marks the
transcript as pending when stop is requested, so an editor change during
the tail does not discard the stopped recording.

### The widget was explicitly allowed on the lock screen

`shouldShowOverlay` returned `true` when the keyguard was locked, and the
window used `FLAG_SHOW_WHEN_LOCKED`. Both behaviors have been removed.
Visibility now requires an interactive screen and an unlocked keyguard
and device. Screen-off, screen-on, and user-present broadcasts trigger an
immediate refresh. An unavailable device hides the widget, cancels its
recording and cloud request, and clears the cached editor.

Recording, copying, and insertion also check device availability. An error
while querying device state denies access rather than showing the widget.

### Widget movement and recovery were coupled to transient views

The overlay now has a 48 dp touch target. A gesture is measured from the
initial press, and a drag never becomes a recording toggle on release.
Movement during recording or processing cannot reposition the widget.
Canceled and multi-pointer gestures cannot become clicks.

The service retains the current widget state and recoverable transcript
when the view is temporarily hidden. Successful copy clears recovery.
Failed copy keeps the recovery button. Screen locking deliberately clears
that state. Android 11 and later exclude system bars and display cutouts
from widget bounds, but not keyboard insets, to avoid keyboard-driven jumps.

The reported movement of another application's widgets was not reproduced.
Traflix does not inject touch gestures into another application. Its drag
path updates only its own overlay window.

### Terminal insertion depended on accessibility text actions

The previous overlay required a text node or a terminal-specific class name,
then attempted accessibility paste. A terminal could receive no text while
the result remained only in history or the clipboard.

On Android 13 and later, the service now requests
`AccessibilityServiceInfo.FLAG_INPUT_METHOD_EDITOR`. It can send the
transcript through the active editor's accessibility input connection,
including when another keyboard is selected. On earlier Android versions,
the overlay can use an active Traflix keyboard connection. Otherwise, the
existing accessibility paste path remains available for compatible editors.

`VoiceTranscriptTarget` captures the package and editor generation. It
rejects a changed editor, a missing connection, a protected field, and
duplicate commits. The legacy node path also refreshes the node and checks
the foreground package before insertion. Failed insertion shows recovery
rather than reporting clipboard-only success.

No Enter key or editor action is generated. Raw `TYPE_NULL` editor
connections and recognized terminal surfaces receive spaces instead of
CR and LF characters. Normal text editors retain multiline transcripts.
The Android accessibility `commitText` API has no delivery acknowledgement.
The widget therefore reports that text was sent, not that the terminal
executed or displayed it. Termius compatibility still requires device testing.

The API contract is documented in the Android references for
[AccessibilityServiceInfo.FLAG_INPUT_METHOD_EDITOR](https://developer.android.com/reference/android/accessibilityservice/AccessibilityServiceInfo#FLAG_INPUT_METHOD_EDITOR)
and [InputMethod.AccessibilityInputConnection](https://developer.android.com/reference/android/accessibilityservice/InputMethod.AccessibilityInputConnection).

### Usage followed the selected provider instead of the result

The desktop hook counted a result as Groq usage whenever the current setting
was cloud, even if the result came from local inference. Usage now follows
the result's `provider`, with a fallback for older sidecars that omit it.
An end-to-end regression test verifies that a local result does not add
cloud usage while the cloud setting is selected.

## Verification limits

| Check | Result |
| --- | --- |
| `python -m pytest src-tauri tests/e2e -q` | 151 tests passed, plus 4 subtests. |
| `:app:testUniversalReleaseUnitTest` | 21 JVM tests passed, with no failures or skipped tests. |
| `npm run build` | TypeScript and Vite production build passed. |
| Python module compilation and `git diff --check` | Passed. |
| `:app:lintUniversalRelease` | Failed on the two existing Android TV manifest errors listed below. |
| Rust tests | Not run. No Rust toolchain is installed. |
| Windows and Android device runtime checks | Not run. No Windows desktop runtime or Android device is available. |

Python unit tests and browser end-to-end tests exercise synthetic audio,
mock Groq transport, history, paste recovery, startup, and provider usage.
Android JVM tests exercise tail deadlines, gesture decisions, input safety,
editor identity, real temporary WAV gain, and existing data-reset behavior.
The TypeScript production build and Android Kotlin compilation pass.

Android lint still reports the existing `MissingTvBanner` and
`ImpliedTouchscreenHardware` errors in the unchanged Android TV manifest.
No release or TV configuration has been changed to hide those errors.

No Rust toolchain is installed in this environment, so Rust tests and the
Windows desktop runtime have not run. `adb devices` reports no connected
device. Microphone behavior, lock-screen transitions, TalkBack, Termius,
and the effect on other apps have not been verified on Android hardware.
No real audio, API credentials, or live Groq requests were used.

The remaining runtime checks are listed in
[Verify the dictation flow](verify-dictation-flow.md).
