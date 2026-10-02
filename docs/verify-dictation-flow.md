# Verify the dictation flow

Use a test editor, synthetic text, and a non-production terminal session.
Do not record passwords, tokens, or real user data. Live Groq tests send
audio off the device and consume provider quota.

For the reasons behind these checks, see the
[dictation flow review](dictation-flow-review-2026-10-02.md).

## Run automated checks

1. Run `npm run build` from the repository root.
2. Run `python -m pytest src-tauri tests/e2e -q` with NumPy, HTTPX, pytest,
   Playwright, and its Chromium browser installed.
3. From `src-tauri/gen/android`, run
   `./gradlew :app:testUniversalReleaseUnitTest` with Java 17 and the Android SDK.
4. Run `./gradlew :app:lintUniversalRelease` from the same directory.
   Record any errors. The existing Android TV manifest errors are unrelated
   to the dictation changes.
5. On Windows with the Rust toolchain installed, run `cargo test` and
   `cargo clippy -- -D warnings` from `src-tauri`.

## Compare Groq client preparation

These benchmarks use synthetic audio and simulated responses. They do not
measure Groq inference or real network latency.

1. Before changing the Python pipeline, save unchanged copies of
   `src-tauri/whisper_engine/audio.py`, `transcriber.py`, and `engine.py`
   in an external baseline directory.
2. Run `python scripts/benchmark_groq_rounds.py --baseline-dir BASELINE_DIR
   --iterations 201 --output EXTERNAL_DIR/python-rounds.json` from the
   repository root. Replace both directory placeholders with actual paths.
   The command compares 20 payload, 20 trim, and 20 local pipeline profiles.
3. Run `python scripts/benchmark_groq_gain.py --baseline BASELINE_DIR/audio.py
   --output-dir EXTERNAL_DIR/gain --repeats 201` for 20 exact-bit gain profiles.
   Use a new output directory to keep earlier measurements.
4. Run `python scripts/benchmark_cloud_latency.py --warmup 2 --iterations 20
   --blocks 8 --prewarm --output EXTERNAL_DIR/latency-short.json` to check
   production IPC and worker latency, including the unchanged stop tail.
5. Repeat with `--blocks 5625` for three minutes of synthetic PCM.
6. Repeat both latency checks with `--baseline-dir BASELINE_DIR`.
   Compare medians and p95 values, not a single fastest sample.
7. Run the upload benchmark on a standalone JDK 17 with an installed Kotlin
   compiler and local Kotlin, JUnit 4, and Hamcrest jars:

   ```bash
   python scripts/benchmark_android_groq_upload.py \
     --java-home /path/to/jdk-17 \
     --kotlinc /path/to/kotlinc \
     --test-classpath "KOTLIN_STDLIB_JAR:JUNIT4_JAR:HAMCREST_JAR" \
     --scratch-dir /absolute/external/scratch-directory \
     --output-dir /absolute/external/evidence-directory
   ```

   Replace the jar placeholders with local paths. Use the OS classpath separator,
   which is `:` on Linux and `;` on Windows. If you have compiler jars instead
   of `kotlinc`, run the script with `--help` and use `--compiler-classpath`.
   The runner downloads nothing and checks 20 profiles against a loopback server.
   It sends no credentials and never contacts Groq. Keep output outside the
   repository and use a new evidence directory for each run.
   This JDK-only server is separate from Android's unit-test compiler.
8. Repeat the hardware checks below. Mock HTTP results do not prove microphone,
   clipboard, terminal delivery, or live service performance.

## Check desktop word boundaries

1. Launch the desktop application on Windows.
2. Select Groq and a fixed transcription language.
3. Start dictation with the main window focused.
4. Wait for the listening indication, then say a short synthetic sentence.
5. Repeat with a quiet first word, a quiet final word, and an internal pause.
6. Stop on the final consonant. Check that the transcript retains the final word.
7. Repeat while another application is active.
8. Repeat in hold-to-speak mode.
9. Repeat with the local Parakeet provider.
10. Unload the local model, then start and immediately stop a dictation.
    Check that the UI returns to ready rather than remaining in processing.
11. Repeat with an unavailable microphone. Check that listening never appears
    and that a subsequent valid session can start.

## Check Android lock-screen behavior

1. Open Traflix and enable its accessibility widget.
2. Open a text editor and confirm that the widget appears.
3. Turn the screen off. Confirm that the microphone indicator disappears.
4. Wake the phone without unlocking it. Confirm that the widget is absent.
5. Unlock with each method supported by the device. Confirm that the widget
   returns outside the Traflix activity.
6. Lock the phone during recording. Confirm that recording stops and no text
   is inserted after unlock.
7. Lock during a cloud request. Confirm that no late result reaches the lock
   screen, clipboard, or an unrelated editor.

## Check widget gestures and recovery

1. In toggle mode, drag the idle widget. Confirm that release does not start
   recording and that its position survives a temporary hide.
2. Tap with small finger movement. Confirm that recording starts once.
3. Move your finger across the widget while recording. Confirm that the widget
   stays in place and the movement does not become a stop tap.
4. Stop with a normal tap. Confirm immediate processing feedback and a single
   stop sound after microphone closure.
5. Repeat with hold-to-speak, touch cancellation, and a second finger.
6. Open and close the keyboard, rotate the device, and check widget bounds.
   Confirm that no other app's widgets or layout move because of the overlay.
7. Change editors after stopping but before the result arrives.
   Confirm that the result is offered for recovery rather than inserted into
   the replacement editor.
8. Hide the overlay temporarily and return. Confirm that its processing or
   recovery state is retained.
9. Copy a recoverable transcript. Confirm that successful copy clears recovery
   and that failed copy does not lose the recovery action.
10. Enable TalkBack and larger fonts. Check the microphone and copy actions,
    state descriptions, and 48 dp touch targets.

## Check Termius and custom editors

1. On Android 13 or later, enable the Traflix accessibility service.
2. Open a disposable Termius session with an active keyboard connection.
3. Keep Gboard selected and dictate harmless synthetic text through the widget.
4. Confirm that the text reaches the terminal once, without an added Enter.
   Do not use a production shell or dictate executable commands for this test.
5. Change the terminal session or editor during transcription. Confirm that
   Traflix offers recovery instead of inserting into the replacement target.
6. Repeat with the Traflix keyboard selected.
7. On Android 12 or earlier, select the Traflix keyboard for terminal dictation.
8. Repeat in a normal text editor. Confirm that standard insertion still works
   and that password and phone-number fields reject dictation.
9. With a test transcript containing CR or LF, check a raw `TYPE_NULL`
   connection. Confirm that automatic insertion sends spaces, not line breaks.
10. If the terminal exposes neither an input connection nor accessibility paste,
    confirm that recovery remains available and that no touch gestures are
    injected into the terminal.
