# INARA revival implementation status

Standing owner instruction: preserve [deferred work and exclusions](DEFERRED_WORK.md) across implementations and handoffs; cross-check [release gates](RELEASE_GATES.json). Continuing source work does not automatically resume deferred setup or real-device acceptance.

## Step 5 software complete: controlled one-call workflow, 24 October 2026

[Controlled-call testing](CONTROLLED_CALL_TESTING.md) adds encrypted enrollment drafts, explicit readiness blockers, origin/project-bound 60-second one-use reviews, typed confirmation, a 30-second incoming-call arm window and Stop controls that remain available while an arm acknowledgement is pending. Core admission rechecks source/helper/profile/capture bindings, policy and ownership; the UI never retries an uncertain arm automatically. Only local structured speech is exposed.

**304 focused Python tests (24 new), 14 client checks (five new), scoped Ruff, TypeScript, contract drift and production Vite build pass.** [QA](qa/controlled-call-workflow-verification.json). Synthetic evidence and inert supervisors test the software boundary; no actual call worker, phone/audio or model ran. Android sources/APK are unchanged from Order 4. UI compilation does not establish visual/device acceptance.

**Physical capture integration is still missing**, and the local test policy remains disabled. No live arm token can be issued here. Next device work is to implement and validate that collector with the actual controls and dedicated duplex routes, then run explicitly reviewed single-call tests separately for SIM and personal WhatsApp. The owner deferred those calls until later; universal carrier/personal-account feasibility is unproven. The local-model benchmark stays deferred for insufficient RAM, production policies remain disabled, 52 controller and 85 desktop reviews remain pending, and WhatsApp text/outgoing actions stay excluded. [Deferrals](DEFERRED_WORK.md).

## Order 4 complete: protected mobile receipts, 24 October 2026

[Protected mobile call receipts](MOBILE_CALL_RECEIPTS.md) adds a separate default-off `calls:read` pairing grant, signed read-only list/detail routes bound to the captured owner/project, a metadata-only seven-day/20-item list, explicit bounded transcript reads and a manual Android view using existing encrypted no-backup storage. Existing devices receive no automatic grant. Active calls/offline lab history are excluded; known auth changes/local expiry clear cached data, while offline revocation cannot instantly erase saved copies. No call, reply, notification or acknowledgement action is exposed.

**280 focused Python checks, including 15 new receipt checks, four client checks and four actual JVM tests pass**, with Ruff, TypeScript, contract drift and production Vite build. A fresh clean strict offline Android build/signature audit is accepted: version `0.1.1-receipts` (code 2), 26,383,817-byte debug APK, preserved under `.runtime/android-release-candidate/c34c83f2-38c0-479b-9dd1-b7613e8dfd32/`. [QA and hashes](qa/mobile-call-receipts-verification.json). The 768 MB/one-worker build passed on this constrained host; the local-model 7 GiB guard was unchanged and no model ran.

Superseded next-source note: Step 5 software workflow is now integrated; physical collector integration and device acceptance remain pending (see current Step 5 section). Phone install/pair, Keystore/process-death/fold/Doze and SIM/personal WhatsApp duplex/control tests remain unperformed and deferred for the owner's later session. The real model benchmark remains owner-deferred, both production policies stay disabled, reviews remain pending, and WhatsApp text/outgoing actions stay excluded. [Deferrals](DEFERRED_WORK.md).

## Order 3: local model integrated; real acceptance pending, 24 October 2026

[Optional local inference](LOCAL_MODEL.md) now integrates a pinned portable llama.cpp CPU runtime and official Qwen3 4B Q4_K_M model. Both are actually installed and SHA-256 verified. No Ollama/background service was installed. An explicit model mode uses shared CPU2/RAM6144MiB/VRAM0 admission; structured voice remains default. Schema/exact-substring grounding and deterministic readback/confirmation keep tools and caller authority outside model output. The Call Lab shows installation and evaluation acceptance separately.

**174 focused Python checks, including 25 new model checks, and five client checks pass**, plus Ruff, TypeScript, contract drift, production Vite build and pip check. [QA](qa/local-model-verification.json). **The real inference run refused before loading because only 1.81 GiB RAM was free (7 GiB required).** No quality/latency/RAM result is claimed, the guard was retained, and `accepted_for_calls=false`. The owner was asked to free memory; no other applications were terminated.

Owner update, 24 October 2026: sufficient resources cannot be freed, so real model evaluation is explicitly deferred. Keep the candidate unloaded/unaccepted and structured local dialogue as default; do not lower the guard or silently replace/download another model. Resume `scripts/call-model.py evaluate` when resources are available; source fixtures do not substitute for real model acceptance. Order 4 protected mobile receipt sync is now integrated and its fresh Android debug build is accepted; physical acceptance remains separate. Physical phone/call tests, production signing/reviews and unrelated setup remain deferred; WhatsApp text/outgoing actions stay excluded. [Deferral register](DEFERRED_WORK.md).

## Order 2 complete: shared call admission, 24 October 2026

[Core-owned call admission](CALL_ADMISSION.md) integrates one local session with owner/project authorization, immediate shared resource reservation, recurring scope/physical-acceptance checks, lifecycle cancellation, protected replay claims and zero-cloud-allowance local usage receipts. Call Lab distinguishes software readiness from physical availability. The standalone live CLI is closed; the desktop still exposes only offline checks, and no physical verifier or public live-start route is enrolled.

**149 focused Python checks, including 25 new admission checks, and five client checks pass**, plus scoped Ruff, TypeScript, contract drift and production Vite build. [Execution evidence](qa/call-admission-verification.json). Tests use synthetic profiles/inert supervisors; no live-mode OS worker, phone, capture/playback device, cloud provider or local conversational model was activated. Physical calls and device acceptance are not inferred.

Order 3 integration/installation is now implemented in the milestone above; real model acceptance remains pending because available RAM is below the guard. Protected mobile receipt sync and the controlled-test physical verifier/public arming integration remain pending. Preserve the later phone-call session, production signing/reviews, unrelated setup and [all exclusions/deferrals](DEFERRED_WORK.md).

## Android and local-only call setup resumed, 23 October 2026

The owner authorized Android/call-bridge setup, selected **local-only** voice, reported Samsung Fold 8 and deferred controlled calls until later. [Local-only setup](LOCAL_ONLY_SETUP.md) adds actual workspace-local tool/model preparation, an explicitly local live worker, bounded English message-taking using Vosk/Windows SAPI and no cloud fallback. The native control helper is built, installed call clients are present, and an actual in-memory TTS-to-STT phrase check passes without microphone/speaker access. The available host reports about 16 GB RAM and integrated Arc graphics; no Legion/game/soak acceptance is inferred.

**92 focused Python checks pass**, including 15 new local dialogue/audio/setup/readiness checks, with scoped Ruff and native helper protocol/refusal verification. [Current execution evidence](qa/local-only-setup-verification.json) records actual Android tool/build results separately from fixture success. No live call, APK/device permission, provider credential, audio driver, unattended answering or WhatsApp text action was activated. The local baseline is structured English/half-duplex; broader conversational models, natural interruption and physical quality remain pending.

**Android debug build accepted, 23 October 2026:** dependency recording, actual Kotlin/Java compilation, one executed JVM protocol test and APK signature verification now pass, followed by a clean strict offline build. All 694 recorded artifact SHA-256 values match cached bytes; nine direct pinned components also match official Maven checksum sidecars. Gradle is deliberately updated to 8.14.6, with JDK 17/AGP 8.9.2/Kotlin 2.1.20/API 35 retained. The working cache is isolated in a deterministic per-workspace user-temp directory; workspace-cache failures remain recorded, and the Windows root cause is not established. No security setting was changed or transform workspace manually promoted. **49 focused Python checks and scoped Ruff pass.** [Build evidence and preserved APK location](qa/android-build-verification.json).

Shared live-session admission/availability source integration is now complete; see the order 2 milestone above. Protected mobile receipt sync remains pending. Fold installation/pairing, dedicated audio routes and exact SIM/personal WhatsApp control/media acceptance remain for the owner's later controlled test session. Production identities/signing and separate 52-controller/85-desktop reviews remain pending; both production policies stay disabled. WhatsApp text/outgoing actions and unrelated configuration remain excluded/deferred. Preserve [the deferral register](DEFERRED_WORK.md).

## Controller receiving and clean-machine preparation, 22 October 2026

[Controller receiving](CONTROLLER_RECEIVING.md) adds an independently trusted receiver that does not need the producer's matching build source, exact signature-bound evidence/history/custody validation, cache-only native acceptance, reviewed bounded copies into new directories, relocatable package verification and a statement-bound pending clean-machine checklist. Received scripts remain inert; producer evidence is endorsed by external signatures rather than source-regenerated. Neither the copy receipt nor the checklist grants installation, execution or release authority.

