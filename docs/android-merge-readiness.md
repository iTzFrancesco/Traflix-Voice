# Android merge readiness

Status: conditional. The Android work on `feat/android-mobile-ime` is ready for
private preview and code review. It is not yet a production-ready Android
release for `main`.

## Decision

Do not merge this branch into `main` as a production release yet.

The code is isolated enough for an integration pull request. A merge is
reasonable only if `main` is explicitly allowed to contain an unsigned,
Groq-BYOK Android preview and the team accepts the remaining release gates.
That is a product decision, not a substitute for the checks below.

The original install failure had a concrete cause: the first Android build
produced `app-universal-release-unsigned.apk`. It has no APK signature and
Android rejects it as an invalid package. Do not distribute that artifact.
Every installable preview must pass `apksigner verify` and use a preview or
release keystore that is kept outside the repository. A debug-keystore APK is
limited to private smoke testing and is not an updater-compatible release for
installations signed with another certificate.

The subsequent Android startup crash had a separate configuration cause. The
desktop configuration contained a hidden transparent `overlay` window, and
Tauri eagerly creates configured windows during startup. Before this fix that
desktop window was inherited by the Android build. The Android override now
replaces the window list with one visible `main` window and excludes the
desktop overlay from the mobile process.

A second startup audit found that the Rust builder still initialized the
desktop clipboard, shell, opener, log, and updater plugins on Android. Those
integrations are now registered only behind `cfg(desktop)`. Android registers
the small `voice-runtime` bridge instead; the unsupported Tauri updater is not
loaded on mobile.

## What is separated

The two application surfaces now have different entry points:

```text
src/App.tsx                  platform selector only
src/desktop/DesktopApp.tsx   Windows dashboard, hotkeys, Python sidecar
src/mobile/MobileApp.tsx     Android Hub lifecycle and native bridge
src/mobile/MobileDashboard.tsx
src/mobile/mobile.css        Android-only Hub styles

src-tauri/src/               shared Rust contracts and desktop shell
src-tauri/src/mobile_runtime.rs
src-tauri/gen/android/       Android Gradle project and Kotlin IME runtime
```

The desktop shell, hotkey runtime, sidecar, tray, and window listeners are
compiled behind desktop platform guards. The Android build uses
`src-tauri/tauri.android.conf.json`, which excludes the desktop Python sidecar,
Windows WebView resources, and the desktop overlay window. The shared code is
limited to settings, statistics, history, usage types, and Tauri command
contracts.

When changing one surface, keep the change inside its surface directory unless
the shared contract really changes. A shared-contract change must be checked
against both desktop and Android builds.

## Verified on this branch

- `npm run build` passes after the desktop/mobile entry-point split.
- `cargo fmt --all -- --check` passes.
- `cargo test --all` passes with 22 tests.
- The Android release build is configured to accept signing values through
  `TRAFLIX_ANDROID_KEYSTORE`, `TRAFLIX_ANDROID_STORE_PASSWORD`,
  `TRAFLIX_ANDROID_KEY_ALIAS`, and `TRAFLIX_ANDROID_KEY_PASSWORD`.
- The Android launcher assets are sourced from `src-tauri/icons/android/`,
  including the Traflix Voice adaptive icon and density-specific images. The
  adaptive background is the dark Traflix canvas rather than white, and the
  manifest declares both `icon` and `roundIcon`.
- The unsigned-artifact failure was reproduced with `apksigner`.
- The signed preview APK verifies with APK Signature Scheme v2, contains
  `arm64-v8a`, `armeabi-v7a`, `x86`, and `x86_64`, and reports package
  `it.traflix.voice` version `0.1.5`.
- The merged Android configuration contains only `main` with
  `transparent=false` and `alwaysOnTop=false`; the desktop `overlay` is not
  packaged as an Android startup window.
- `cpal`/`oboe` remain desktop-only; Android uses the native
  `VoiceAudioRecorder`, avoiding the C++ runtime dependency that caused the
  startup linker crash.
- The Android startup smoke passes on the API 30 x86 emulator across three
  consecutive install-and-launch cycles.
- The Android ABI smoke requires `arm64-v8a`, `armeabi-v7a`, `x86`, and
  `x86_64` in the universal APK so ARM phones such as the OPPO A53s are not
  rejected as incompatible.
- `cargo check --target aarch64-linux-android` passes with the desktop plugin
  registrations excluded from the Android builder.
- The Android release build passes Kotlin compilation, R8, and lint with the
  mobile updater bridge retained in the R8 seeds. It reports versionName
  `0.1.5` and versionCode `1006003`.
