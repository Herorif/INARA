# INARA Android companion (debug pilot)

Native Kotlin/Compose companion for pairing, laptop status, scoped job previews and separately granted tool-free chat. **A clean strict offline debug build is accepted, 23 October 2026**, with real Kotlin/Java compilation, one passing JVM protocol test and APK signature verification. No phone/emulator installation or runtime acceptance has occurred. [Build evidence and preserved APK location](../docs/qa/android-build-verification.json).

The source manifest declares only INTERNET. The compiled manifest additionally contains AndroidX's app-owned signature-only `DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION`, verified with aapt2; it adds no phone/audio permission. It has no camera/microphone permission, default-dialer role, calls integration, foreground service or background worker. The protected notification listener exists in source behind a false acceptance flag, as detailed below. Existing SIM and personal WhatsApp are unaffected.

## Protected call receipt reads

Version 0.1.1-receipts (code 2) adds an explicit read-only calls:read pairing grant, manual saved-call list/transcript reads and protected bounded caching. Existing devices receive no new grants. A fresh strict offline build, four JVM tests and APK signature verification pass; phone install/runtime acceptance remains pending. [Implementation, current artifact and limits](../docs/MOBILE_CALL_RECEIPTS.md). No call answering or WhatsApp text action is enabled.

## Build with the local toolchain

Pinned baseline: JDK 17, Gradle 8.14.6, Android SDK platform 35 / Build Tools 35.0.0, AGP 8.9.2, Kotlin/Compose compiler 2.1.20 and Compose BOM 2025.04.01. Real resolved locks and SHA-256 verification metadata are now present. These are validated compatibility pins, not a latest-version claim. [AGP compatibility](https://developer.android.com/build/releases/agp-8-9-0-release-notes), [Compose compiler setup](https://developer.android.com/develop/ui/compose/setup-compose-dependencies-and-compiler).

`./build.ps1 -Preflight` checks local presence without executing tools. `./build.ps1` checks exact tool versions, then runs a clean offline build with strict dependency verification, one worker and the 768 MB JVM cap. It installs nothing. First dependency recording uses the explicit `-RecordDependencies` mode, optionally with `-ResolveDependencies` when downloads are undertaken. Recording is not accepted-build status: review generated locks/checksums and rerun the normal offline build. The runner audits fresh JVM tests, APK structure and apksigner results, with local source/output hash receipts. [Commands, evidence contract and remaining limits](../docs/ANDROID_BUILD_ACCEPTANCE.md). No real dependency lock/checksum file or APK was fabricated without a build. Compose/emulator/device acceptance remains separate.

## Pairing ceremony

1. In desktop Connections, open Android companion. Enable the listener with an exact private IPv4 address; loopback is useful only for local verification. It starts off every core launch. No firewall/router changes are made.
2. Create a two-minute invitation for the current project, optionally granting tool-free chat. Save the invitation JSON and transfer it privately to the phone. Optional offline QR rendering uses `requirements-mobile.txt`; that extra was not installed. A QR reader may copy invitation JSON for the app's paste entry; there is no in-app scanner or silent camera access.
3. Import the invitation using the Android system file picker, or paste its JSON. The app pins the invitation's laptop certificate using a private trust store and normal hostname verification, then proves possession of its Keystore signing key. Private key and invitation secret are never sent as a credential/token pair; only the public key and one-time invitation secret are submitted over TLS.
4. Compare the **full device-key fingerprint** on both screens and approve on the laptop. Check approval on the phone. Pairing grants status/job reads for one captured project and, only if selected, tool-free AI chat for 30 days. It grants no desktop tools or remote action approvals.
5. Revoke on the laptop when needed. Forget local link explicitly to erase local keys/cache; forgetting alone does not revoke the server record.

## Lifecycle

Refresh, Send once and Check saved receipt are explicit user actions. There are no network retries, redirects, background polling or automatic outbox sends. Pending messages, selected link, cached messages/jobs and drafts use AES-GCM encrypted app-private no-backup storage with a separate Keystore key. Draft saves debounce 350 ms; pause flushes saved state. Cache size is bounded. Process death restores an unfinished request as uncertain; receipt lookup reads the durable server outcome without calling a provider again. Revocation/authorization errors block grants and clear rendered private caches on the next response.

The phone client disconnects/cancels work on Activity stop and closes connections in finally. Actual Android cancellation timing, process death, key invalidation, fold/unfold/IME/multi-window, TalkBack, physical sleep, certificate renewal and battery/Doze behavior remain acceptance gates. The Compose layout uses one column below 720 dp and two scrollable panes above it. Those source layouts have **not** been rendered on a phone/emulator here.

See [protocol, evidence and limits](../docs/R7_ANDROID_FOUNDATION.md). API/provider configuration and all physical phone acceptance remain deferred.


## R8 selected notifications (source only)

The protected notification listener, encrypted bounded queue, explicit consent/rule review and manual duplicate-safe sync are compiled. `BuildConfig.NOTIFICATION_ACCEPTANCE_ENABLED` remains false. The JVM protocol test does not exercise Android Keystore, notifications or device permissions. No real notification acceptance was performed. Do not flip the flag or enable system access until a separately authorized native/device acceptance process is available. INTERNET remains the only source-declared uses-permission (the merged APK also has the app-owned AndroidX signature permission); the non-exported listener requires the system's BIND_NOTIFICATION_LISTENER_SERVICE binding permission.

See [R8 source behavior and limits](../docs/R8_NOTIFICATIONS.md) and [remaining release gates](../docs/RELEASE_READINESS.md). No WhatsApp replies/drafts/actions or call handling is implemented. No background networking, history scan or automatic sync was added.
