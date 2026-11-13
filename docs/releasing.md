# Release Traflix Voice on GitHub

Use this guide before changing application versions, creating release tags, or
publishing Windows or Android builds. A release is built and published by
GitHub Actions. Do not build a release locally.

## Choose a normal push or a release

A request to push changes to GitHub means a normal code push. Do not bump a
version, create release tags, or start a local build unless the user asks for
an updated release.

The normal CI workflow in `.github/workflows/ci.yml` still runs automatically
for pushes to `main` and pull requests targeting `main`. It checks the code
and builds a Windows MSI as a workflow artifact. That CI artifact is not a
GitHub Release and does not update installed applications.

Treat a request for an updated build as a release request for both Windows and
Android unless the user names one platform. Prepare small, focused commits,
push the approved changes, and let the tagged GitHub Actions workflows build
and publish the installable releases. Do not run the release build on the
developer's computer.

## Keep the platform versions separate

Windows and Android have independent version numbers because each platform has
its own release channel.

| Platform | Version files | Release tag | Published artifact |
| --- | --- | --- | --- |
| Windows | `package.json`, `package-lock.json`, `src-tauri/tauri.conf.json`, and `src-tauri/Cargo.toml`, and `src-tauri/Cargo.lock` | `vX.Y.Z` | Signed MSI and `latest.json` |
| Android | `src-tauri/tauri.android.conf.json` (`version` and `bundle.android.versionCode`) | `android-vX.Y.Z` | Signed `app-universal-release.apk` |

