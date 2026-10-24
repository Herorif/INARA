# Order 4: protected mobile call receipt sync

Implemented 24 October 2026. **Source/protocol integration and a fresh strict offline Android debug build are accepted.** [Execution evidence](qa/mobile-call-receipts-verification.json): 280 focused Python checks (15 new receipt checks), four desktop client checks, four actual JVM tests, Ruff, TypeScript, generated-contract drift and production Vite build pass. Physical Android installation/rendering/Keystore/lifecycle and real calls remain unverified.

## Separate permission and read-only routes

The laptop pairing panel has a default-off **read-only call receipts and caller transcripts** checkbox. Only an authenticated owner renderer can create its invitation; the owner still compares the full device fingerprint and approves the captured project/grants. Pairing stores `calls:read` only when explicitly selected. Existing paired devices receive no new permission; they need an explicitly approved new pairing. The receipt checkbox resets on project change. This is independent of chat and notification permissions.

The dedicated mobile HTTPS API adds signed `/v1/call_receipts` and `/v1/call_receipt` reads. Both use the existing device P-256 proof, exact path/payload binding, timestamp window, durable replay protection, TLS pinning, owner authentication, expiry/revocation and captured project checks. The routes are recorded in [route policy](ROUTE_POLICY_MATRIX.json). The phone cannot select another owner/project, add grants, invoke a tool or request call/reply operations.

Lists contain at most 20 finished core admission summaries from the last seven days: request UUID, SIM/personal WhatsApp source, terminal state/timestamps and conservative unverified identity/confirmation flags. No caller hash, private transcript or internal record reference is included. Active calls and offline Call Lab history are excluded. Older unscoped standalone lab records are not imported or promoted into real-call receipts.

Opening a receipt explicitly retrieves its matching finished protected record from the exact owner/project live-record directory. Expired/missing/unfinished records refuse; an uncertain/failed attempt can have no available transcript. Only literal caller/assistant text is returned, at most 200 segments and 12,000 characters total. Extra internal fields and raw audio are not exported. Receipt availability and a transcript do not authenticate the caller, prove message confirmation or promise follow-up/delivery to another service.

Reading a receipt does not mark WhatsApp messages read, acknowledge caller messages, answer/hang up, send text, make a callback or enable notifications. Signed transport responses are not WhatsApp acknowledgements. There is no push service, background polling, forwarding or account migration.

## Android view and cache

The companion adds a manual receipt-list refresh and explicit transcript-open action. The view labels saved copies, last-fetch time and unverified caller/confirmation status. Text uses ordinary native Text rendering with no executable model/tool markup. Pure Kotlin validation checks UUID/source/terminal-state/time windows, unverified flags and transcript role/count/length. Responses must match the paired project and selected receipt UUID. A refresh clears the previously selected detail; reads never replay a call or ask a model.

At most 20 summaries and one selected transcript share the existing Keystore AES-GCM encrypted no-backup state. Known grant loss/authentication failures clear cached receipt data on publication; local grant expiry and seven-day retention are rechecked during publication/lifecycle actions. Clear cache, close transcript and forget link are explicit local controls. The existing secure-window flag, activity-stop cancellation and protected-state recovery behavior are retained.

**Offline revocation cannot instantly erase an already cached copy.** The phone must receive changed authorization, encounter local expiry during lifecycle/actions, or have its owner clear/forget the cache. Logical clearing is not forensic secure erasure. Actual OS Keystore/process-death/Doze/fold behavior is still a device acceptance gate; JVM tests do not establish it.

## Actual build and artifact

The new companion is `0.1.1-receipts`, version code 2. A clean strict offline build with unchanged dependency locks/SHA-256 metadata produced a fresh 26,383,817-byte APK and passed apksigner verification plus four JVM tests (three new receipt-rule tests and the existing signing vector). The debug APK SHA-256 is `4dd01543200e6d910448861aef0bb47da5a72d169aeca1e386342a5622ceb094`.

The APK, SHA256SUMS, BUILDINFO and original receipts are preserved under `.runtime/android-release-candidate/c34c83f2-38c0-479b-9dd1-b7613e8dfd32/`. The earlier Order 1 artifact remains separately retained. No APK was installed and no phone was contacted. Compiled inspection confirms INTERNET plus the existing AndroidX app-owned receiver permission, no new phone/audio/camera permission, and notification acceptance false. Debug signing is not production release signing or install/update acceptance.

For this resource-constrained host, the Android build heap was reduced to 768 MB with one worker and in-process Kotlin, and the actual build passed. This is a build setting, not a relaxation of Order 3's unchanged 7 GiB local-model loading guard. No local model was loaded or benchmarked.

## What remains

This completes Order 4's software integration and debug build. The next source integration is a controlled-test enrollment/verifier and explicit one-call arming workflow backed by actual physical evidence; profile booleans alone must never unlock it. Fold installation/pairing, isolated two-way audio, exact SIM/personal WhatsApp controls and controlled calls remain for the owner's later session. The local-model benchmark remains explicitly owner-deferred for insufficient resources. Production signing/custody, 52 controller and 85 desktop review subjects, unrelated providers/models/devices and game/soak acceptance remain pending/deferred. See [the standing register](DEFERRED_WORK.md).