- The mobile updater accepts only non-draft `android-vX.Y.Z` releases with the
  exact `app-universal-release.apk` asset. It downloads into the app cache,
  verifies the published SHA-256 and device ABI, and automatically delegates
  installation to Android's package installer after the user grants the
  unknown-sources permission when required.

## Installable preview artifact

The corrected private test preview is published as
[`android-v0.1.5`](https://github.com/iTzFrancesco/Traflix-Voice/releases/tag/android-v0.1.5).
Download `app-universal-release.apk` from that release. Its SHA-256 is:

```text
d6009687c2991ed7a2681ea106190f0dbad0d941e3e97b3b15d34f8eeeb74c44
```

The APK is package `it.traflix.voice`, versionName `0.1.5`, and versionCode
`1006003`. It is signed with the local Android debug keystore for private
download and emulator testing, not with the private-preview or production
certificate. Uninstall an existing preview signed with another key before
installing it.

This is a private test APK. It is suitable for validating the startup fix, not
for production distribution or guaranteed in-place updates.

There is no physical Android device connected to this workspace, so keyboard
activation, microphone capture, `InputConnection` insertion, and OEM
background behavior still need a physical-device pass. The API 30 x86 emulator
has been used for the install-and-launch smoke test.

## Gates before a production merge

1. Install the signed APK on at least one Android 13+ device and test both
   recording modes in a normal text field, browser, messaging app, and a
   password/PIN field.
2. Verify editor changes, keyboard switching, rotation, service restart,
   audio-focus loss, permission denial, offline mode, timeout, rate limit, and
   a retry after a failed commit.
3. Replace or disable the private direct-Groq BYOK path. Production Android
   must use the Traflix gateway with short-lived tokens, quotas, privacy
   disclosure, and a documented data-retention policy.
4. Sign the release with the production-kept keystore and publish a repeatable
   Android CI artifact. Do not commit a keystore or passwords.
5. Complete the Play Data Safety, microphone foreground-service, IME, and
   privacy review. Run the device matrix described in the architecture plan.
6. Decide whether the `REQUEST_INSTALL_PACKAGES` permission is acceptable for
   the distribution channel. Direct APK previews need it for the updater;
   Play distribution requires a separate policy review.

Until these gates pass, label the Android artifact as a private preview and do
not present it as a stable release. The direct BYOK path is especially
important: Android Keystore protects the locally saved key, but it does not
make a client-held provider key suitable for a public distribution model.

## Reproducible checks

From the repository root:

```bash
npm ci
npm run build

cd src-tauri
cargo fmt --all -- --check
cargo test --all
cd ..

pwsh -NoProfile -File scripts/android-abi-smoke.ps1 -ApkPath path/to/app-universal-release.apk
pwsh -NoProfile -File scripts/android-startup-smoke.ps1 -ApkPath path/to/app-universal-debug.apk
```

For a signed local preview, set the four `TRAFLIX_ANDROID_*` variables to a
keystore outside the repository, then run:

```bash
export JAVA_HOME=/path/to/jdk-17
export ANDROID_HOME=/path/to/android-sdk
export NDK_HOME=/path/to/android-sdk/ndk/<version>
export TRAFLIX_ANDROID_KEYSTORE=/path/to/preview.keystore
export TRAFLIX_ANDROID_STORE_PASSWORD=<store-password>
export TRAFLIX_ANDROID_KEY_ALIAS=<alias>
export TRAFLIX_ANDROID_KEY_PASSWORD=<key-password>

npm exec tauri -- android build --apk --ci
```

Do not pass a single `--target` for the downloadable universal APK. A target
such as `i686` is reserved for emulator-only smoke builds and produces an APK
that is not installable on ARM phones.

Validate the generated artifact before sharing it:

```bash
apksigner verify --verbose path/to/app-universal-release.apk
aapt dump badging path/to/app-universal-release.apk
```

If a device already has a build signed with a different key, uninstall that
preview first or install the new artifact without `-r`.

## Merge checklist

- [x] Desktop and Android entry points are separated.
- [x] Desktop-only Rust runtime is platform guarded.
- [x] Android configuration excludes the desktop sidecar and desktop overlay.
- [x] Desktop plugins are excluded from Android startup; mobile updates use a
      dedicated Android bridge and only `android-v*` GitHub releases.
- [x] Launcher icon is Traflix Voice, including adaptive-icon resources and a
      non-white background.
- [x] An installable signing path exists without committing credentials.
- [ ] Physical Android installation and IME flow are verified.
- [ ] Production gateway replaces direct Groq BYOK.
- [ ] Production signing, Android CI, privacy review, and device matrix are
      complete.

Current recommendation: keep the branch open for review and private testing;
merge only as an explicitly experimental integration. For the normal primary
branch, wait for the unchecked gates.