Determine the base from the latest **published release in the platform's own
channel**. For Windows, read GitHub's published stable release (`gh api
repos/{owner}/{repo}/releases/latest --jq .tag_name`). For Android, use the latest
published `android-vX.Y.Z` prerelease that contains the signed APK. Local files,
commit titles, bare tags, drafts, cancelled workflows and unpublished attempts
do not consume a release number.

Stay on the current Windows `major.minor` series by default. Increment only the
patch, exactly once, for compatible fixes and features. The user's current
instruction is to remain on **1.8**: published stable **1.8.3 → 1.8.4** for this
release. Do not automatically advance to 1.9 or 1.10 because features were added.
A minor or major series change requires an explicit user request. Even then,
advance exactly one level from the published base; never skip an intermediate
series because a version appeared in an internal commit or an aborted attempt.

Android has its own published sequence. Keep its `versionCode` strictly higher
than every published APK. The latest published Android preview is `android-v0.1.35` with
versionCode `1006033`; this release increments to `0.1.36` / `1006034`. A
cancelled, unpublished attempt does not consume a release version.

For a Windows version bump, run the repository script with the new version:

```powershell
npm run bump -- 1.8.4
```

The script requires authenticated GitHub CLI access, reads the latest published
stable release and rejects skipped versions before editing files. Patch is the
default. Only after an explicit user request may `--minor` or `--major` be added.
It updates Windows version files and both `package-lock.json` and
`src-tauri/Cargo.lock` without changing dependency versions. Review all of those changes before committing them. Do
not use this script to bump Android; it does not update the Android version or
`versionCode`.

For Android, edit `version` and `bundle.android.versionCode` in
`src-tauri/tauri.android.conf.json`. Keep the new `versionCode` above the
previous release. For a paired release, update both platform versions in the
same release change. The version strings do not need to match.

## Publish a Windows release

The Windows release workflow in `.github/workflows/release.yml` runs when you
push a tag matching `v*`. It checks the Rust and Python code, builds and signs
the MSI, generates the updater manifest, and creates a GitHub Release. The
release tag must exactly match the version in `src-tauri/tauri.conf.json`.

The updater manifest is `latest.json`, not `release.json`. The release workflow
generates it with `scripts/generate-updater-manifest.mjs` and uploads it with
the MSI and its `.sig` signature. The Windows app reads the stable manifest
from the `latest` release. Keep the manifest name, URL, signature, and platform
keys compatible with the Tauri updater.

The Windows workflow needs the `TAURI_SIGNING_PRIVATE_KEY` GitHub Actions
secret. Never commit the key or print it in logs.

## Publish an Android release

The Android release workflow in `.github/workflows/android-release.yml` runs
when you push a tag matching `android-v*`. It builds a signed universal APK,
runs Android JVM tests, verifies the APK signature, and checks that its
`versionName` matches the tag. It publishes the APK as a GitHub prerelease
with the exact name `app-universal-release.apk`.

The Android updater reads GitHub Releases and accepts only the
`android-vX.Y.Z` tag family and the expected APK asset. It does not read
`latest.json` or `release.json`. Keep the tag family and APK asset name stable.
The updater uses the SHA-256 digest exposed for the GitHub Release asset when
GitHub provides one.

The Android workflow needs these GitHub Actions secrets:

- `TRAFLIX_ANDROID_KEYSTORE_B64`
- `TRAFLIX_ANDROID_STORE_PASSWORD`
- `TRAFLIX_ANDROID_KEY_ALIAS`
- `TRAFLIX_ANDROID_KEY_PASSWORD`

Keep the keystore and passwords in GitHub Actions secrets. Do not add them to
the repository or include them in logs.

## Release both platforms

For the default updated-build request, publish Windows and Android from the
same approved commit. The two workflows use different tags and may finish at
different times.

1. Read this guide and the repository's `AGENTS.md` instructions.
2. Finish the changes on the approved release target. Keep each commit focused
   so reviewers can see the work in small steps. Do not combine unrelated work
   into a single commit or squash the release history into one commit.
3. Read the latest published release in each channel and update each version
   exactly once using the rules above. Increase Android's `versionCode` only
   relative to published APKs.
4. Push the commits to the existing target branch. Do not create a secondary
   branch unless the user asks for one.
5. Confirm that the release source is the approved commit on `main` and that
   the required GitHub Actions secrets exist.
6. Create one tag for each platform at that same commit. Replace the example
   versions with the versions in the configuration files:

   ```powershell
   git tag -a v1.8.4 -m "Traflix Voice 1.8.4"
   git tag -a android-v0.1.36 -m "Traflix Voice Android 0.1.36"
   git push origin v1.8.4 android-v0.1.36
   ```

7. Follow both tagged workflows in GitHub Actions. Resolve failures before
   calling the release complete. Rerun a failed workflow when its tag and
   source are correct; use a new version and tag if the release contents must
   change.
8. Check the Windows Release for the MSI, `.sig`, and `latest.json`. Check the
   Android prerelease for the signed `app-universal-release.apk`.

If the user asks for only one platform, update and tag only that platform. Do
not move or reuse a published tag. Choose a new version for corrected release
contents.

## Correct an unpublished release attempt

Published releases and their tags are immutable: use a new patch for changed
published contents. An internal or cancelled attempt never justifies skipping
versions on the published channel.

When the user explicitly corrects an unpublished version or its source commit:

1. Cancel every workflow for the incorrect release attempt and confirm it stopped.
2. Verify that neither a Release/prerelease nor installable release assets were
   published for those tags. If assets were published, do not reuse their versions.
3. Remove the erroneous unreleased tags, retaining the commit history.
4. Correct the files from the published channel baseline. Retain the selected
   unpublished Android version/code when no APK was published.
5. Create fresh release tags at the corrected main commit and run both workflows.

This exception requires that explicit correction request; it is not permission
to retag an already published release or replace an installer users received.

## Preserve the update contracts

- Keep the Windows updater endpoint and `latest.json` schema compatible with
  `src-tauri/tauri.conf.json` and Tauri's updater plugin.
- Keep the Android tag format and APK asset name compatible with
`src-tauri/gen/android/app/src/main/java/it/traflix/voice/MobileUpdatePlugin.kt`.
- Do not change signing, updater endpoints, release visibility, or tag rules
  without reviewing the affected client update code and GitHub Actions
  workflow.
- Never include credentials, keystores, local build output, or user data in a
  commit or release asset.
