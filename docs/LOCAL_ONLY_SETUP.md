# Local-only Android and call setup

Owner decision, 23 October 2026: resume Android/call-bridge setup, use local-only voice, Samsung Fold 8 (owner-reported), controlled test calls later. Downloads/build setup are authorized; live answering, phone permissions/pairing and physical call tests are not performed automatically. Keep the existing SIM and personal WhatsApp accounts. All WhatsApp text actions and outgoing calls remain excluded.

## Installed local voice baseline

The optional environment uses Vosk 0.3.45 with `vosk-model-small-en-us-0.15`, sounddevice 0.5.6 and the installed Windows SAPI speech engine. Recognition accepts 16 kHz mono PCM and speech returns 24 kHz mono PCM. Model files are loaded explicitly from `.tools/local-voice/`; there is no automatic model download or cloud fallback during calls. The live CLI and worker now select this local mode explicitly and pass no provider key/model. The historical cloud adapter remains separate and is not used by this route.

This baseline is **structured English message-taking**, not a general conversational local LLM. INARA identifies itself, asks for name/reason/message/callback details, reads them back and requires yes/no confirmation. Caller text is bounded literal data with no tool/owner-memory authority. Initial audio is half-duplex: wait until INARA finishes speaking before replying. Natural interruptions, multilingual quality and a small conversational local model remain future measured work, after the physical bridge is proven. A confirmed dialogue transcript does not authenticate caller identity or establish delivery to the owner.

All inference is local. Initial tool/package/model acquisition requires network downloads during the explicitly requested setup. The Vosk model's observed archive SHA-256 is `30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498`; the upstream download did not provide an independent signed digest, so no signed provenance/redistribution approval is claimed. Keep its review separate from existing controller/desktop ledgers.

Actual in-memory acceptance generated “Please leave a message for the owner.” using Windows speech and recognized the same phrase with Vosk. No microphone/speaker or phone call was used. Native synthesis needs the normal Windows user context; the restricted execution sandbox could not access its voice engine, while the authorized normal-context check succeeded. Caller acoustics, accents, noisy audio, timing and endpoint isolation remain unverified.

```powershell
.venv/Scripts/python.exe scripts/call-bridge.py preflight
.venv/Scripts/python.exe scripts/call-bridge.py devices
```

These check setup/endpoint metadata and do not open audio streams or answer. **Order 2, 24 October:** [shared core admission](CALL_ADMISSION.md) is implemented, including local zero-cloud-allowance receipts and recurring lifecycle/resource authorization. The old standalone `run --live` path now refuses with `call_core_required`; a future controlled-test path must use the core and a trusted physical-acceptance verifier. No verifier is enrolled and public live answering remains off.

## Android development environment

Latest, 24 October: [Order 4 protected receipts](MOBILE_CALL_RECEIPTS.md) has a fresh accepted strict offline APK with four JVM tests, version 0.1.1-receipts/code 2. The Android heap is now 768 MB and actual compilation passes; the model-loading guard remains unchanged and its benchmark remains owner-deferred. Earlier build accounts below are historical.

Workspace-local setup uses JDK 17, Gradle 8.14.6, Android command-line tools 16.0, API 35 and Build Tools 35.0.0. These are the project's compatibility pins, not a newest-version claim. Downloads/checksums are recorded under `.tools/local-setup/`; Java/Gradle use published SHA-256 and the Android command-line archive uses Google's repository SHA-1 plus a recorded local SHA-256. No global PATH, SDK variable or persistent execution-policy change is needed.

The setup script creates `.tools/local-env.ps1`. SDK and Android user state remain inside `.tools/`. Gradle uses a deterministic per-project directory under the current user's temporary directory (`inara-gradle-<workspace hash>`), because real AAR transform renames failed inside this workspace but succeeded there. The helper computes the path when setup runs; no global environment is changed. Windows may clear temporary storage. If dependencies are missing, the strict offline build refuses; explicitly repeat recording/review rather than silently enabling online fallback. Existing system proxy settings are applied to these development tools only; no proxy credentials are copied. SDK logs remain under `.runtime/local-setup/`. The runner uses one Gradle worker/768 MB, disables filesystem watching and uses the Kotlin compiler in-process to avoid leaving a separate Kotlin daemon behind.