**195 distinct focused Python checks pass**, including 26 receiving/copy/drift checks, with scoped Ruff. Actual collection/rederivation against the unchanged **2,681-file controller** and a new zero-event ledger contain **52 pending controller subjects** (one additional external receiver tool); **85 desktop subjects remain separately pending**. Real disabled-policy receiving preparation refuses without creating an output. [Execution evidence](qa/controller-receiving-verification.json). Positive delivery/copy tests use inert fixtures, ephemeral synthetic keys and an injected native adapter. Real source/configuration/device acceptance is not inferred from those checks.

Step 5 source preparation is complete. Next: owned signing and independent trusted delivery, then actual clean Windows account/machine and signed native-window install/launch/update/recovery/removal acceptance **when configuration is explicitly resumed**. Independent remaining source work may continue while that setup is deferred; do not manufacture another source milestone as proof of real acceptance. Both production policies remain disabled. Preserve [all deferrals and exclusions](DEFERRED_WORK.md), especially Android/toolchain downloads, provider/model/device setup, personal SIM/WhatsApp live audio, Legion/game measurements and WhatsApp text/outgoing actions.

## Signing custody and delivery preparation, 22 October 2026

[Signing/delivery preparation](SIGNING_DELIVERY_PREPARATION.md) implements public custody drafts/validation, separate immutable controller review revisions and domain-separated detached delivery requests/verification. Delivery verifies publisher/reviewer signatures before payload validation, binds exact controller/bootstrap/provenance/ledger/custody/policy bytes and rechecks evidence/native trust. No private-key/signing/enrollment/installation/launch path was added. The existing 2,681-file controller and manifest pin remain unchanged; these are independently trusted external preparation tools.

**181 focused Python checks pass**, including 34 new custody/review/delivery checks, with scoped Ruff. Actual renewed provenance and a zero-event controller ledger contain **51 pending subjects**, up from 48 because three external tools are now included. All **85 desktop subjects remain separately pending**. [Execution evidence](qa/signing-delivery-verification.json) records actual disabled-policy/draft readiness blockers and unsigned request refusal without creating an output. Positive signature/native acceptance uses synthetic assertions, ephemeral in-memory test keys, inert payloads and an injected native adapter.

Step 4 preparation is complete. Next: source-neutral receiving/delivery packaging and clean-machine acceptance preparation, followed by actual owned signing/trusted delivery and real lifecycle acceptance when configuration is explicitly resumed. Current delivery verification requires an independently trusted matching source snapshot. Both production policies remain disabled; the public draft does not enroll an identity or resume any deferred setup. Preserve the [deferral register](DEFERRED_WORK.md), including Android/toolchain downloads, provider/model/device setup, physical incoming SIM/personal WhatsApp audio proof, real model cost/quality and Legion/game measurements. WhatsApp text/outgoing actions remain excluded.

## Protected profiles and removal lifecycle, 22 October 2026

[Protected lifecycle](MANAGED_LIFECYCLE.md) completes Step 3 source integration: original-account encrypted backups, reviewed typed recovery-copy preparation, separately signed profile activation/rollback, software removal retaining data and separate exact-phrase profile erasure. All selection/removal changes retain format 3 and use signed checkpoint transitions. Encrypted deletion inventories and exact journals support reviewed resume; cancellation refuses after deletion begins. Admission/signature/policy/checkpoint history and sequence floors remain retained.

**542 distinct Python checks pass** across focused regression and final lifecycle/copy runs, including 32 lifecycle checks and 35 worker/entry checks. Scoped Ruff and native wide/narrow interaction acceptance pass. Tests cover actual Windows-account backup/preparation, typed-data revalidation, signature-domain separation, source changes during backup, canonical recovery paths, deletion/commit interruptions, stale or foreign state, unknown/shared files and erasure phrase repetition at resume. [Execution evidence](qa/managed-lifecycle-verification.json) records final controller/bootstrap/worker/provenance acceptance. These are source/development-host checks using synthetic signers/inert payloads, not production native-window mutation or clean-machine certification.

Next: **Step 4 - owned identity custody, Windows signing and trusted delivery preparation**, then real signed-package/clean-machine install, update, recovery and removal acceptance when configuration is authorized. Both production policies remain disabled, all 48 controller reviews and 85 desktop reviews remain pending separately, and no real profile/identity/provider/device is configured. WhatsApp text/outgoing actions remain off; Android and physical SIM/personal WhatsApp duplex-media proof stay separate and real-game benchmarking stays deferred.

## Protected native management UI, 22 October 2026

[Protected management](MANAGED_NATIVE_UI.md) adds the dedicated dark/cyan WPF window for checkpoint-pinned metadata status, signed enrollment/renewal/trust rotation/update/rollback, reviewed interrupted-change resume and pre-commit cancellation. A bootstrap-verified private worker keeps the UI responsive. Five-minute single-use reviews bind exact inputs and backend plans; busy operations block input changes and window closure. Returned pins are never adopted automatically. Uncertain applies retain prepared/previous checkpoint review evidence with confirmation disabled.

**480 distinct Python checks pass** across the focused regression and final worker/controller/provenance runs, including 30 management-worker/entry checks, with scoped Ruff. Native UI renders/interaction checks pass at 1120 and 780 pixels. [Execution evidence](qa/managed-native-ui-verification.json) records the final controller/bridge/provenance acceptance. Production identities/configuration remain deferred, both production policies disabled, all 48 controller reviews and 85 desktop reviews pending separately. This is source/development-host acceptance, not production signing or a real signed-package/native-window mutation/clean-machine certification.

Next: **Step 3 ? protected backup/restore and removal lifecycle integration**, preserving profile ownership/compatibility and signed checkpoint/recovery evidence; then owned signing/delivery and clean-machine acceptance. Android and physical SIM/personal WhatsApp duplex-media proof stay separate. WhatsApp text/outgoing actions remain off, providers/toolchains/devices unconfigured and real-game benchmarking deferred.

## Controller provenance and notices, 22 October 2026

[Controller provenance](CONTROLLER_PROVENANCE.md) now binds an offline dependency/source/native inventory, verbatim notices and a separate pending review queue to the exact externally pinned controller. Actual collection and full evidence rederivation pass for the unchanged 2,672-file artifact: **43 components, 51 notice files, 38 native files and 48 pending controller reviews**, with no missing component-level notices. Metadata origin hints do not authenticate acquisition or establish native subcomponent coverage.

**139 focused tests pass**, including 23 new provenance checks and 11 release-boundary checks, with scoped Ruff. [Verification evidence](qa/controller-provenance-verification.json). The queue is a checklist, not an approved ledger or release input; all 85 desktop subjects remain pending separately. Both production policies remain disabled. No configuration, downloads, signing, installation, profile access or resident launch occurred.

Next: native format-3 management UX for protected status/update/recovery, then backup/removal lifecycle integration and owned signed delivery/clean-machine acceptance. Keep provider/toolchain/device configuration deferred, WhatsApp text/outgoing actions off and the real-game benchmark deferred.

## Protected checkpoints and signed version changes, 22 October 2026

[Managed updates](MANAGED_UPDATES.md) implements external account-protected checkpoint/history storage, dual-policy approval for trust changes and reviewed local package update/retained-version rollback. Ordered journaled metadata commits preserve old versions/data, with reviewed recovery and pre-commit cancellation. Managed format-3 roots refuse unsigned controls and use checkpoint-pinned guarded launch.

**281 focused checks pass**, including 31 new managed-state checks, with scoped Ruff, real account-protection refusal probes and updated 2,672-file controller/bootstrap acceptance. [Evidence](qa/managed-update-verification.json). Production policies remain disabled, all 85 reviews remain pending and no actual production root, signing identity or resident is configured.

Next: controller-specific notices/provenance and native format-3 management UX, then owned bootstrap signing/delivery and clean-machine acceptance. External latest-checkpoint pins are required; no hardware monotonic state or cross-account acceptance is claimed. Preserve existing package/profile/recovery boundaries and keep WhatsApp text/outgoing actions off.

## Renewable authorization and guarded launch, 22 October 2026

[Admission and launch](ADMISSION_LAUNCH.md) implements root/installation/version-bound signed renewal, exact review/apply, retained grant history and externally pinned head checks. Guarded resident launch revalidates signatures, installed bytes, profile binding and Windows trust under lifetime manager/file leases. Suspended-start Job Object containment stops the process tree on expiry, controller death or guard cleanup.

**250 focused checks pass**, including 33 new checks, with scoped Ruff. Actual isolated-Python file-lock/expiry/process-tree acceptance and updated 2,670-file controller/bootstrap verification are recorded in [execution evidence](qa/admission-launch-verification.json). Production policies remain disabled and all 85 real review subjects remain pending; no real resident, production grant/installation or identity is configured.

