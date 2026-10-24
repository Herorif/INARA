# Android build acceptance

Latest accepted build, 24 October 2026: [Order 4 mobile call receipts](MOBILE_CALL_RECEIPTS.md), version 0.1.1-receipts/code 2, four executed JVM tests and fresh strict offline APK/signature audit. [Current QA](qa/mobile-call-receipts-verification.json). Build heap is now 768 MB. The initial 23 October account/artifact below is retained as history.

**Accepted, 23 October 2026:** real dependency recording followed by a clean strict offline debug build, Kotlin/Java compilation, one executed JVM protocol test and successful apksigner verification. [Current execution evidence](qa/android-build-verification.json) includes input/dependency/output hashes and the preserved APK location. Compiled aapt2/javap inspection confirms package `com.inara.companion`, INTERNET plus the app-owned AndroidX signature-only internal receiver permission, and notification acceptance false. No phone or emulator was contacted; release signing and physical device acceptance remain pending.

## Reproduce the build

The validated baseline is JDK 17, Gradle 8.14.6, AGP 8.9.2, Kotlin/Compose compiler 2.1.20, API 35 and Build Tools 35.0.0. Gradle was deliberately updated from 8.11.1 during diagnosis; the other application pins were retained. The official Gradle ZIP SHA-256 was verified. [Gradle release notes](https://docs.gradle.org/8.14.6/release-notes.html), [AGP compatibility](https://developer.android.com/build/releases/agp-8-9-0-release-notes).

```powershell
# Read-only presence check; no network/device/tool execution.
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup-android-local.ps1 -Step preflight

# Normal build: clean, strict verification, offline, no installs.
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup-android-local.ps1 -Step build

# Explicit online recording only when deliberately restoring/updating dependencies.
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup-android-local.ps1 -Step record
```

The setup wrapper sources the generated `.tools/local-env.ps1`. Tools/SDK and Android user state are workspace-local. The working Gradle cache uses a deterministic per-workspace directory in user-temporary storage. If Windows clears it, the offline build refuses; explicitly record/review again rather than silently enabling network fallback. The runner uses one worker, a 768 MB JVM cap, no filesystem watching and in-process Kotlin compilation. These settings reduce build resource use but do not provide a thermal/process sandbox. The execution-policy override affects only the child shell.

Recording executes the same build/tests/signature checks but deliberately reports `accepted_debug_build: false` and `dependency_review_required: true`. A separate normal strict offline run is required after review. The app locks all configurations with strict missing-lock handling; complete locks cover debug and JVM compile/runtime classpaths. All 694 recorded artifacts were SHA-256 compared against cached bytes, and nine direct pinned components were compared against checksum sidecars from Google Maven/Maven Central. Published module filenames were resolved using their declared variant URLs. Repository policy permits Google Maven/Maven Central and the plugin portal for plugins, with project repositories refused.

Checksum review is technical bootstrap review, not signed supply-chain attestation or independent authentication of every transitive artifact. It grants no redistribution/license approval or production identity. [Gradle bootstrap limits](https://docs.gradle.org/current/userguide/dependency_verification.html), [locking](https://docs.gradle.org/current/userguide/dependency_locking.html).

## Evidence contract

`android/build.ps1` verifies exact Java/Gradle pins, disables SDK downloads and runs fixed `:app:clean`, `:app:assembleDebug` and `:app:testDebugUnitTest` tasks. The auditor snapshots Android source/build inputs and itself, requires unchanged inputs and locked dependency records, and records each attempt under a fresh `.runtime/android-build/<UUID>/` directory.

Acceptance requires zero build/signature exit codes, a fresh bounded APK containing compiled manifest/DEX/resources, and fresh JUnit XML containing executed passing protocol-vector tests with no failures/errors/skips. Unsafe/duplicate APK entries, inconsistent counts, stale outputs, missing SHA-256 entries, broad trusted-artifact exclusions and wrong tool versions refuse. Installed [apksigner](https://developer.android.com/tools/apksigner) separately verifies the APK and supplies the signer-certificate digest. APK structure alone is not signature verification.

The accepted APK is 26,367,433 bytes, SHA-256 `a13d17cf7769259816602379e2b83ee46c3299be6db415b8ab12811467cd8550`. The APK, SHA256SUMS, BUILDINFO and original build receipts are copied into `.runtime/android-release-candidate/e60c6fd1-f3b9-443a-bf5b-ca03c1908e54/`; later Gradle cleans do not remove that copy. The debug signer is not a production publisher identity. Receipts are local workflow evidence, not signed attestations or protection against deliberate owner fabrication. APK timestamps/signatures may differ between clean builds; reproducible byte identity is not claimed.

## Failure diagnosis and validation

Seven earlier build attempts are retained. Gradle denied temporary-to-immutable transform renames inside both the original and shortened workspace caches. Updating Gradle alone did not fix it. Ordinary Python/Java rename probes passed; handle inspection found no decisive lock holder. The isolated user-temp cache passed both dependency recording and the subsequent strict offline build. This establishes a working configuration, not the underlying Windows cause. No security settings were changed, caches deleted or temporary transform workspaces manually promoted.

**49 focused Python checks pass:** 25 Android auditor checks, 11 release-tool checks and 13 local-call/setup checks. Scoped Ruff passes. One actual JVM protocol test also passes; it is distinct from the Python fixtures. The debug build warns that `libandroidx.graphics.path.so` cannot be stripped and packages it unchanged; build/signature acceptance still passes. No native-device or release-size acceptance is inferred.

Remaining gates: Fold installation/pairing, actual Compose rendering, Keystore, process death, fold/unfold/IME/accessibility, TLS/revocation/privacy and Doze; physical SIM/personal WhatsApp controls and isolated two-way audio; owned release signing and distribution reviews. Notification acceptance remains false, WhatsApp text/outgoing actions stay excluded, and controlled calls remain scheduled for later. [Deferred work](DEFERRED_WORK.md).