```powershell
# Explicit setup/download operations; never run during normal assistant startup.
.venv/Scripts/python.exe scripts/setup-local-tools.py toolchain
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup-android-local.ps1 -Step sdk

# First resolved dependency capture, followed by review of actual lock/checksum records.
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup-android-local.ps1 -Step record

# Normal subsequent build is strict and offline.
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup-android-local.ps1 -Step build
```

The execution-policy override applies to that child shell only. Dependency recording is not accepted build status; review actual repository origins/checksums before the normal strict offline build. See [Android acceptance](ANDROID_BUILD_ACCEPTANCE.md) and the current [setup evidence](qa/local-only-setup-verification.json) for actual results. Debug build/signature evidence never implies release signing, actual installation or device acceptance. Notification acceptance remains false.

## Actual Android outcome, 23 October 2026

**The debug build is now accepted.** The initial four Gradle 8.11.1 attempts and three further controlled workspace-cache attempts failed on temporary AAR transform renames. A short workspace path and Gradle update alone did not resolve it. Gradle 8.14.6 with an isolated user-temp cache completed recording and a separate clean strict offline build. The Windows root cause remains unproven. Both ordinary Python and Java rename probes worked; no cache was deleted/manually promoted and no security setting was changed.

Real dependency locks now cover debug and JVM compile/runtime classpaths. All 694 verification entries match cached artifact SHA-256 values; the nine direct pinned components also match upstream Google Maven/Maven Central checksum sidecars. This is technical bootstrap review, not signed supply-chain provenance or redistribution/license approval for every transitive dependency.

The recording run compiled Kotlin/Java, executed the JVM protocol test and verified the debug signature, while correctly withholding accepted-build status. The subsequent normal build passed offline with strict verification and unchanged source/dependency records: **one executed JVM test, 26,367,433-byte APK and `accepted_debug_build: true`**. 49 focused Python checks and scoped Ruff pass. [Current build QA and preserved APK location](qa/android-build-verification.json); the earlier [local-setup QA](qa/local-only-setup-verification.json) remains a historical failure record. The debug APK and receipts are copied into a separate `.runtime/android-release-candidate/<run-id>/` directory so future clean builds do not remove them.

Debug signing does not establish release signing, installation, Compose/device behavior or phone-call capability. No phone/emulator was contacted. Notification acceptance remains false. Shared live admission/availability source integration is now complete; protected mobile receipt sync and a real physical-acceptance verifier remain pending. Optional local conversational model evaluation is the next order; physical Fold setup and calls remain scheduled for later.

## What remains for the controlled test session

1. Have the Fold and this Windows host available, plus a second phone/trusted caller. Confirm actual Android/One UI versions. Personally approve any Bluetooth, Phone Link, WhatsApp linked-device or APK permissions/login steps.
2. Configure and prove two dedicated audio routes. Current inventory exposes only built-in speakers and microphone, not the required isolated call receive/transmit pair. No virtual driver was installed and ambient/system-mix capture must not substitute for isolation.
3. Observe the exact official call-client process and call-specific lifecycle controls. Enroll actual IDs/endpoint names; do not invent them from fixtures. No actual process/control inspection or call answer occurred during setup.
4. Test SIM and personal WhatsApp independently: ring, answer, caller-to-recognizer audio, speech-to-caller audio, end/Stop, caller changes and disconnects. Human calling through the client does not prove AI automation. Keep live availability off until acceptance.
5. Install/pair the accepted debug companion in the owner-approved device session, then test Keystore, lock/revoke, fold/unfold, process death and Doze separately. A sleeping/offline laptop is not an available call engine; this setup does not create standalone phone-only answering.

No root/modified WhatsApp client, account migration, forwarding or Business substitution is introduced. Personal-account feasibility remains a gate, not a guarantee. Preserve [other deferred work](DEFERRED_WORK.md), including real production signing/reviews, other providers/models/devices, live quality measurements and game testing.