Next: protected update/trust state, reviewed key/policy rotation and transactional signed updates/rollback. External latest-head pins are currently required; local metadata is not a hardware monotonic counter. Controller notices, owned bootstrap delivery and real resident/UI clean-machine acceptance remain open. Android/physical calls remain separate; WhatsApp text/outgoing actions stay off.

## Windows verification and portable controller, 22 October 2026

[Windows controller preparation](WINDOWS_CONTROLLER.md) implements native cache-only certificate verification, exact external signer/timestamp pins, a final-byte portable controller inventory and a trusted-source PowerShell bootstrap that verifies files before bundled Python starts. Install/recovery retains signed package evidence before registration; the read-only launch contract checks current signatures, exact installed bytes and profile binding. Local root metadata remains unsigned and no resident is launched.

**216 focused Python checks pass**, including 33 new checks, with scoped Ruff. Actual 2,668-file controller assembly, external-bootstrap status/refusals and native upstream Python certificate observations are covered by [execution evidence](qa/controller-verification.json). Production policies remain disabled, all 85 reviews remain pending and no actual production identity or installation is configured.

Next: durable admission/renewal authorization, process-lifetime guarded launch, monotonic update/rollback state and reviewed trust changes. Controller distribution notices, owned signed-bootstrap delivery and clean-machine acceptance remain pending; Android/physical calls remain separate and WhatsApp text/outgoing actions stay off.

## Authenticated package format and guarded admission, 22 October 2026

[Authenticated packaging](SIGNED_PACKAGE.md) adds a separate container manifest, payload/audit/ledger file inventory and purpose-separated detached publisher/reviewer signatures. The external controller verifies trust and signatures before payload inspection, then validates inert bundled evidence without executing candidate code. Production-only review/apply binds the installation destination/state; source/copied bytes and state are checked under the manager lease before registration. Fresh signed review is required for interrupted-copy recovery. Selection/launch are never automatic.

**183 focused Python checks pass**, including 27 package checks, plus scoped Ruff. Real-candidate fixture assembly/verification passes with 3,067 inventory files and 85 pending review subjects. Missing signatures, fixture installation and disabled production trust refuse without creating a target. No private keys are persisted and no real release is signed. [Evidence](qa/signed-package-verification.json). Existing unsigned pilot controls remain separate; this is guarded admission, not persistently authenticated installation/launch, Authenticode or clean-machine acceptance.

Next: Windows signing/verification adapter and trusted-controller distribution preparation, with authenticated admission receipts and verified-launch contracts. Owned identities/certificates, authoritative review decisions, bootstrap delivery and actual clean-machine/signed-update acceptance remain pending. WhatsApp text/outgoing actions stay off.


## External publisher/reviewer trust and detached attestations, 22 October 2026

[Release trust](RELEASE_TRUST.md) adds independently pinned public-key policies, separate publisher/reviewer thresholds, exact candidate/inventory/audit/ledger binding, bounded signing windows, sequence/channel/mode checks and detached signature verification. The CLI prepares unsigned messages and never imports private keys, signs, installs or launches. The checked-in policy is disabled with zero enrolled production identities; fixture use requires an explicit option.

**90 focused Python checks pass**, including 40 trust checks, with scoped Ruff. Real candidate/audit/85-pending-subject ledger acceptance passes using ephemeral in-memory fixture keys; altered/missing signatures, implicit fixture trust and unconfigured production preparation refuse. No private keys were persisted and no real release was signed. Key verification remains distinct from legal identity, Authenticode, clean-machine acceptance and release authorization. [Evidence](qa/release-trust-verification.json).

Next: an independently trusted verify-before-install boundary and explicit signed-package format, with invalid/untrusted payload refusal before copy/selection/launch. Keep unsigned pilot and fixture paths separate. Actual reviewer/publisher enrollment, authoritative review decisions, Windows signing/timestamps, trusted bootstrap delivery and clean-machine/signed-update state remain pending. WhatsApp text/outgoing actions stay off.


## Immutable distribution review ledger, 22 October 2026

[Distribution review](DISTRIBUTION_REVIEW.md) adds digest-bound candidate/audit subjects, explicit pending/approved/rejected reviewer assertions, subject-specific text evidence requirements, exact review/apply and immutable new-directory revisions with retained event/evidence history. Stale requests/evidence/destinations, changed audit/tool bindings and modified/missing/extra ledger files refuse. Recorded approvals never authenticate the reviewer or grant release/redistribution clearance.

**82 focused Python checks pass**, including 39 ledger checks, with scoped Ruff. Actual inventory creation and separate CLI status verification cover **85 real subjects**, all pending: 75 components, five assets, two missing-notice records, two runtime baselines and one vendor/native coverage review. No real decision, evidence download, signing, provider/phone/profile configuration or startup change occurred. [Evidence](qa/distribution-review-verification.json).

Next: explicit publisher/reviewer identity and trust policy plus authenticated whole-payload packaging preparation, with fixture verification kept separate from actual certificate provisioning. Authoritative origin/license/baseline decisions, signed artifacts, clean-machine and signed-update acceptance remain open. Android and physical calls remain separate; WhatsApp text/outgoing actions stay off.


## Renderer/worker provenance and asset inventory, 21 October 2026

[Renderer provenance](RENDERER_PROVENANCE.md) now records the actual main/worker graph, chunk membership, raw input hashes, byte-identical WASM/loader/public copies and final output inventory during build. New desktop staging revalidates current source and binds the evidence into the package. Legacy candidates remain explicitly unrecorded. Asset ownership is digest-bound and pending; no license clearance is inferred.

**107 focused Python checks and six Node observer checks pass**, with scoped Ruff, a real production build and verified 2,993-file bundled candidate. Observed evidence contains 2,162 physical inputs, 2,155 main/worker module records, 45 chunks and 67 outputs. The exact-membership audit collects 75 component records and 82 notice files; two observed npm records still lack recognized notice text and all five asset inputs remain pending. [Evidence](qa/renderer-provenance-verification.json).

Next: a digest-bound distribution review ledger for asset origins, missing notice evidence, vendored/native components and runtime baseline decisions. Signing identity/trust, clean-machine and signed-update acceptance remain open. Android/physical calls/providers remain separate gates; WhatsApp text/outgoing actions stay off.


## Distribution provenance and notice evidence, 21 October 2026

[Distribution provenance](DISTRIBUTION_PROVENANCE.md) adds an offline candidate-bound audit with exact manifest/inventory/collector hashes, pinned Python metadata, native bundle source-input checks, a conservative renderer npm inventory and verbatim content-addressed notices. A separate verifier rederives the complete report/output and refuses modified claims or evidence. **79 focused checks pass**, including 31 new audit checks, plus scoped Ruff. Actual collection covers **143 component records and 147 notice files** in the unchanged 2,990-file native Setup candidate. Six npm records lack recognized local notice files and remain visible review gaps.

This completes the provenance/notice collection source milestone, not license clearance or authenticated distribution. Publisher identity, signing, security/support baselines and clean-machine acceptance remain open. Next: exact renderer build provenance and copied-asset ownership, then resolve notice evidence/redistribution decisions, owned signing and clean-machine/signed-update acceptance. [Execution evidence](qa/distribution-audit-verification.json). No profile, provider, phone, startup setting or account was changed; WhatsApp text/outgoing actions stay off.


## Native Windows setup and removal, 21 October 2026

[Native Setup](NATIVE_SETUP.md) adds a responsive dark cyan WPF interface for explicit installation, version selection/rollback, tray-first launch, encrypted backup and reviewed recovery. A verified bundled Python worker uses private pipes without a web listener. Software removal retains original/recovery data; permanent erasure is separately reviewed and requires an exact typed phrase. Bounded removal journals support reviewed resumption and refuse changed/foreign paths. Same-build reinstall reviews retained recovery-profile reuse.

**174 focused Python checks pass**, with scoped Ruff, native WPF layouts at 1120/780 pixels and actual private-worker/dispatcher acceptance. A real bundled-package synthetic workflow passes install/select, owned resident launch, Setup-independent lifetime, lease protection, graceful quit, software removal with data retained and separately confirmed test-data erasure. [UI evidence](qa/setup-ui-verification.json), [bridge evidence](qa/setup-bridge-verification.json), [package evidence](qa/setup-package-verification.json). No production profile, startup setting or registry entry was changed.

This is an unsigned directory-based native pilot, not signed MSI/EXE or clean-machine acceptance. Distribution provenance/notice collection is implemented above. Next: exact renderer and asset evidence, redistribution decisions and signing readiness, followed by clean-machine and signed-update acceptance. Android tooling/device, physical SIM/personal WhatsApp media and real providers remain separate gates; WhatsApp text/outgoing actions stay off.


