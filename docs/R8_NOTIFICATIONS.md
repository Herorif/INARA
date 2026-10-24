# R8 selected notification inbox

R8 implements the read-only server/desktop workflow and native Android source. It does not establish Android compilation or physical-phone acceptance. No real notifications, phone permissions, accounts, messages, calls, provider requests or model downloads were used.

## Delivered behavior

The Android companion panel now contains a cyan JARVIS signal inbox, local count summary, timestamps, redacted snippets, explicit refresh/clear controls and a permission editor. Each device has a separate current-project scope. Rules select exact application packages and opaque conversation hashes; `*` explicitly selects every conversation in a chosen app. Nothing is selected by default. Metadata-only is the default. Allowing redacted text is separate and still may expose personal details; this is explained on both surfaces.

Pairing/status/chat grants do not authorize ingestion. A new encrypted per-device/project policy grants `notifications:sync`. Signed `/v1/notification_policy` reads only that device's policy; signed `/v1/notification_sync` requires an approved, unlocked-owner, unexpired device plus the separate enabled policy and exact policy revision. The phone cannot read an inbox, set policy, clear desktop content, approve tools or invoke notification actions. Three desktop owner/renderer controls read/configure/clear the selected project's device ledger. No shared model tools were added.

Every policy application, clear, revoke or regrant rotates a UUID revision and clears content/receipts. A queue captured under an old revision cannot replay after a later grant. Device revocation immediately disables/clears server notification state. Current project changes cannot grant access to a different paired project. Offline phone copies cannot learn laptop revocation until manual refresh/sync; stopping locally/system-access loss clears the local queue when detected. Clear on one side does not claim to clear an offline copy on the other side.

## Storage and ordering

Server payloads use the existing user-bound DPAPI SQLite document storage. Default retention is 24 hours, configurable from one hour to seven days. Each device is bounded to 200 source records including removal tombstones and 2,000 idempotency receipts. Uploads contain at most ten events and retain the existing signed-envelope/body/rate limits. Capacity errors reject the entire transaction instead of evicting tombstones or silently replaying messages.

Stable event UUIDs support explicit duplicate-safe retries even if the previous response was lost. New signed request UUIDs still pass through R7 replay protection. Changed content under the same event ID rejects. Per-source timestamp/sequence ordering ignores older updates; removals win exact ties. Tombstones prevent a late posted event from resurrecting a removed notification within retention. Expiry runs at core startup and every minute, independently of inbox visibility, and on policy/read/sync. Core shutdown cancels its maintenance task. Logical clearing/expiry does not promise forensic erasure of encrypted SQLite/WAL/backups.

Email addresses, web links, long number strings, common code/token/password patterns and control characters are redacted before storage. Metadata mode strips titles/text entirely. The event ledger hashes only the sanitized representation. Redaction is defense in depth, not full personal-data detection. Incoming text is inert display data: no model, prompt execution, replies or automatic acknowledgements. Summaries are deterministic local counts, visibly labeled as such.

## Native source and closed acceptance gate

The manifest declares one `exported=false` service protected by `BIND_NOTIFICATION_LISTENER_SERVICE`, with the documented Android listener intent. INTERNET remains the only requested uses-permission. No receivers, work scheduler, background networking or automatic rebind were added. The source follows the [Android notification listener contract](https://developer.android.com/reference/android/service/notification/NotificationListenerService).

`BuildConfig.NOTIFICATION_ACCEPTANCE_ENABLED` is **false** in the checked-in build. Access-settings, collection and sync controls remain disabled, and listener callbacks reject work before inspecting notification data. This flag must remain closed until a separately authorized native build/device acceptance process is available; do not flip it as routine setup.

Source for an accepted test build provides explicit system-settings navigation, review of laptop rules, separate local text consent and Enable reviewed selection. The listener processes new selected events only, excludes ongoing/group-summary/secret/call/alarm/media notifications, and never scans active history or reads/executes actions. Conversation discovery stores at most 32 opaque IDs locally for selected packages. Some apps expose no reliable conversation identifier; their shared default bucket must not be represented as guaranteed per-contact isolation.

An independent AndroidKeyStore AES-GCM key/file stores the bounded queue, consent and opaque discovery IDs under noBackupFilesDir. The original R7 signing alias and default storage filename/AAD remain unchanged. One cross-instance lock serializes listener/model storage. The local queue holds at most 100 events and a maximum 24-hour TTL (or the shorter server retention), pruned on callback/read/foreground/manual sync; Android process suspension does not guarantee timed physical deletion. Full queues show backpressure. Permission loss/disconnection stops local collection and clears queued data when detected. No raw notification logs are written. Forgetting the link also removes this independent notification store/key.

Manual foreground sync fetches policy again, rejects changed revisions, sends one batch, validates exact receipt IDs/revision and removes only acknowledged events. Disconnect/process death preserves stable queued IDs; reconnection never automatically transmits them. The source build/JVM/Keystore/Doze tests remain unrun because JDK/Gradle/SDK/ADB are absent. These claims describe source design, not observed handset behavior.

## Acceptance evidence

The final supported Python suite passed **810 checks with one Blender-dependent skip**. Node passed all **66 checks**. Types, generated contracts, Ruff, source/manifest guards and the production build passed. The CI workflow includes the new notification/release tests, but no hosted CI run is claimed.

Actual hidden Electron + native host acceptance used generated fixture keys and synthetic notifications over loopback TLS: pairing default-denied ingestion, explicit owner policy, server redaction, duplicate receipt, one displayed item, clear, stale-revision rejection, device revoke and listener/workspace/core cleanup. Desktop and 390px screenshots are in `docs/qa/r8-*`. No Android device/APK/provider was used. Resident working set was about 65 MB before opening; about 83 MB after closing, including the in-process HTTPX/cryptography fixture client. This is a short fixture observation, not a clean production idle, game or battery benchmark.

## Remaining work

R8 source/fixture implementation is complete. Android compilation and physical-device acceptance are release gates, not another lettered R8 refactor. Follow [release readiness and remaining backlog](RELEASE_READINESS.md). WhatsApp drafts/replies/sends/actions and phone-call answering remain excluded.
