# Order 2: shared local-call admission and availability

Implemented 24 October 2026. **Source integration is complete; live phone acceptance remains deferred.** [Verification](qa/call-admission-verification.json): 149 focused Python checks, including 25 new admission checks, five client checks, scoped Ruff, TypeScript, generated-contract drift and production Vite build pass. Tests use isolated databases, synthetic enrollment and inert supervisors. They do not answer calls or open audio.

## Core ownership

`Application.call_admission` owns one session. The internal `start` method binds an authenticated owner renderer, captured project, canonical request UUID, immutable bridge profile and a bounded one-call lease. Before admitting work it requires a trusted physical-acceptance callback plus confirmed controls/routes, local speech presence, resource eligibility and a durable request claim. No such physical verifier is enrolled in the running product. Enrollment JSON booleans alone cannot enable answering, and there is no renderer/mobile/tool live-start operation.

The local profile reserves one CPU, 512 MB RAM and zero VRAM in the existing shared governor. These are admission estimates, not measured peaks or OS hard limits. Admission refuses while a creative/check worker already holds or queues resources; incoming calls do not wait behind stale ringing controls. Subsequent creative work can queue behind the reserved slot. Resident/gaming modes and resource faults refuse calls. Availability inspects capacity on demand using the governor's existing hardware cache; it neither acquires a slot nor loads a speech model.

The existing owned Windows supervisor supplies child-tree cleanup, heartbeat monitoring, suspension detection, recurring authorization and the hard lease deadline. Authorization rechecks owner, project, resource ownership and the trusted physical-acceptance callback. Disconnect, lock/project changes, resident/gaming transition, faults, acceptance withdrawal and core shutdown stop or cancel the owned session and release its reservation. One core's governor is not a new cross-process or system-wide CPU scheduler.

## Durable records and usage

The protected database retains up to 256 request UUIDs and 24 recent summaries per owner/project. Repeated UUIDs refuse across restart; no session resumes automatically. A readiness read marks orphaned running summaries uncertain. This bounded controlled-test ledger deliberately has no automatic reset; longer-lived retention/compaction needs a separate design before broad unattended use.

Admission creates a content-free shared usage receipt before any worker starts. It is explicitly `cloud=false`, with zero cloud authorization allowance. Local speech can therefore be admitted even when cloud caps are exhausted; it neither consumes nor bypasses a cloud authorization. The worker bootstrap pins `voice_mode=local` and includes no provider key/model. Local energy/hardware cost and measured speech performance are not claimed to be zero. Usage receives state/duration only, not caller text, endpoints or transcripts. Protected call records remain scoped separately to the captured owner/project; mobile receipt synchronization remains pending.

Exceptions during usage admission, worker construction/execution or finalization release reservations. Missing or interrupted outcomes remain uncertain. A local completion receipt is not caller authentication, message confirmation or proof of delivery to the phone.

## Public UI and CLI

Call Lab now displays shared admission readiness, resource/setup blockers and local-only speech separately from physical availability. `live_enabled=false` and the physical-unverified blocker remain mandatory in the strict client contract. Refresh does not open call apps, capture devices or network providers. The existing offline simulation remains the only public start operation.

The old standalone `scripts/call-bridge.py run --live ...` now refuses with `call_core_required` before reading enrollment or launching a worker. It cannot operate independently of the shared core governor. Schema/preflight and explicitly requested metadata diagnostics remain available. A future owner-approved controlled-test entry must use core admission and a real acceptance verifier; no CLI/profile/environment switch added here grants that acceptance.

## Remaining work

Order 1's accepted Android debug APK remains unchanged. Order 3 is evaluation and integration of an optional local conversational model, with no runtime/model selected or downloaded by this step. Keep idle/gaming resource use and measured quality central; current Vosk/SAPI speech remains structured English and half-duplex.

Protected mobile receipt sync, the trusted physical-acceptance verifier and eventual explicitly armed core call controls remain pending. Fold installation/pairing, exact SIM/personal WhatsApp lifecycle controls and isolated receive/transmit audio await the owner's controlled test session. Production signing/custody and 52 controller/85 desktop reviews remain separately pending, both production policies disabled. WhatsApp text replies/drafts/acknowledgements/notification actions, outgoing calls, forwarding and Business migration remain excluded. [Standing deferrals](DEFERRED_WORK.md).