## Reviewed recovery activation, 21 October 2026

[Recovery activation and compatibility](RECOVERY_ACTIVATION.md) implements explicit owner/version/destination review, prepared managed copies, typed project-scope rekeying for workspace/memory/conversations/terminal CAD-image jobs, atomic activation and retained-data rollback. **151 focused checks pass**, including 24 activation checks, plus scoped Ruff. Actual native restored memory/conversation/fixture-artifact access, graceful shutdown, old-control refusal and retained-data rollback pass. [Evidence](qa/recovery-activation-verification.json). Unknown record groups/SQL objects, legacy markers, active/referenced jobs and incompatible owners/scopes reject; no data is silently dropped.

Activation atomically upgrades installation metadata to format 2, so older controls refuse rather than silently use original data. Launch through the current control script. New backups record their encrypted canonical source root; original archive format 1 remains supported. Windows installation/launch/uninstall UX is now implemented in the Native Setup milestone above. Signing, broad recovery-adapter coverage, clean-machine acceptance, Android tooling/device and physical SIM/personal WhatsApp duplex media remain open; WhatsApp text/outgoing actions stay off.

## Encrypted full-profile recovery copies, 21 October 2026

[Encrypted profile recovery](ENCRYPTED_PROFILE_RECOVERY.md) implements original-Windows-account DPAPI/AES-GCM backup, bounded validation-only preview and digest-confirmed restore into a new detached directory. Full data content and empty folders are preserved; existing profiles and version pointers are untouched. The managed resident must be stopped. **127 focused Python checks pass**, including 46 recovery checks, with scoped Ruff. Actual bundled-Python DPAPI backup/preview/restore and protected-record recovery across separate processes pass. [Evidence](qa/encrypted-profile-recovery.json).

Detached recovery still preserves original paths. Reviewed activation and initial typed path adapters are now implemented in the newest milestone; Native Setup is implemented above; further adapter coverage remains pending. Signing/license clearance, clean-machine acceptance, Android tooling/device tests and physical SIM/personal WhatsApp duplex media remain open. WhatsApp text/outgoing actions stay off.

## Desktop version slots and recovery tooling, 21 October 2026

[Version-slot management](DESKTOP_VERSION_SLOTS.md) adds explicit directory-based installation/selection, per-version owned data, verified interrupted-copy recovery, rollback to the previous version and its original data, and a resident-lifetime Windows manager lock. No existing profile is adopted and no package/data deletion, registry/startup change or download occurs. This remains an unsigned pilot rather than a signed Windows installer/updater. **82 focused checks**, scoped lint, full-package switching/rollback and actual installed native-resident startup/shutdown pass. [Native evidence](qa/desktop-install-native-verification.json).

Encrypted detached full-profile recovery is now complete in the milestone above. Next integration work is reviewed activation/path compatibility and Windows install/launch/uninstall UX, followed by signing/license clearance and clean-machine acceptance. Actual Android builds, provider setup and SIM/personal WhatsApp duplex-media acceptance remain separate gates; WhatsApp text/outgoing actions stay off.

## Portable Python/core desktop pilot, 21 October 2026

[Portable core runtime](PORTABLE_CORE_RUNTIME.md) is implemented and locally accepted. A fresh isolated CPython 3.12.10 runtime contains the 41 exact core dependencies, with no copied venv, pip, development tools or heavy optional models. The desktop core pilot uses its own Python and Electron; native workspace and one owned offline CAD build pass without external Python/npm resolution. This is unsigned development-host evidence, not clean-machine installation or production release acceptance.

Next independent milestone: explicit installation/version slots, isolated data ownership, recovery and rollback preparation. Signing/license review, clean-machine acceptance, Android tooling/device tests and physical SIM/personal WhatsApp duplex audio remain open. No provider/device/account configuration or WhatsApp text/outgoing action was enabled.

Updated 20 October 2026. This records the completed core/persistence milestones, JARVIS workspace, native resident, offline CAD, typed scene assembly, Image atelier and Vision studio v2 from [Implementation handoff](IMPLEMENTATION_HANDOFF.md). Read [Persistence](PERSISTENCE.md) for storage, migration and recovery contracts. The broader [architecture](INARA_REVAMP_PLAN.md) and [JARVIS interface plan](UI_AND_CODE_CLEANUP_PLAN.md) remain the roadmap. Read the newest section first; older "next" statements are historical checkpoints.

## Current requested priority: personal incoming-call assistant

The owner requests INARA to speak with incoming SIM and personal WhatsApp callers and take a message, then explicitly requires carrier independence and the existing personal account. These requirements supersede the earlier next-source order; message replies/sends and outgoing calls remain excluded. **A supervised desktop-bridge prototype and offline Command OS Call bridge lab are implemented; end-to-end live answering remains unverified.** The supported resident/UI runtime exposes synthetic checks only; the archived server was not revived. Android tooling was not found on PATH; no APK or connected call/audio route was validated.

The feasibility review checked official Android call/audio restrictions, Meta's business calling boundary, Microsoft Phone Link/Bluetooth and WhatsApp Windows human calling, plus documented HFP roles. These establish candidate experiments, not a working unattended AI bridge. The next gate is to prove exact incoming-call control and isolated two-way audio for both requested channels on real devices, through a hands-free device or a scoped desktop-client bridge. Carrier forwarding and Business-account conversion are not the selected solution. Universal coverage cannot be inferred from one working device, and a laptop bridge cannot answer while the laptop sleeps.

