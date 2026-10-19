# INARA Android companion (R7 source)

Native Kotlin/Compose source for pairing, laptop status, scoped job previews and separately granted tool-free chat. **No APK was compiled or installed in this environment.** JDK/Gradle/SDK/ADB were unavailable. Manifest/source guards and Python protocol fixtures do not prove Android runtime behavior.

The app has only INTERNET permission. It has no camera/microphone permission, notification listener, default-dialer role, calls integration, foreground service or background worker. Existing SIM and personal WhatsApp are unaffected.

## Build when tooling is provided

Pinned baseline: JDK 17, Gradle 8.11.1, Android SDK platform 35 / Build Tools 35.0.0, AGP 8.9.2, Kotlin/Compose compiler 2.1.20 and Compose BOM 2025.04.01. These are explicit source pins, not a claim to be the latest versions or a resolved dependency lock. [AGP compatibility](https://developer.android.com/build/releases/agp-8-9-0-release-notes), [Compose compiler setup](https://developer.android.com/develop/ui/compose/setup-compose-dependencies-and-compiler).

`./build.ps1` checks pre-existing tools/SDK and runs Gradle offline with two workers and a 2 GB JVM cap. It installs nothing. There is deliberately no wrapper that downloads Gradle on first use. If dependencies are missing, a separately authorized `./build.ps1 -ResolveDependencies` permits normal Gradle dependency resolution; it still requires an existing SDK. First successful build must record dependency resolution/verification, run the included JVM protocol-vector test and inspect Compose previews/emulator behavior before an APK is described as usable. No Gradle dependency lock/checksum file was fabricated without a build.

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