Implemented `backend/calls/` with strict enrollment, a compiled .NET UI Automation helper, dedicated WASAPI raw-stream routing, a tool-free Gemini Live adapter, a bounded one-call lifecycle and DPAPI-protected incremental/terminal records. The CLI starts only explicitly, waits for ready media/provider before Answer, rejects changed controls/callers, clears interrupted speech, stops matching calls on cancellation/deadline and never retries an uncertain answer. It has no owner history/tools, business migration, carrier forwarding or outgoing action. A seven-day-on-access, 256-entry separate lab ledger protects transcripts; no raw audio is retained. Source and operator procedure: [desktop bridge lab](IMPLEMENTATION_HANDOFF.md#desktop-bridge-lab-implemented-20-october-2026).

Latest acceptance: **103 call/lab/route-policy Python checks and 98 frontend checks pass**, plus types/contracts/lint/build. Actual Windows workers pass completion, Stop and stalled process-tree termination. Native Command OS acceptance passes readiness, synthetic record review, panel-close cancellation and 390px layout, with no physical media/provider/network requests. The optional audio adapter and explicit voice model/key are unconfigured. The broad core run reports 1,103 passes, 30 skips and three archived CAD-agent failures due to an unconfigured key, after excluding authenticator collection because NumPy is absent. [Current behavior, evidence and limits](CALL_LAB.md). Offline owner/project/session/resource integration and worker supervision are complete; live enrollment, usage admission, physical proof and phone receipt delivery remain pending. Missing call views do not establish termination; conservative UI fingerprints can reject legitimate repeat calls and do not supply an atomic platform call ID. This remains a source pilot with synthetic UI diagnostics, not production unattended answering or an Android call feature.

[Call-first handoff and remaining sequence](IMPLEMENTATION_HANDOFF.md#current-priority-incoming-call-answering-and-message-taking); [bridge experiment, architecture and acceptance](INARA_REVAMP_PLAN.md#call-only-completion-plan-20-october-2026). No driver, provider, account link, forwarding setting, permission, live call or WhatsApp action was enabled.

## Completed post-revamp milestone: reviewed creative handoffs

Latest packaging source milestone, 21 October 2026: [Node-free desktop workspace pilot](DESKTOP_WORKSPACE_PACKAGE.md) bundles the native main dependencies and installed Electron runtime, stages an integrity-checked pilot and resolves its fixed runtime layout without npm fallback. **37 packaging/native/release Python checks pass**, lint/PowerShell syntax/diff pass. Actual staged-core/staged-Electron UI acceptance passes five destinations at 390/1440px with external npm resolution disabled, no model/device workers and unchanged package integrity after exit. Python remains an explicit external dependency; this does not complete portable core, installer, signing, update or clean-machine gates.

Latest source milestone, 21 October 2026: [Android build acceptance tooling](ANDROID_BUILD_ACCEPTANCE.md) adds read-only preflight, explicit dependency recording, normal offline strict builds, source/dependency snapshots, fresh JVM/APK/signature audits and local hash receipts. **24 Android-build checks and 11 release checks pass**, including actual PowerShell preflight/missing-tool refusal; lint, syntax and Android source guards pass. JDK/Gradle/SDK remain missing, so no APK, dependency records or phone acceptance are claimed. The next actual Android gate is toolchain provision, reviewed dependency recording and a real clean debug build.

Artifacts now offers an explicit destination for saved CAD/image recipe references. The destination review preserves the current draft until Apply; generation remains separate. Source UUID/fingerprint/export digest are checked against successful owner/project receipts before planning/building and again before queued workers start. Resulting protected job receipts retain source provenance. Pending briefs stay out of global state and clear on close/project/disconnect/lock. [Behavior, evidence and remaining priorities](CREATIVE_HANDOFFS.md).

Acceptance: **235 focused Python checks, 106 frontend checks**, types/contracts/lint/build and actual native two-way handoff review/apply/discard/stale-draft acceptance pass. No extra worker/provider call was triggered by handoffs; seven verification workers (six offline CAD and one synthetic image) exited. Recipe metadata is supported; pixel analysis, image conditioning and geometry inference from images are not implemented. Physical call proof, Android/device/provider acceptance and signed distribution/recovery remain open.

## Completed post-revamp milestone: Command OS UI refinement

Reviewed multi-object scene proposals are [implemented](SCENE_PROPOSALS.md). The existing AI blueprint route accepts a bounded scene target, previews one to eight typed parts and requires Apply followed by a separate approved build. Per-provider-call usage admission, cancellation, stale-project rejection and protected revisions remain intact. **215 focused Python passes / one Blender skip; 102 frontend passes**, types/contracts/lint/build and actual native review/preview/apply/offline-worker acceptance pass. No real provider or physical capability was activated. Reviewed recipe-reference handoffs are now implemented above; real calls still require physical bridge proof first.

Assistant, Studio, Inbox, Tasks and Connections share a new persistent shell, docked lazy tools, collapsible context inspector and activity tray. Preferences can open over a creative tool without losing its draft. The refreshed visual system includes compact navigation, distinct Studio artwork, readable multiline chat and narrow bottom navigation. Shared feature content/error handling replaces the duplicated modal registry, and conversation/overview/inspector/tray styling and responsibilities are separated. Existing read-only phone notifications are surfaced through the current-project Inbox without granting access or invoking AI. [Implementation and limits](UI_AND_CODE_CLEANUP_PLAN.md#command-os-ui-refinement-20-october-2026).

Acceptance: **98 Node checks**, transport types, generated-contract drift, production build and verification-script lint pass. Actual hidden native shell acceptance passes five destinations at 390/768/1440/2560px, keyboard navigation and focus restoration, modal-over-dock draft preservation, setup/error/retry, reduced motion and 200% zoom/text. The synthetic native run activated zero device/provider/creative workers and no media or external network; short resident working set recovered from **65.56 MB before opening to 66.82 MB after UI exit**. Final evidence: `.runtime/command-qa/run-24beceb5-7ee9-4f46-b181-334773e8fb6e/verification.json`, also retained as [Command OS verification](qa/command-os-verification.json). Reviewed screenshots: [Assistant](qa/command-os-assistant.png), [Studio](qa/command-os-studio.png), [narrow Inbox](qa/command-os-inbox-390.png). These short fixture figures are not a gaming or sustained hardware benchmark. Android/provider/device/release acceptance and WhatsApp AI/actions remain deferred. Typed multi-object scene proposals are next.

The adapted offline renderer also passes all nine shared feature interiors, offline action guards, text scaling and bundled tracking on a synthetic canvas (`.runtime/ui-qa/verification.json`). Native mobile acceptance passes pairing, notification redaction/deduplication/clearing, revocation and replay rejection, with its listener released (`.runtime/mobile-qa/run-719eba2c-b0ad-4f71-ae6d-7e1ee89849b4/verification.json`). Native memory acceptance passes textarea sending, source citations, reviewed memory changes, retention and protected backup/recovery, with its fake provider closed (`.runtime/memory-qa/run-fb391774-d1af-4ece-a598-a65805b298ea/verification.json`). No physical phone or paid provider was used.

## Completed post-revamp milestone: connection adapters and readiness

Lazy Kasa discovery/control, printer data/mDNS and bounded OctoPrint/Moonraker clients are separated; exact endpoints, saved credentials, shared approvals, observation ownership and durable print receipts are preserved. The polished Connections readiness view reads local metadata/cache without initializing adapters or contacting devices. **1,053 full-regression Python passes / one Blender skip; 94 Node passes**, final focused adapter/device/print checks, type/drift/lint/build and real hidden renderer acceptance at desktop/390px. Native readiness activated zero adapters and short resident recovery was about 66.5 MB. [Evidence and limits](CONNECTION_ADAPTERS.md). Actual SDK/hardware/provider acceptance remains pending. Typed multi-object AI scene proposals are the next source milestone, using fixtures while configuration stays deferred.

## Completed post-revamp milestone: reviewed desktop tasks

Manual one-to-eight-step immutable plans now use existing project file/app tools with fresh approval for every step, protected durable receipts, origin-bound cancellation and conservative interruption recovery without replay. The responsive JARVIS workspace provides editing, review, progress, previews and uncertain-result guidance. **1,004 full-regression Python passes / one Blender skip; 51 final queue checks; 89 Node passes**, type/drift/lint/build and actual native fixture acceptance at desktop/390px. Short resident recovery was about 68 MB. [Behavior and acceptance](REVIEWED_TASKS.md). Real apps/providers/hardware were not used. Device/printer protocol separation and Connections readiness are now implemented above; Android and distribution acceptance stay gated.

## Completed post-revamp milestone: Web inspector and adapter cleanup

Read-only public HTTPS research now replaces the retained autonomous browser: typed requests, shared owner approvals, bounded owned worker, inert page content, ephemeral results and cancellation. Printer observation is separate and stops with the last owner workspace. **954 Python passed / one Blender skip, 83 Node passed**, types/contracts/lint/build and hidden native fixture acceptance at desktop/390px. Short resident recovery was about 67 MB. [Evidence and remaining limits](BROWSER_INSPECTOR.md). No live public network/provider/hardware acceptance is claimed. Interactive browser/desktop automation remains open; the reviewed typed desktop task queue is now implemented above.

## Completed post-revamp milestone: usage and quality

Acceptance: 911 Python passes / one Blender skip, 78 Node passes, type/drift/lint/build and all 12 offline contract evaluations. Native acceptance uses only synthetic provider/data; actual provider invoice and model-quality acceptance remain deferred.

Usage & quality adds explicit owner-wide daily/monthly authorization allowances, per-invocation admission across desktop/phone chat/CAD/transcription, sanitized provider token receipts and local job duration receipts. It defaults to monitor only and does not claim to measure invoices. The fixed 12-case offline assistant/memory/budget/CAD/image suite runs in an owned disposable process/profile, with no real provider or user data. [Coverage and acceptance limits](USAGE_AND_QUALITY.md). Read-only browser and printer observation modernization are now implemented above; configuration and release/device gates remain open.

## Completed post-revamp milestone: project memory

Verification: 865 Python regression passes / one Blender skip, 72 Node passes, focused integration checks, type/drift/lint/build and actual hidden desktop memory/recovery/source-citation acceptance. No paid API or real user data was used.

Owner-reviewed facts/preferences/decisions, source/tag editing, local lexical search, expiry/archive/forget, protected same-profile backup, non-overwriting recovery preview/apply and explicitly opted-in assistant context/source citations are implemented. No automatic extraction, embedding model, plaintext index, mobile memory grant or model write tools were added. [Project memory behavior and evidence](PROJECT_MEMORY.md). Usage budgets and quality evaluations are next for source work; release/tooling/device gates remain open.

## Current milestone: R8 source complete, release acceptance pending

R8 adds the selected read-only notification inbox, separate per-device/project grants, explicit app/conversation rules, metadata-only defaults/redaction, encrypted bounded retention, ordered removal tombstones, duplicate-safe manual sync, local count summaries and visible revoke/clear controls. The native Android collection/access/sync gate remains off until compilation and controlled device acceptance. No WhatsApp drafts/replies/actions or calls were added. [Behavior and verification](R8_NOTIFICATIONS.md).

Current acceptance: **810 Python passes / one Blender skip, 66 Node passes**, plus type/drift/lint/build, source guards and native desktop notification/TLS fixtures. Android native build/device acceptance remains unrun.

Offline support diagnostics, dependency/license metadata inventory, source-pilot staging/hash verification and a machine-readable release/backlog inventory are implemented. They do not imply a signed installer or standalone release. [Remaining release gates and advanced-feature backlog](RELEASE_READINESS.md).

## Completed behavior

The supported `backend/server.py` now starts with the lean core environment and serves typed conversation without an `AudioLoop`, microphone permission, camera or voice connection. Google SDK clients initialize on a text request and are closed afterwards. `INARA_TEXT_MODEL` selects the text model; the initial default is `gemini-3.8-flash`.

Requests and results are validated and carry UUID conversation/request IDs. Durable encrypted conversation history is scoped to the desktop client and project, with bounded restored context and serialized turns. Duplicate request IDs return the prior result or error without replaying the provider work; conflicting payloads are rejected. Missing credentials, invalid input, provider failure and timeout have structured, sanitized errors.

Project file reading/writing and app launching use the common dispatcher. Arguments are validated, configured denials are enforced, approvals expire and are bound to the requesting client, and authorization is checked again before execution. File access rejects traversal, absolute/drive/UNC paths and alternate-data-stream syntax, resolving existing symlinks/junctions before containment checks. Voice file operations use the same containment rule.

Temporary projects and the selected project survive startup. Reminder claiming, schedule advancement and occurrence records commit together; leased delivery retries retain their IDs, and authenticated receipt/completion survives restart. Legacy reminder, routine and project chat migration preserves originals and encrypted snapshots. UTC/IANA recurrence and missed-occurrence policy are documented in [Persistence](PERSISTENCE.md).

Optional audio, camera, CAD, browser, Kasa and printer implementations are imported on demand. Printer hydration/monitoring starts on printer or voice activation; semantic camera watches run when requested frames and watches are present. The FastAPI lifespan owns background-task cleanup. Legacy socket names remain available through the supported server.

The native desktop supplies stable client identity and a random launch token over an inherited pipe and trusted preload IPC. Explicitly configured manual-development tokens are supported. Allowed browser origins are restricted. The chat input shows processing/disconnected states, and duplicate typed response events do not append the same reply twice. The development command sets `INARA_DEV_SERVER=1` correctly.

## Development baseline

A local Git repository and pre-change checkpoint were created: `db88277`. Existing settings, keys and project data remain outside source control. Python 3.12.10 and checksum-verified portable Node 24.21.0 were used locally. Core and development dependency versions are recorded in separate lockfiles. The original full `requirements.txt` remains the optional legacy-feature installation path.

Use `scripts/bootstrap.ps1 -Dev` for the reproducible environment and frontend build. If the normal npm registry cannot establish a valid TLS connection, `-Registry https://registry.npmmirror.com` selects the mirror explicitly while preserving npm integrity checks. No global registry setting or disabled TLS validation is required.

`scripts/start.ps1 -BackendOnly` starts the lean backend. `scripts/start.ps1 -Dev` starts the development desktop, and `scripts/start.ps1` opens the built desktop once Electron's executable is installed. AI responses require a valid `GEMINI_API_KEY` in `.env`.

## Verification

- 31 deterministic checks passed across the new conversation tests and the retained desktop runtime smoke tests.
- Covered independent text responses, credentials and invalid requests, provider failure redaction, conversation/project ownership, duplicate IDs, real SDK schema conversion and tool signatures, permission denial, approval owner binding/expiry, path escape rejection, temporary-artifact preservation, startup and cleanup, and the legacy event contracts.
- Ruff checks passed for the new services and milestone tests. Python dependency compatibility checks passed.
- The Vite production build passed, transforming 2,054 modules. The existing large single JavaScript bundle remains a performance issue for the planned UI/lazy-loading milestone.
- Changed desktop and transport JavaScript passed Node syntax checks.

The npm download initially failed certificate validation on the primary registry connection. Installation succeeded through a TLS-verified mirror with the checked-in lockfile's integrity checks. The build required execution outside the sandbox because esbuild's parent-directory resolution was denied inside it.

No paid AI requests, real app launches, camera sessions, printer actions or phone calls were used in verification. Electron's executable was installed separately after the frontend build-only dependency install; the native desktop window has not been visually verified. Optional legacy audio/CAD/device libraries and current provider-model compatibility still need their own integration tests. The Windows CI workflow is configured but has not run on GitHub.

## Remaining boundaries

The typed tool path exposes project files, configured app launching, validated local reminders and offline parametric CAD jobs. Direct snooze/cancel uses the common dispatcher; CAD builds share the existing generation permission. Typed scene assembly and an optional Blender bridge are implemented; actual Blender execution awaits an installation. Image atelier and its local generation adapter are implemented; real diffusion inference remains unconfigured/unverified. Local speech, advanced vision, Android and telephony remain subsequent work. Some legacy direct handlers still require policy migration, and the legacy voice dispatcher remains separate. This is a local desktop implementation, not a remotely exposed automation service.

Completed typed history and request ledgers are encrypted before SQLite/WAL writes. Restored context is limited to twenty completed messages. Windows DPAPI is user-bound; portable private export, device pairing, scoped credentials and retention controls remain planned. CAD worker ownership and manual resource/gaming policy are implemented; GPU/thermal admission and isolation of other legacy workers remain open. Legacy voice histories remain a separate adapter; existing settings/artifacts retain their formats. The legacy face-landmark gate does not become strong OS authentication through this change.

The command deck, responsive workspace, local reminder panel, lazy 3D/camera loading and resident close/reopen are implemented. Electron is now pinned to 44.7.0 and runs only while a workspace is open; the native host replaces its resident overhead. Optional adapter interiors and creative worker isolation remain subsequent work. WhatsApp reply drafting and sending are excluded until specifically requested; no automatic replies were added.

## Next milestone

R2b3 Kasa/printer compatibility is next. R2b1 and R2b2 are implemented; the whole R2b milestone remains incomplete. [Settings/lifecycle policy](SETTINGS_LIFECYCLE_POLICY.md) records the independent owner gate, strict transports, atomic settings and native/fallback evidence. The matrix identifies remaining groups. Configuration and real-game benchmarking remain deferred.

## Second milestone verification (13 October 2026)

- Versioned encrypted SQLite user data, request ledger, project selection and reminder delivery are implemented without API configuration.
- 56 Python checks pass, covering both milestones, Windows DPAPI round trips, protected database/backups, migration validation/rollback, session restart without tool replay, uncertain requests, concurrent services/pollers, transport failure, acknowledgements, stale alert edits, cancellation/snooze, timezone filtering and DST recurrence.
- Two Node state tests pass for simultaneous alert queueing, duplicate deliveries and reconnect snapshots. The production Vite build passes. Ruff and dependency consistency pass.
- Tests use temporary user data, fake providers and fake transport. No production data migration, paid requests, phone/device actions or native desktop visual verification was performed. The build still reports the existing large bundle, old browsers data and Vite CJS warnings; the JARVIS/lazy workspace milestone will address the frontend structure.
- The local desktop recipient rule does not implement Android delivery ownership or pairing. Closing the current desktop shell still stops its backend; resident lifetime is next. WhatsApp replies remain excluded.


## Resident and JARVIS workspace verification (13 October 2026)

The command deck and resident lifecycle foundation are implemented, including tray/hotkey reopen, explicit graceful quit, generic resident reminder notices, gaming suppression/gating, responsive command/Studio/connections views, local reminder creation and deferred camera/landmark loading. Source modules are separated by lifecycle and feature responsibility.

61 Python checks and eight Node checks pass, along with lint, dependency consistency and production build. Hidden renderer tests verify 1440, 768 and 390 CSS-pixel layouts, modal behavior, icon labels and absence of heavy startup assets. Rendered screenshots are in [docs/qa](qa/command-desktop.png). Native close/reopen uses the same backend and verifies reminder receipt, gaming state and graceful quit with fresh isolated data. Notification display is stubbed. Bundled tracking initialization passes with an empty test stream; no real camera or paid provider is used.

Initial JavaScript is approximately 241 KB uncompressed / 76 KB gzip; CAD is a separate approximately 902 KB chunk. The immediate resident snapshot retained roughly 400 MB of Electron working sets; the 150 MB resident target is not met, and a ten-minute idle/game benchmark is outstanding. The implementation is a functional foundation, with resident footprint reduction explicitly remaining open. Details and limits are in [Resident and workspace](RESIDENT_AND_WORKSPACE.md).

## Native resident follow-up (13 October 2026)

The default Windows host now runs Win32 tray/hotkey and the ASGI core in one Python process, with Electron solely for an open workspace. It preserves the old profile/identity, transfers credentials by pipe/IPC, owns the entire workspace tree through an atomic Windows job, delivers scoped reminders directly and treats native gaming selection as authoritative. Startup/registration timeout, busy-port failure and tray retry are implemented. The older Electron host remains an explicit fallback.

69 Python and eight frontend checks pass. Electron 44.7.0 passes hidden responsive UI/tracking initialization and the retained fallback lifecycle integration. The final ten-minute run, including the owned Python launcher, averaged 64.86 MB working set (65.30 MB peak) at 0.3802% of one CPU core, with 47.54 MB peak private bytes and no resident Electron processes. First workspace open/reopen took 2.516/2.188 seconds after core readiness. Busy-port retry, workspace crash cleanup and graceful quit pass. Final combined-process evidence, acceptance limits and the deferred game benchmark are recorded in [Native resident](NATIVE_RESIDENT.md). The earlier approximately 400 MB Electron measurement above is historical.

## Offline CAD Studio verification (14 October 2026)

The shared typed generation tool now builds boxes, L brackets and open enclosures in an owned stdlib worker, without audio, a CAD kernel or an API key. The responsive JARVIS panel offers dimensions, orbit/wireframe, scoped history and real STL/GLB/recipe downloads. An optional provider proposes schema-validated recipe data for review. Existing voice CAD remains available.

98 Python and nine frontend checks pass, with build, lint and dependency consistency. Real native UI verification covers each shape's expected volume, rendered preview, GLB import, all downloads, narrow layouts, history restoration without rebuilding and missing-key planner behavior. Three workers exit; geometry stays outside the resident. After workspace exit, six recovery samples remained around 64.86 MB combined working set / 47.32 MB private bytes. This is a ten-second recovery observation, not a new idle/game benchmark. [CAD evidence and limits](CAD_STUDIO.md) records actual Blender/STEP/complex-shape exclusions and the bounded transport shutdown behavior after injected crashes.


## Scene assembly verification (14 October 2026)

Typed scenes now support up to eight boxes/brackets/enclosures with per-object dimensions, positive scale, XYZ rotation, translation and four materials. The responsive Studio adds object selection, add/duplicate/remove, material-aware GLB preview and immutable STL/GLB/recipe revisions. Scene bounds and summed part volumes are shown accurately; this does not add boolean unions or arbitrary modeling. Existing encrypted scopes, permissions, old recipe deduplication and owned worker cleanup are retained.

The optional bridge detects an installed Blender and runs a fixed background import/export/project/render script as an owned descendant, with bounded CPU threads, timeout and artifacts. No Blender installation exists here, so the real round-trip test is skipped and actual `.blend`/render/export remains unverified. Offline scenes work without it or API configuration.

116 Python and nine frontend checks pass, along with build, Ruff and dependency consistency. Actual hidden renderer verification passes three-solid regression, scene object editing/transforms/materials, GLB download/import, narrow layouts and history restoration without rebuild. Four workers exit, scene/geometry modules remain outside the resident, and six post-workspace samples stay at 64.97-65.04 MB working set / 47.54 MB private bytes. This is a ten-second recovery observation. [Scene Studio](SCENE_STUDIO.md) records contracts, screenshots, evidence and remaining Blender limits. No paid or phone actions ran; the real-game benchmark remains deferred.


## Image atelier verification (14 October 2026)

Image atelier now offers prompts, frame/seed/quality controls, preview, PNG/recipe download and protected revisions. A fixed local SD/SDXL adapter loads only in an owned worker after explicit generation, without downloads or a cloud API. Configuration remains deferred and no real image model ran. The normal UI explains missing setup and disables generation.

CAD/image lifetimes and authenticated RPCs now share services, preserving old CAD contracts and adding one creative execution slot across CAD/Blender/images. 144 Python and nine frontend checks pass, plus build, Ruff and dependency consistency. Actual native renderer verification exercises unconfigured behavior and explicitly labelled test-only fixture revisions/downloads/reopen/cancel at 1440/768/390 widths. Production rejects fixture provenance. Three fixture workers exit and six recovery samples show 65.12-65.18 MB working set / 47.51 MB private bytes; this does not measure diffusion/GPU recovery. The existing real CAD/scene workflow also passes after refactoring. [Image atelier](IMAGE_ATELIER.md) records evidence, model/setup limits and the next vision milestone. Real Blender and image-model acceptance, remote CI and gaming benchmarks remain unverified/deferred.


## Roadmap reconciliation (14 October 2026)

A planning-only review against `5f79902` now defines R1 Vision, R2 core/policy cleanup, R3 typed shared UI/activity, R4 capabilities/resources, R5 creative workflows, R6 voice/quick panel, R7 Android pairing and R8 notification summaries. Source ownership, follow-on tracks and acceptance gates are recorded in [the architecture roadmap](INARA_REVAMP_PLAN.md#current-baseline-and-implementation-sequence-14-october-2026) and [refactor map](UI_AND_CODE_CLEANUP_PLAN.md#remaining-refactor-work-tied-to-the-implementation-sequence). These are planned changes, not completed runtime features. Configuration and real-game benchmarking remain deferred, personal WhatsApp replies remain excluded, and live model/Blender/phone acceptance remains pending.


## Vision studio v2 verification (14 October 2026)

R1 implementation adds explicit camera/tracker state, source selection, mirror/overlay/rate controls and two-hand overlays. Capture/session, inference scheduling, worker protocol and rendering now have separate owners. The classic Web Worker runs the bundled local model with one transferred frame in flight, stale-result rejection and bounded initialization/inference. Stop, device loss, source switch, panel/visibility/native power events and gaming release resources; restart is explicit. Two unused legacy hooks and the global camera CSS block are retired.

146 Python and 26 frontend checks pass, plus production build, lint and dependency consistency. Real renderer/model checks use synthetic camera streams: blank-frame inference is genuine; injected overlay landmarks are visibly labelled fixtures. Seven workers terminate, all tracks end, no remote assets load and the native core stays free of vision-model imports. Six post-workspace samples remain 63.63-63.83 MB working set / 46.60-46.86 MB private bytes. [Vision evidence and acceptance limits](VISION_STUDIO.md) records actual camera/hand and physical sleep/device checks still pending. This is short recovery, not a game benchmark. R2a is the next implementation.

The retained fallback host lifecycle check passes after fixing reminder destination priority: resident mode selects its tray/native recipient ahead of stale renderer connections; Studio still prefers the renderer. Two destination regressions are included in the 146 Python checks.


## Core composition/session extraction verification (14 October 2026, R2a)

The injected application root now owns construction, FastAPI/ASGI lifetime, reminders, creative services and event delivery. Desktop sessions own handshake identity/roles/native binding and project snapshots. Conversation/reminder transports register existing wire contracts independently of the server facade. Startup rollback, repeated lifetime and shutdown failure paths release pollers/subscriptions. The final owner disconnect resolves approvals; another connected owner channel keeps its approvals.

161 Python checks pass (one real-Blender skip), including 15 new boundary checks; all 26 frontend checks and scoped Ruff pass. Actual native failure/reopen/reminder/gaming verification, CAD/scene render/export/restore and labelled image-fixture cancellation/revisions pass. Short native idle measured 65.57 MB mean working set / 48.03 MB peak private bytes including the launcher, with zero Electron processes. Existing bounded Engine.IO shutdown timeout logs remain in the injected-crash scenario. No new real-model/hardware acceptance is claimed. [Evidence, migration inventory and remaining legacy seams](CORE_COMPOSITION.md). R2b is next.


## Route-policy checkpoint verification (14 October 2026, R2b1)

52 socket routes, `/status`, 15 shared tools and 26 legacy voice declarations are inventoried with schema/caller/context/effects/policy/response/lifetime/replacement fields. Seven direct desktop/device actions now share strict schemas and dispatcher policy with typed model tools. Renderer/auth checks, scoped responses and stamped event ownership prevent those actions from broadcasting across owners. Origin disconnect/app close cancels tracked local requests; shared confirmation input is strict and owner-bound.

222 Python checks pass (one real-Blender skip), including 61 new policy checks; all 26 frontend checks and scoped lint pass. Actual native failure/reopen/reminder/gaming/shutdown verification passes, with short idle 65.61 MB mean working set and zero Electron processes. Desktop/device action tests use injected adapters; no real app/device/screenshot/clipboard action is claimed. [Migration, evidence and remaining bypasses](ROUTE_POLICY_MIGRATION.md). R2b2 settings/lifecycle is next; remaining legacy groups are explicitly pending.


## Settings/lifecycle verification (16 October 2026, R2b2)

Owner-only settings/permission reads and mutations, strict native/resource requests and fallback resident-only shutdown are implemented in injected transports. Settings authorization is outside editable tool permissions; locked/wrong-role/foreign calls cannot grant themselves access. Atomic replacement precedes in-memory commit. Native gaming and fallback resident gaming override renderer requests; restricted transitions release creative/local/media work and report cleanup failures without lifting restriction. Native identity registration and owner safety cleanup remain usable while face-locked.

288 Python checks pass (one real-Blender skip), including 66 new policy checks; all 26 frontend checks, build and lint pass. Real native admin socket checks prove persistence/reconnect, schema/role denial and scoped settings; a fresh profile verifies owner registration before renderer hydration, alongside native reopen/reminder/gaming/shutdown and fallback lifecycle checks. Short idle is 66.72 MB mean working set / 49.48 MB peak private bytes with zero Electron processes after close. The initial intermittent scene-worker failure, subsequent passing run and remaining legacy limits are recorded in [evidence and limits](SETTINGS_LIFECYCLE_POLICY.md). R2b3 is next.

## Combined compatibility and workflow policy checkpoint (R2b3)

Kasa/printer setup and a contained, staged print workflow now use injected owner-scoped services. Slice/upload/start have independent shared permissions; uploads cannot implicitly start a printer. Protected attempt records prevent replay after cancellation, uncertainty or restart. Reminder UUID receipts/role gates and canonical CAD planner authorization are implemented. See [implementation and verification limits](DEVICE_PRINT_POLICY.md) and the refreshed [route matrix](ROUTE_POLICY_MATRIX.md).

Remaining memory/media/legacy creative/browser routes and voice/event ownership keep R2b open. No provider/hardware configuration or WhatsApp reply behavior was added.

Final verification: 377 Python checks passed, one Blender-dependent skip; 26 frontend checks, scoped lint, production build and actual native/fallback/CAD desktop integration passed. CAD advisory progress now tolerates the reproduced Windows replacement sharing failure. Earlier native timing failures and hardware acceptance remain documented in the checkpoint evidence.

## Workspace compatibility checkpoint (R2b4)

Ten remaining memory/media/legacy CAD/browser wire routes use strict owned services, shared action policy and scoped callbacks. Legacy session approvals expire and cannot resolve across stopped generations; unstamped bus events remain internal. Typed conversations now carry trusted origin context and cancel on disconnect/shutdown. Project transcript exports preserve existing files. See [workspace contracts, verification and limits](WORKSPACE_POLICY.md).

Legacy voice schema/dispatcher parity, connection/face lifecycle and hard isolation remain explicit follow-up work before R2c/R3. No provider or hardware configuration and no WhatsApp reply functionality was added.

462 Python checks pass with one Blender-dependent skip; all 26 frontend checks, lint/build and actual native/fallback/CAD desktop integration pass. Short native idle remains about 67 MB with zero Electron processes after close.

## Shared voice and connection checkpoint (R2b5)

The two authorized steps are implemented: 37 live voice functions share validated dispatcher execution, and connection/private hydration plus face worker lifetime belong to the application. Owner/session guards survive approvals and delayed bus delivery. Missing face setup is rejected before enabling it; heavy camera/model work stays in a bounded owned process. See [implementation, tests and hardware limits](VOICE_CONNECTION_POLICY.md).

R2c can now retire unused voice declarations, ad-hoc helper/confirmation paths and dead facade lifecycle references. Provider/model setup, real media/face/device behavior and generated-code/browser hard isolation remain deferred/unverified. WhatsApp replies remain excluded.

666 Python checks and 26 frontend checks pass, with one Blender-dependent skip. Lint/build and actual native/fallback/CAD desktop integration pass. Short native idle is about 67 MB with zero Electron processes after workspace close.

## R2c cleanup complete

Duplicate static voice catalogs/helpers, fallback approvals and obsolete facade/lifecycle hooks are retired. Live configuration uses generated shared schemas; `ConfirmationTransport` owns strict renderer confirmations. The inventory remains 52 socket routes, 53 tools and 37 voice functions. 668 Python and 26 frontend checks pass, with one Blender skip; lint/build and native/fallback/CAD integration pass. [Retirement map, evidence and limits](RETIRED_PATHS.md). R3 shared UI/RPC and JARVIS panel consolidation is next.

## R3a UI/RPC foundation

The shared responsive JARVIS panel header/loading/recovery surfaces and panel-owned TypeScript RPC scope are implemented. Image atelier is the first migrated feature, with generated request contracts, no automatic replay, reconnect history recovery and stale-callback/snapshot guards. 34 frontend and 104 focused Python checks plus build/lint/drift and native image/CAD integration pass. Semantic compiler verification is pending because registry certificate validation blocked installation; no full frontend type-check claim is made. [Evidence, screenshots and R3b task](R3_UI_RPC.md).

## R3 completed

The command palette, unified project Activity/artifact view, shared JARVIS panels/approvals/forms, embedded legacy interiors, scoped CAD/image/planner lifecycle, generated contracts/version and feature-specific event bridges are implemented. Captured text-event scope prevents cross-project late updates. The project-local pinned compiler resolves the earlier semantic-check gap. 669 Python and 41 Node checks pass, with one Blender skip; semantic/drift/lint/build and renderer/native creative acceptance pass. [Evidence and material limits](R3_UI_RPC.md). The next milestone is R4 capabilities and resource-aware job ownership.

## R4 completed

Capability/setup diagnostics, shared fixed model/worker profiles, bounded FIFO creative admission with CPU/RAM/VRAM estimates, explicit per-job background continuation, and queue/process release are implemented. OS probes are on demand and do not import heavy models. Panel-close cancellation remains the default; workspace/core closure and gaming still stop background work. [Implementation, verification and deferred hardware acceptance](R4_RESOURCE_LIFETIME.md). The next whole milestone is R5 Creative Studio v2.

R4 validation: 690 Python tests and 46 Node checks pass, with one Blender skip; semantic types, contracts, lint/build and native fixture/CAD/lifecycle acceptance pass. Short native idle is 67.24 MB mean with zero Electron processes; longer/gaming and physical/provider acceptance remain deferred.

## R5 offline creative workflows completed

CAD/image drafts now share bounded undo/redo, explicit immutable branch ancestry, comparison and recipe reuse. Selected scene objects have numeric and draft translation controls, saved view bookmarks and reviewed data-only change proposals with stale-base rejection. The image gallery is explicit and bounded; Blender presentation presets remain fixed data. Kernel-backed geometry and actual Blender/image/provider acceptance remain deferred/unavailable. [Implementation and evidence](R5_CREATIVE_STUDIO.md). The next whole milestone is R6 quick assistant and voice consolidation.

R5 validation: 707 Python tests and 52 Node checks pass, with one Blender skip; semantic types, generated contracts, lint/build and native CAD/image workflows pass. Five CAD and four labelled image workers exited; short resident recovery remains about 67 MB. Actual providers/Blender/image models/kernel/device and gaming acceptance remain deferred.

## Completed R6 quick assistant and reviewed speech

The compact responsive JARVIS surface, native hotkey/focus routing, typed fallback, explicit preparation/hold/release/review/send, streamed transcript updates after release, optional local synthesis and interruption are implemented. A single bounded PCM/session path uses the common conversation/dispatcher and retires both always-on constructors. Fixtures cover policy, scope, cancellation, device ownership and native AudioWorklet lifecycle. Physical speech accuracy/latency, Bluetooth/sleep and actual provider/local voice acceptance remain deferred. [Implementation, evidence and limits](R6_QUICK_ASSISTANT.md). R7 secure Android pairing is next.

R6 validation: 733 Python tests and 60 Node checks pass, with one Blender skip. TypeScript, generated-contract drift, Ruff and the production build pass. Native synthetic-speech and Electron fallback lifecycle acceptance pass; post-close native resident recovery is about 66 MB. Actual microphone/provider/local voice, Bluetooth/sleep and creative/device acceptance remain deferred.

## R7 Android source and verified desktop/server pairing

Opt-in private TLS, owner-confirmed expiring invitations, signed device requests, durable replay/expiry/revocation, project-bound read-only status/job previews and separately granted tool-free chat are implemented. The desktop JARVIS pairing/revocation flow passes actual loopback TLS fixture acceptance at desktop/mobile widths. Phone history is isolated from desktop history and uncertain request receipts never retry provider work. [Behavior, protocol and evidence](R7_ANDROID_FOUNDATION.md).

Native Kotlin/Compose/Keystore/encrypted-state/outbox source and a pinned offline-first build entry are present. No configured JDK/Gradle/Android SDK/ADB exists here, so no APK, JVM Android test, emulator, Fold8 or Keystore execution is claimed. Source/manifest guards pass and declare only INTERNET. QR encoding remains an uninstalled optional adapter; file transfer is verified. R8 read-only notification source is next, with actual phone permissions/build/device acceptance still gated. SIM/personal WhatsApp, provider/hardware setup and benchmark deferrals are preserved.

R7 validation: 773 Python tests and 63 Node checks pass, with one Blender skip. Types, generated-contract drift, Ruff, production web build, source/manifest guards and native loopback TLS/desktop pairing checks pass. The final request-body and embedded-listener refinements also pass the focused 40 Python mobile checks. Android compilation/JVM/Keystore/device tests remain unrun because tooling is unavailable; no hosted CI run is claimed.
