# INARA implementation handoff and model choice

## Standing instruction: preserve deferred work

The owner explicitly requires deferred items to remain tracked across every implementation and handoff. Read [Deferred work and standing constraints](DEFERRED_WORK.md) and [release gates](RELEASE_GATES.json) before proceeding. Update both when a decision or evidence changes, and mention relevant outstanding deferrals in completion updates. A generic continuation request does not automatically resume deferred configuration/downloads/device testing or excluded WhatsApp actions. Source/fixture completion must stay distinct from real acceptance.

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

[Managed updates](MANAGED_UPDATES.md) adds separate current-account DPAPI checkpoints with encrypted before/after metadata images and public policy history, independently retained checkpoint pins, dual old/new publisher/reviewer policy approval, and review-bound enrollment/renewal/rotation/update/rollback. New local packages are copied and authenticated before selection; rollback retains the sequence high-water mark. Journaled installation/grant/anchor writes support exact reviewed resume or cancellation before metadata commit. Adopted roots use format 3, which unsigned controls refuse; managed launch checks checkpoint/source/profile/current trust under existing lifetime guards.

**281 focused Python checks pass**, including 31 managed-state tests, with scoped Ruff. Actual account protection/corruption/unsigned-metadata refusal and updated 2,672-file portable controller/bootstrap checks are recorded in [execution evidence](qa/managed-update-verification.json). Synthetic key rotation, package intake, rollback and commit-boundary recovery never approve real ownership or run real application code. No production root/identity is configured; both production policies remain disabled and all 85 real reviews remain pending.

Next: controller-specific provenance/notices and a reviewable native format-3 management UX for status/update/recovery/backup/removal, then owned signed-bootstrap delivery and clean-machine resident/Electron/job acceptance. Checkpoint rollback resistance still depends on the trusted external latest pin; it is not a hardware counter or compromise-resistant account store. Keep original packages through commit/recovery, preserve unknown partial files and never use unsigned controls to downgrade managed metadata. Existing unmanaged roots remain unchanged, and WhatsApp text/outgoing actions stay off.

## Renewable authorization and guarded launch, 22 October 2026

[Admission and launch](ADMISSION_LAUNCH.md) adds separate domain-signed, root/installation/slot/source/policy-bound launch grants with distinct publisher/reviewer thresholds and bounded renewable validity. Reviewed admission retains exact grant history and atomically commits its head; externally retained latest-head pins reject stale local state. The controller rechecks current trust, installed bytes, profile ownership and native signatures under file leases and the manager lock, then starts only the selected isolated resident in a suspended-start, kill-on-close Job Object. Expiry and controller death stop the contained tree. Original package expiry is superseded only by an explicit fresh signed grant, never by a generic ignore-expiry option.

**250 focused Python checks pass**, including 33 new grant/process checks, with scoped Ruff. Actual isolated-Python finite execution, file-write denial, expiry and controller-death child/grandchild cleanup pass. A 2,670-file controller is assembled and verified; bootstrap status and missing-configuration/pin refusals are checked. [Evidence](qa/admission-launch-verification.json). No actual INARA resident, production grant/installation, identity, provider or phone configuration occurred; both production policies remain disabled and all 85 real reviews remain pending.

Next: independently retained update/trust state, review-bound policy/key rotation and transactional signed update/rollback rules. Current head protection depends on a trusted external latest pin, not a hardware counter or compromise-resistant local store. Controller notices/provenance, owned signed-bootstrap delivery and real native UI/clean-machine acceptance remain pending. Legacy unsigned controls remain separate; WhatsApp text/outgoing actions stay off.

## Windows verification and portable controller, 22 October 2026

[Windows controller preparation](WINDOWS_CONTROLLER.md) adds a native cache-only WinVerifyTrust adapter, explicit external signer/timestamp leaf-certificate pins, a final-byte portable controller inventory and an independently trusted PowerShell bootstrap that verifies all files before starting bundled Python. Authenticated install/recovery retains reviewed signature/audit/ledger capsules before registration. The read-only launch contract checks current authorization, installed bytes and profile binding; the controller also requires Windows verification. Local installation/root bindings are explicitly unsigned metadata, and no resident is started.

**216 focused Python checks pass**, including 33 new receipt/controller/native checks, with scoped Ruff. Actual assembly verifies a 2,668-file controller using the existing isolated runtime; external-bootstrap policy status and wrong-pin/missing-configuration refusal are exercised on the development host. Windows reports a valid upstream Python signer/timestamp, with no certificate enrollment or INARA identity claim. Both production policies remain disabled and all 85 real reviews remain pending. [Evidence](qa/controller-verification.json). No real installation, certificate, profile, provider or phone configuration occurred.

Next: durable admission/renewal authorization and a process-lifetime guarded launcher, then monotonic update/rollback state and reviewed trust changes. Controller-specific notices/provenance, owned signed-bootstrap delivery and clean-machine acceptance remain open. Current one-hour authorization still expires; local receipt metadata is not an independently signed owner receipt, and legacy unsigned controls remain separate. WhatsApp text/outgoing actions stay off.

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

Updated 20 October 2026. Implement against the [architecture](INARA_REVAMP_PLAN.md), [project review](PROJECT_REVIEW.md) and [code cleanup and JARVIS interface plan](UI_AND_CODE_CLEANUP_PLAN.md).

The core/persistence milestones, polished JARVIS workspace, native resident, offline CAD worker, typed scene assembly, optional Blender bridge, Image atelier/job adapter, Vision studio v2, R2a core composition/session extraction and R2b1-R2b5 policy groups, R2c retirement, the R3 UI/contracts milestone, R4 capabilities/resource lifetime and R5 offline creative workflows plus R6 quick assistant/reviewed speech are implemented. R7 pairing, R8 read-only notification source/desktop workflow and offline release/support tools are now implemented; Android compilation/device acceptance is still gated by missing tooling. Real image generation remains unverified and unconfigured. Actual Blender execution remains unverified because it is not installed. Read [Implementation status](IMPLEMENTATION_STATUS.md), [CAD Studio](CAD_STUDIO.md), [Scene Studio](SCENE_STUDIO.md), [Image atelier](IMAGE_ATELIER.md), [Vision studio](VISION_STUDIO.md), [Native resident evidence](NATIVE_RESIDENT.md), [Persistence](PERSISTENCE.md), [Core composition](CORE_COMPOSITION.md), [Route policy migration](ROUTE_POLICY_MIGRATION.md) and [Settings/lifecycle policy](SETTINGS_LIFECYCLE_POLICY.md) and [Device/print workflow policy](DEVICE_PRINT_POLICY.md) and [Workspace policy](WORKSPACE_POLICY.md) and [Shared voice/connection policy](VOICE_CONNECTION_POLICY.md) before continuing. The user explicitly deferred the real-game benchmark; API configuration remains deferred.

Use GPT-6.1 Sol as the primary implementation model, with Medium reasoning and Standard speed. Use High reasoning for difficult migrations or debugging. Reserve GPT-6 Astra for unusually demanding architecture, security and final integration reviews. Use GPT-6 Luna for small, clearly specified edits once contracts and examples are established.

User-requested exception for the next UI redesign: use GPT-6 Astra with Ultra when available in the client's model picker, for design, implementation and visual review. Ultra and Extra High are distinct client options; do not invent an `ultra_high` API effort or claim a model switch occurred from a documentation edit. The owner selects the session model. This development choice does not change INARA's runtime provider or load a model onto the laptop. [Official model controls](https://learn.chatgpt.com/docs/models).

Official OpenAI documentation recommends GPT-6.1 Sol for complex coding and describes its capability as near Astra at a lower cost. That supports this choice; it is not a guarantee of equal results on every INARA task. Confirm quality through behavior, artifact validation and visual review. Availability depends on account, client and rollout. [Model guidance](https://learn.chatgpt.com/docs/models), [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol).

## Current priority: incoming call answering and message taking

Owner request, 20 October 2026: prioritize calls ahead of the remaining creative roadmap. INARA should **speak with incoming callers and take a message** on SIM and WhatsApp. The owner then explicitly required **carrier independence and the existing personal WhatsApp account**; do not substitute business-account migration or carrier forwarding as the selected solution. This is call-only scope: WhatsApp text drafts, sends, acknowledgements, outgoing calls and caller-triggered desktop actions remain excluded. The earlier UI-to-WhatsApp sequence below is retained as historical/backlog context; this section controls the next work.

**A supervised one-call desktop bridge prototype and offline Command OS Call bridge lab are implemented; real call answering remains unverified.** `backend/calls/`, `native/call-bridge/CallControl.cs` and the explicit lab CLI implement the candidate software workaround below. The supported core/UI exposes only owner/project-scoped synthetic checks; live answering remains CLI-only and Android integration is pending. Startup opens no audio or worker. [Current implementation and evidence](CALL_LAB.md). The older telephony provider/session prototypes remain wired only through archived `backend/core/server.py`. That router lacks signature checks and its session inherits owner instructions/old model literals; it was not revived.

Feasibility checked against current official Android, Meta and Twilio material:

| Requested outcome | Supported route / unresolved requirement |
| --- | --- |
| AI speaks on calls to the existing SIM number | Investigate a handset/headset bridge or an explicitly validated Windows Bluetooth call path. Microsoft Phone Link documents receiving calls over Bluetooth, but that does not prove a controllable AI audio path. Default-dialer answer control alone does not grant two-way call media. Carrier forwarding is an alternative only if the owner later relaxes carrier independence. |
| AI speaks on the existing personal WhatsApp account | No supported personal-account automation/audio API was established. Investigate a headset bridge or the official linked Windows client with explicitly isolated audio and bounded call control. Official human calling support is not proof of unattended AI automation. No business conversion, unofficial account protocol or migration is authorized. |
| Receive a message after the call | A restricted call service can produce a protected caller-provided message and sync it to the owner after a supported media route exists. It must label partial/failed calls and reported caller identity accurately. |

The owner's answers settle the product constraints; do not ask them to choose a carrier or business account again. The immediate gate is now a physical bridge feasibility proof. Neither a carrier-agnostic design nor an HFP specification justifies claiming every carrier/phone/app combination works. Do not implement a fake personal-WhatsApp connector, answer into silence, assume notification access supplies media, or change account/forwarding settings. Installed app metadata queries did not establish a ready WhatsApp/Phone Link bridge; no pairing or audio path was exercised.

Whole milestones to completion, without lettered refactor extensions:

| Order | Implementation | Completion evidence |
| --- | --- | --- |
| 1 | Prove a personal-account, carrier-independent bridge | On the actual Fold/Legion, prove incoming ring detection, call-specific answer, inbound audio capture and outbound speech injection for both SIM and personal WhatsApp, plus terminate/disarm. The compiled desktop-client prototype below is the first software candidate; HFP-HF hardware remains an alternative. Record locked/background/headset conflicts, proximity, sleep and app-version limits. This is an experiment, not an accepted live feature. If it fails, report the exact unresolved requirement rather than silently substituting Business/forwarding. |
| 2 | Isolated inbound bridge adapter | Bind control and media to the exact ringing call/paired device/process and session generation, with bounded queues, format contracts and cancellation. Fixture duplicate/stale events, unknown endpoints, disconnected audio, ambiguous answer, stop and restart; no outbound routes or owner tools. Any later hosted gateway alternative also requires authenticated webhooks and media identity. |
| 3 | Restricted talking/message-taking service | Explicit AI greeting; collect name, reason, caller-provided callback details and message; read back for confirmation. One call initially, bounded duration/context/spend, no owner conversation/private memory or tools. Test barge-in, silence, ambiguity, prompt injection, provider failure and deterministic fallback. |
| 4 | Owner call inbox and controls | Protected idempotent call receipts and separately granted device/project sync. Read/unread, source, partial/final status, expiry/forget, callback-request review and explicit bridge/availability status. Answering while the Legion sleeps needs a separately validated always-on bridge; remote receipt delivery also needs an available authenticated sync path. |
| 5 | Controlled live SIM acceptance | Test the proven carrier-independent bridge on controlled SIM calls, disable/rollback, voicemail, spoofed identity, network loss, sleep and competing audio. Validate actual language/latency/costs and carrier/device compatibility; no claim of universal coverage from one handset. Caller speech never gets desktop authority. |
| 6 | Personal WhatsApp acceptance | Validate controlled inbound calls through the proven personal-account bridge, with app updates, lock/background, failed answer, disconnect, endpoint changes and call-specific media isolation. Human desktop calling or working SIM Bluetooth does not establish this gate. If no viable personal route is proven, this goal remains blocked rather than marked complete. |
| 7 | Finish creative source backlog | Typed multi-object scene proposals, selected-object review/revisions and coherent image/vision/speech job/artifact flows. Preserve the completed Command OS shell and lazy workers. |
| 8 | Android and real capability acceptance | Reproducible APK/dependency verification and Fold testing; selected notification access stays separately gated. Configure and verify chosen AI/Blender/image/speech/camera/device adapters against actual hardware and current provider availability. |
| 9 | Private release completion | Self-contained signed desktop/Android packages, license review, clean-machine install/uninstall, explicit updates, interrupted-update rollback, protected recovery and sustained Legion/Fold checks. Real-game benchmarking remains deferred. |

[Detailed call architecture and acceptance](INARA_REVAMP_PLAN.md#call-only-completion-plan-20-october-2026). No call endpoint, account migration, provider subscription, forwarding change, live call or Android permission was activated during this feasibility pass.

### Desktop bridge lab implemented, 20 October 2026

The workaround candidates are **SIM -> official Phone Link/Bluetooth -> dedicated call audio** and **personal WhatsApp -> official linked Windows client -> dedicated call audio**. Both feed a new tool-free live voice session. Carrier APIs, forwarding and Business migration are absent. Official human calling is established by the vendor docs; automatic app control and AI duplex media still need actual client/device acceptance. Windows call UI automation is an experimental integration, not a supported WhatsApp automation API.

Implemented source:

- Native helper pins process ID, start time, full executable path/hash, window class, distinct observed control IDs and a hashed caller display. Only `PhoneExperienceHost.exe` or `WhatsApp.exe` can be enrolled. It reobserves before invoking one matching control; changed/ambiguous bindings reject. No app launch, global shortcut, coordinates, conversation scraping, cookie access or outgoing control exists. Invocation is not treated as connection success.
- A persistent root/caller view must survive ringing, active and explicitly ended states. The adapter also binds the active control fingerprint. A missing/hidden window is not proof of hangup; absent/replaced views remain uncertain and are left for owner checking. UI Automation provides no atomic provider call ID, so these conservative UI bindings are still not a guarantee against every app race. A client that recreates its identity view cannot pass this prototype's lifecycle proof.
- Two explicitly named WASAPI endpoints replace ambient/default/system-mix capture. Receive is 16 kHz mono PCM; transmit is 24 kHz mono PCM. Pre-answer frames are discarded; input/output buffering is bounded, interruption clears playback, and missing/duplicate/stalled routes fail. Separate app-specific virtual routes require owner setup and physical proof; names and configuration checkboxes do not independently prove isolation.
- An explicit one-call lease, at most 120 seconds waiting and 180 seconds in preparation/conversation plus bounded cleanup. Both audio and a fresh provider connection precede Answer; matching active state precedes greeting. Cancellation/expiry/failure stops tasks and attempts only the same observed caller's hangup. Unknown results become uncertain and never automatically retry.
- Tool-free Gemini Live adapter with an explicit `INARA_CALL_MODEL`, fresh context, AI-identification/message-taking instructions and no owner history, facts, memory or dispatcher. Barge-in and bounded transcripts are handled. Unexpected model tools or audio formats terminate the session. No provider/model availability or voice quality is established by fixture tests.
- DPAPI-protected separate lab records preserve incremental caller/assistant transcript fragments and uncertain outcomes across restart; no raw audio is stored. The ledger caps at 256 records; seven-day expiry is applied on access. Readback confirmation and identity are not inferred from transcript text. Reused UI fingerprints are conservatively rejected for the retention window, which can also reject a legitimate repeat caller if the app reuses its UI identity.

Live answering remains **an opt-in CLI experiment**, with no mobile receipt delivery, standing answer policy, automatic startup or integrated live-audio budget accounting. The CLI refuses live mode if an existing INARA owner budget cap is enabled; do not weaken a budget to run it. Duration/response limits are not an invoice ceiling. Owned Windows worker-process supervision now bounds a hung driver externally. Connections also offers an owner/project-scoped offline Call bridge lab with shared resource admission, Stop and synthetic transcript review. [Supervision, UI acceptance and remaining limits](CALL_LAB.md). Production live admission, enrollment/expiry, physical proof and phone integration are still required.

Reproducible offline checks (no downloads, app inspection, calls, microphone or paid API):

```powershell
.venv/Scripts/python.exe scripts/build-call-bridge.py
.venv/Scripts/python.exe scripts/verify-call-bridge.py
.venv/Scripts/python.exe scripts/call-bridge.py preflight
```

Acceptance: **30 Python fixture checks**, Ruff and .NET x64 native compilation/protocol rejection pass. [Sanitized report](qa/call-bridge-verification.json). Cases include lost answer ACKs, changed caller/view identity, missing terminal evidence, cancellation, timeout, playback backpressure/stale audio, transcript bounds, protected partial recovery and tool refusal. The computer-use Node runtime could not start, including after reset/retry; no live app UI was inspected. Preflight reports `audio_adapter_installed: false`, `voice_configured: false`, `live_routes_verified: false`. Import checks load no sounddevice, Google SDK, NumPy, server or application. No raw audio, app actions, live calls or model requests were used. Existing UI/full-core counts are previous evidence, not a new full regression run.

Configuration/device acceptance, in this order:

1. Pair Phone Link calls with the actual phone and link the owner's personal WhatsApp Windows client. Keep both accounts/numbers. Validate each client's ordinary incoming calling manually. The bridge depends on an awake reachable PC; SIM needs Bluetooth proximity.
2. Choose and install/verify **two isolated virtual audio paths** with appropriate signed drivers, then explicitly install the optional [call adapter requirements](../requirements-call-bridge.txt). That requirements file installs no driver or app and changes no Windows defaults. Set only the intended call client's speaker to receive-path playback and microphone to transmit-path capture; INARA uses the opposite ends. If Phone Link cannot honor isolated routing, this candidate fails rather than capturing game/system/room audio.
3. Run `scripts/call-bridge.py inventory` for pinned running-process metadata, then `inspect --pid <observed PID>` during controlled incoming/active calls to read automation IDs and Invoke availability without clicking. `schema` describes all strict `BridgeProfile` fields; use no guessed IDs. Manually establish answer/hangup controls, correct state/caller markers and duplex isolation with a controlled tester before setting `controls_confirmed` / `route_confirmed`. These flags record owner attestation, not automatic verification; the first automated controlled call still needs acceptance. App/process changes invalidate enrollment; clients without usable unique control IDs cannot use this adapter.
4. Explicitly configure credentials and a currently available voice model in `.env` with `GEMINI_API_KEY` and `INARA_CALL_MODEL`. The model is required, not silently borrowed from owner chat. Real latency, language, billing and provider data handling need acceptance.
5. With a reviewed local profile, `scripts/call-bridge.py observe --profile <local JSON>` reads state only. The explicit `run --profile <local JSON> --live --arm-seconds 30` command then waits for **one** controlled call and stops after it; Ctrl+C requests cleanup. It can invoke real client controls and send that call's audio to the configured provider. Inspect the client's actual termination if the receipt is uncertain. `records` shows metadata; `records --content` deliberately displays the protected transcript locally.

Next: perform that controlled proof, resolve concrete client limitations, then add validated enrollment and live usage admission before owner live controls and a real call inbox. Offline owner/session/resource wiring and process supervision are implemented in [Call bridge lab](CALL_LAB.md). Do not mark milestones 1, 5 or 6 complete from native compilation or fake ports.

## Cost comparison

Standard API text-token prices in USD per million tokens, for requests with at most 272,000 input tokens:

| Model | Uncached input | Output | Proposed role |
| --- | --- | --- | --- |
| GPT-6.1 Sol | $2.00 | $10.00 | Main implementation |
| GPT-6 Luna | $0.10 | $0.50 | Small bounded tasks |
| GPT-6 Astra | $10.00 | $50.00 | Demanding review and problem solving |

Sol's listed input and output rates are 80% lower than Astra's. Total task savings depend on tokens, retries and tool use. Long-context, cached-input and speed-tier prices differ. These API prices are separate from subscription usage. [Official API pricing](https://developers.openai.com/api/docs/pricing).

For credit-based ChatGPT Work/Codex usage, published Standard rates per million input/output tokens are 50/250 credits for Sol, 2.5/12.5 for Luna and 250/1,250 for Astra. Included-plan allowances are not a fixed conversion to API task counts. Prefer Standard speed for this cost-saving workflow; Fast and Ultrafast consume more usage. [Work and Codex pricing](https://learn.chatgpt.com/docs/pricing).

If GPT-6.1 Sol is unavailable, use the supported Sol option exposed in the account and validate the first bounded task. Do not use Luna as the sole owner of the entire cross-platform rewrite merely because its token rate is lowest.

## Preserve these requirements

- Keep the existing SIM number and personal WhatsApp account.
- WhatsApp notification summaries are allowed with enabled access; reply drafting and sending are deferred until specifically requested. No automatic replies or acknowledgements.
- Provide a small resident laptop assistant, an on-demand Studio and a native Fold8 companion.
- Heavy models, creative workers, tracking and camera acquisition are loaded only when needed. Gaming mode respects foreground resource use.
- Make JARVIS styling the primary visual direction while keeping controls readable, responsive and accessible.
- Preserve project data and existing useful integrations. Use one supported core, one tool contract and one authorization path.
- Ordinary text assistance works independently of live audio, microphone permission and an open window.
- Introduce changes in small, verifiable steps; update these plans if an implementation discovery changes a material assumption.

## Completed first milestone

The reproducible core environment, independent typed-conversation service, lazy provider, scoped request/result contracts and representative shared tool authorization are implemented. Project path containment and non-destructive startup are in place. The retained desktop event contract and new behavior passed 31 deterministic checks, and the production frontend build passed. See the status record for boundaries and unverified integrations.

## Completed second milestone

Versioned Windows-protected SQLite persistence, scoped sessions, request deduplication across restart, validated non-destructive migration, transactional reminder claiming, receipt/completion, UTC/IANA recurrence and UI reconnect recovery are implemented. Existing artifacts and source records remain preserved. See the status record and persistence contract for limitations.

## Resident/workspace foundation

Tray/hotkey reopen, graceful quit, scoped resident reminder delivery, explicit gaming policy, a polished responsive command deck, local reminder creation and lazy camera/CAD panels are implemented. Initial JavaScript is approximately 241 KB. The default native host releases Electron entirely after workspace close, preserving core/identity lifetime. Electron 44.7.0 and actual idle/lifecycle evidence are in [Native resident](NATIVE_RESIDENT.md). Game FPS/thermals, signed packaging, actual keyboard/balloon acceptance and resource use after optional legacy worker activation remain unverified.

## Ordered roadmap for subsequent implementations

Follow [R1-R8 and the follow-on tracks](INARA_REVAMP_PLAN.md#current-baseline-and-implementation-sequence-14-october-2026), reconciled against checkpoint `5f79902`. The [refactor map](UI_AND_CODE_CLEANUP_PLAN.md#remaining-refactor-work-tied-to-the-implementation-sequence) names source areas and acceptance evidence.

| Order | Product outcome | Refactor outcome |
| --- | --- | --- |
| R1 implemented; hardware acceptance pending | Vision studio v2: reliable local preview/tracking and polished controls | One capture/inference/overlay session; legacy tracking consolidation |
| R2a/R2b1-R2b5/R2c implemented | Reliable shared actions and errors | Composition root, thin transports, route/policy matrix, one schema/tool authority, mapped legacy retirement |
| R3 implemented | Consistent JARVIS panels, command palette and activity/artifact view | Incremental TypeScript/generated contracts, shared UI/RPC lifecycle, scoped styles/state |
| R4 implemented | Capability/setup diagnostics and resource-aware job controls | Worker launch profiles, reservations/queue, hardware probes, explicit background-job lifetime |
| R5 offline workflows implemented; optional adapters gated | Deeper 3D vibe coding and image workflows | Validated change sets, selected-revision edits, kernel/Blender/image adapters with real acceptance gates |
| R6 implemented; physical speech acceptance pending | Quick assistant and push-to-talk voice | One audio/session stack feeding existing conversation and tool services; optional wake profile later |
| R7 source/protocol implemented; APK/device acceptance pending | Native foldable Android companion and secure pairing | Device/project context, scoped grants, revocation and idempotent sync |
| R8 | Read-only selected-notification inbox and summaries | Native ingestion, dedupe, retention and owner-controlled summarization; no WhatsApp reply tools |

R1 software, R2a and R2b1-R2b5 policy groups and R2c retirement are implemented. The two latest authorized steps are complete: live voice uses shared schemas/dispatch, and owner-only connection hydration plus owned face-process lifetime replace facade callbacks. Optional provider/hardware behavior and legacy generated-code/browser hard isolation remain separate acceptance work.

## Current priorities: unified UI through WhatsApp assistance

Planning update, 19 October 2026, following the owner's request for a stronger UI and a compact roadmap through WhatsApp AI. This order supersedes older "next" statements below; the completed R1-R8 milestones remain completed. These are whole product milestones, not another lettered refactor sequence. This update authorizes no real notification access, provider/toolchain installation, account migration, reply drafting, sending or call answering.

| Order | Whole milestone | Completion boundary |
| --- | --- | --- |
| 1 implemented | Unified JARVIS workspace | Assistant, Studio, Inbox, Tasks and Connections now share a docked tool canvas, collapsible context inspector and compact activity tray. Short dialogs preserve the current tool; mobile navigation, multiline chat, shared lazy panel content and visual refinements are implemented. See [implementation and acceptance](UI_AND_CODE_CLEANUP_PLAN.md#command-os-ui-refinement-20-october-2026). |
| 2 | Multi-object 3D vibe coding | Extend the existing bounded scene/proposal contracts with selected-object edits, preview/review, stale-context rejection, protected revisions and per-call usage admission. Offline fixtures first; no generated executable code or provider setup. |
| 3 | Coherent creative workflows | Bring image, camera/tracking and reviewed speech into the shared artifact/job interface. Preserve lazy workers and cancellation. Actual model/provider, Blender, camera and microphone acceptance is a separate explicitly configured gate; fixtures do not establish generation quality or device support. |
| 4 | Android build and Fold acceptance | Establish a reproducible Android build once tooling setup is authorized, then verify pairing, Keystore, fold/cover layouts, lock/revoke, process death, Doze and offline queue behavior on the owner's phone. No APK/device acceptance is currently established. |
| 5 | Personal-number WhatsApp inbox with AI summaries | Use explicitly selected Android notifications, the existing encrypted scoped notification pipeline and a new separately consented model-processing boundary. Provide on-demand summaries with source references, bounded context, retention/forget and usage admission. Incoming text has no tools or authority. No replies or complete-history claim. |
| 6 | Release-ready private pilot | Complete packaging, licenses/signing, clean-machine install/uninstall, update rollback and backup/recovery; run sustained Legion and physical Fold checks. UI close must recover resident resources. The real-game benchmark remains deferred. This gate precedes any live message-action pilot. |
| 7 | Optional prompt-only draft assistance | Only after a specific request to implement it: the owner selects a conversation/context and asks for a draft. Review inside INARA, initially using manual handoff to WhatsApp. A draft request never authorizes sending; notification arrival never starts a draft. |
| 8 | Optional individually authorized send | Only after a separate implementation request and device/platform acceptance: bind each approval to the exact recipient/thread/body and a short expiry, revalidate the source action, require current owner authentication and persist a non-replayable receipt. An uncertain outcome requires owner checking, never automatic retry. Fall back to opening WhatsApp/manual send if no supported action is available. |

Recommended personal-account architecture: selected phone notifications -> encrypted phone queue -> paired TLS/device-project grant -> protected desktop inbox -> explicitly consented, bounded summary request -> owner. Message text is untrusted input and cannot call tools. Draft/send permissions remain absent from the current implementation.

Android notification access provides only the content actually exposed by the source application, not WhatsApp history synchronization. Android documents notification listeners and notification reply actions, but does not establish that the owner's WhatsApp build exposes a usable reply action. Any future reply experiment must validate that on the actual phone and check applicable platform terms. No WhatsApp Web scraping, session-cookie bridge or unattended UI clicking is the integration foundation. [Notification listener](https://developer.android.com/reference/android/service/notification/NotificationListenerService), [RemoteInput](https://developer.android.com/reference/android/app/RemoteInput).

WhatsApp Business Platform is an alternative business-account integration, not an assumed API for the existing personal Messenger account. Before adopting it, verify current onboarding/coexistence eligibility, number/account consequences and AI/provider policies for the actual jurisdiction. Current gated Meta developer/terms pages did not establish this owner's eligibility; do not promise a migration or general-purpose bot. [Official Business Platform](https://business.whatsapp.com/products/business-platform).

Away from the laptop, keep notifications queued locally and show core availability honestly. On-demand AI requires the paired core to be reachable; a sleeping/offline laptop is not an available AI server. An optional private remote transport or separately configured hosted service needs its own design and acceptance; do not expose the core publicly or assume a cloud relay. SIM/WhatsApp call answering remains a separate feasibility/policy/device investigation and is not part of messaging acceptance.

## Connection adapters and readiness completed

Kasa SDK discovery/control, printer data, explicit mDNS observation and OctoPrint/Moonraker HTTP clients are separated from the retained compatibility/profile/slicer facades. Exact host:port routing, saved credentials, per-stage approvals and non-replayable print receipts are preserved. Silent upload fallback/start and discovery camera/protocol probing are removed. The responsive Connections readiness view inspects local metadata/cache without activating adapters or revealing endpoints/keys. [Implementation and limits](CONNECTION_ADAPTERS.md).

Acceptance: **1,053 full-regression Python passes / one Blender skip; 94 Node passes**, final focused protocol/device/print checks, type/contracts/lint/build and hidden native UI acceptance at desktop/390px. Native readiness activated zero adapters, used synthetic metadata only and recovered to about 66.5 MB resident memory. Actual vendor SDK/device/printer behavior and network acceptance remain unverified; no dependencies, providers or real hardware were configured.

The UI refinement above is implemented. Next creative source milestone: extend optional AI blueprint proposals to typed multi-object scenes, with bounded scene contracts, previews/review, stale-context rejection, protected revisions and shared per-call usage admission. Use injected proposals and existing offline geometry workers; no raw generated Python/shell, model downloads, provider configuration, actual Blender/image/camera or physical actions. Android, interactive browser actions, real provider/hardware acceptance and signed distribution/update recovery stay gated.

## Reviewed desktop tasks completed

Reviewed tasks adds immutable one-to-eight-step project plans, a polished responsive editor/review workspace, fresh approval for every typed file/app step, protected durable receipts and cancellation/recovery that never replays effects. Safety stops work across project changes and while locked without returning private task data. Shared dispatcher hooks preserve other callers' existing behavior. [Behavior, evidence and limits](REVIEWED_TASKS.md).

Acceptance: **1,004 full-regression Python passes / one Blender skip**, **51 final queue checks**, **89 Node passes**, types/contracts/lint/build and real hidden renderer fixture acceptance at desktop/390px. Short resident recovery was about 68 MB. QA used isolated project files and a fake cancellable app adapter; no real application, network, provider or hardware actions were activated.

Device/printer protocol-adapter separation and Connections readiness are now implemented above using fixtures. Extract Kasa discovery/control and printer network clients while preserving exact endpoints, shared approvals, lazy loading, owned observation and durable non-replayable print attempts. Do not perform real network discovery/control or tool/provider installation/configuration. Interactive browser actions, physical/provider acceptance, Android build/device acceptance and signed distribution/update recovery remain open gates.

## Web inspector completed

The retained autonomous browser loop and automatic safety acknowledgement are retired. The Web inspector now uses explicit typed public HTTPS requests, shared approvals, owned bounded worker lifetime, inert hostile page text and cancellation. Printer observation is extracted and releases on last-owner-renderer disconnect. This is a read-only research milestone, not interactive browser/desktop automation or physical device acceptance. [Behavior, evidence and limits](BROWSER_INSPECTOR.md).

Validation: **954 Python passed / one Blender skip; 83 Node passed**, type/drift/lint/build and real hidden native fixture acceptance at desktop/390px. Short native resident recovered to about 67 MB. No public website, provider or real device actions were used.

The reviewed desktop task queue is now implemented above with bounded typed steps, owner/project capture, per-step approvals, durable non-replayable receipts and progress/cancellation/recovery UI. Preserve the browser read-only boundary, shared usage admission and legacy cloud guard; no automatic restart of effectful steps. Continue device-adapter decomposition with fixtures. Android, provider/hardware acceptance and signed distribution gates remain open.

## Usage and quality completed; next source implementation

The second post-revamp source milestone adds Usage & quality, owner-wide integer daily/monthly authorization allowances, atomic per-invocation reservation, provider-reported token counters, request/job references, local creative-job duration receipts and 12 owned offline product-contract evaluations. Caps default off (monitor only); no provider/key/model configuration or paid requests were performed. [Behavior, coverage and limits](USAGE_AND_QUALITY.md).

Validation: **911 Python tests passed with one Blender skip; 78 Node tests passed**. Types, generated-contract drift, Ruff, production build and all 12 offline fixture evaluations passed. Native fixture acceptance and limitations are recorded in the usage/quality evidence. No paid provider or hosted CI run is claimed.

These limits govern owner-assigned INARA allowances; actual provider invoice cost is unknown. Timeouts/cancellations/missing metadata retain their allowance. No automatic refunds or retries. Metered paths include desktop/phone conversation, CAD proposals and transcription. Legacy unmetered cloud tools/aliases are blocked when caps are enabled; local jobs, memory and reminders remain usable. Fixture evaluations are explicitly not real-model quality acceptance.

Historical next scope (read-only browser and printer observation are now implemented above): owned browser/desktop automation and device-adapter cleanup. Replace the retained autonomous browser seam with bounded typed operations, explicit owner/project/task lifetime, hostile-content handling and cancellation. Integrate every provider step with usage admission before enabling it under caps; preserve the legacy guard until parity is tested. Continue device/printer adapter separation without real hardware actions or automatic dependency downloads. Android build/device, signing/distribution/update recovery and provider/hardware acceptance remain separate open release gates. No additional lettered budget substep is scheduled for this source/fixture milestone.

## Project memory completed; next source implementation

The first post-revamp step is implemented: owner-reviewed project facts/preferences/decisions, editable sources/tags, version metadata, local lexical search, bounded protected retention, archive/forget, encrypted same-profile export, reviewed non-overwriting recovery and explicitly opted-in assistant context with source labels. Raw memory context is not saved as an extra conversation message; historical answers/backups remain separate from Forget. [Implementation and limits](PROJECT_MEMORY.md).

The responsive lazy panel is available from Command quick launch and the command palette. Local storage/search need no provider/model setup. Backups require the original Windows profile and project; portable cross-account recovery and embedding semantics are not claimed. No model write tools or phone memory grants were added.

Verification: **865 Python regression checks passed with one Blender skip; 72 Node checks passed**. Final focused memory/conversation/speech checks, types, generated-contract drift, Ruff, production build and actual hidden desktop memory/recovery/provider-fixture acceptance passed. No hosted CI or real-provider quality claim is made.

Usage budgets and offline quality fixtures are now implemented in the checkpoint above. Read-only browser and printer observation modernization are now implemented above; real provider price/invoice and model-quality acceptance stay deferred. Android build/device acceptance and signed distribution remain separate open release gates.

## R8 completed; next work after the source revamp

R8 selected read-only notifications are implemented across the server/desktop and native Android source. Separate device/project notification policies, metadata-only defaults, app/conversation rules, redaction, bounded encrypted ledgers, manual duplicate-safe sync, expiry/revocation and a responsive JARVIS inbox are complete within fixture acceptance. Android collection remains build-gated off. See [R8 behavior and limits](R8_NOTIFICATIONS.md).

Final local acceptance: **810 Python checks passed, one Blender skip; 66 Node checks passed**. Types, contract drift, Ruff, production build, closed Android source guards, actual native desktop/loopback notification fixtures and source-pilot integrity verification passed. No Android compilation/device/hosted-CI execution is claimed.

Offline release/support tooling now provides whitelist diagnostics, dependency/license metadata inventory, source-pilot staging/integrity verification and machine-readable readiness. A staged pilot is unsigned and needs external runtimes/dependency setup; it is not a self-contained installer. See [release readiness and backlog](RELEASE_READINESS.md) and [gate inventory](RELEASE_GATES.json).

1. R1-R8 source implementation milestones are complete within their documented boundaries. Do not schedule an R8a or another cosmetic refactor checkpoint. Source work can continue on the explicit post-revamp backlog while setup stays deferred.
2. Next release prerequisite: Android build/dependency verification, then controlled Fold8 acceptance. JDK/Gradle/SDK/ADB are absent. No APK/native tests or physical notification behavior are claimed. Do not download dependencies automatically or flip `NOTIFICATION_ACCEPTANCE_ENABLED` as routine setup.
3. Project memory is now implemented in the post-revamp milestone above. Usage allowance controls/offline evaluations are implemented. Next source work is browser/device adapter modernization. Optional embedding retrieval and portable recovery-key design remain future memory enhancements.
4. Desktop release still needs clean-machine self-contained core/optional-worker packaging, installer/uninstaller, signing/license clearance, explicit startup/update choices, interrupted-update recovery/rollback and long-run Legion acceptance. Source staging/checksums do not satisfy those gates.
5. Real provider/model/Blender/image/kernel/microphone/camera/printer setup and exact hardware acceptance remain deferred. The user explicitly deferred the real-game benchmark.
6. No real notification access, phone calls, forwarding, SIM/account migration or live messages were used. WhatsApp reply drafting/sending, acknowledgements and notification action execution remain excluded until specifically requested. Retain the existing SIM/personal WhatsApp number.

## R7 source/protocol milestone and Android acceptance gap

The responsive desktop companion panel, explicit private-address TLS listener, two-minute single-use invitations, owner fingerprint approval, DPAPI-protected device/key/replay state, 30-day device/project grants, revocation and isolated read-only mobile API are implemented. Optional phone chat uses the shared conversation ledger with an empty tool dispatcher and its own explicit grant. Request receipts do not replay uncertain sends or import desktop history.

Native Kotlin/Compose source provides single/two-pane layouts, file/paste invitation import, certificate validation, Android Keystore signing/encrypted state, bounded job previews and explicit chat/receipt recovery. Only INTERNET uses-permission is declared; R8 adds a system-permission-protected listener whose collection gate remains off. No Android build was possible with the available tools; no APK, native rendering, key hardware placement, process death, fold/unfold or battery acceptance is claimed. Optional QR rendering was not installed; invitation-file transfer is verified. See [R7 evidence and remaining acceptance](R7_ANDROID_FOUNDATION.md).

773 Python tests and 63 Node checks pass, with one Blender skip. Types, generated-contract drift, Ruff, production web build, source/manifest guards and native loopback TLS/desktop pairing checks pass. The final request-body and embedded-listener refinements also pass the focused 40 Python mobile checks. Android compilation/JVM/Keystore/device tests remain unrun because tooling is unavailable; no hosted CI run is claimed.

R8 source work is now implemented. Completing the deferred Android build/device gate remains required before enabling phone collection; no additional R7/R8 lettered implementation substep is scheduled.

## Completed R6 quick assistant and voice consolidation

A lazy compact JARVIS surface opens with Ctrl+Shift+Space, the command palette or Quick assistant. Typed chat shares the existing conversation. Voice uses explicit prepare/permission, hold, release, streaming transcription after release, review/edit and Send. Only Send reaches the shared conversation/tool dispatcher. Optional local-only speech playback has interruption. One bounded PCM/device/session owner replaces the two old always-on loops; both old constructors now return a migration message. Closing, disconnecting, source loss, project/lock changes, suspend and resource restrictions release or invalidate work without replay.

733 Python tests and 60 Node checks pass, with one Blender skip. TypeScript, generated-contract drift, Ruff and the production build pass. Native synthetic-speech and Electron fallback lifecycle acceptance pass; post-close native resident recovery is about 66 MB. Actual microphone/provider/local voice, Bluetooth/sleep and creative/device acceptance remain deferred.

Fixture-based acceptance is recorded in [R6 implementation and limits](R6_QUICK_ASSISTANT.md). Real microphones, Bluetooth/sleep behavior, installed local voice quality and provider transcription accuracy/latency remain unverified. No API/model/device setup was performed. R7 secure pairing is next; no further R6 substep is scheduled for the completed fixture-tested implementation.

## Completed R5 offline Creative Studio milestone

Shared draft undo/redo, explicit branch ancestry, recipe fingerprints, selected-object editing, separate draft blockouts/translation gizmo, saved camera views, revision comparisons, image gallery/recipe reuse and reviewed bounded change proposals are implemented. Parent/stale/owner checks preserve existing revisions, and worker generation still requires the existing admission/approval. Typed Blender presentation presets extend the fixed bridge, while actual Blender/provider/image/kernel acceptance remains deferred; holes/fillets/booleans/STEP are explicitly unavailable.

707 Python and 52 Node checks pass, with one Blender skip; types/drift/lint/build and native CAD/image acceptance pass. Nine workers exited and short post-worker resident recovery remains about 67 MB. See [behavior, evidence and material limits](R5_CREATIVE_STUDIO.md). R6 is next; no additional R5 substep is scheduled for the completed offline workflow.

## Completed R4 capability/resource milestone

The responsive Capability center, on-demand Windows CPU/RAM diagnostics, explicit unknown GPU information, centralized capability/model/worker profiles, shared bounded FIFO creative queue, capacity checks and explicit job release are implemented. Panel closure cancels by default; owner-scoped per-job background continuation lasts only within the current connected workspace/core session. Gaming/resident restrictions, interruption and cleanup-fault handling preserve ownership. Image generation now uses an explicit CPU profile rather than automatic CUDA selection.

690 Python and 46 Node checks pass, with one Blender skip; types/drift/lint/build and native image/CAD/lifecycle acceptance pass. Short native idle remains about 67 MB with zero Electron processes after closure. See [implementation, acceptance evidence and limitations](R4_RESOURCE_LIFETIME.md). R5 offline workflows are now implemented; no additional R4 substep is pending.

## Completed R3 UI and contract milestone

The shared JARVIS design/panel/approval system, embedded legacy interiors, keyboard command palette and project-scoped CAD/image Activity/artifact view are implemented. CAD/image/planner/preview calls share scoped lifetime and runtime guards; schemas/types and UI contract version 1 are generated. Feature-specific event registrars replace the monolithic store bridge, and typed conversation updates retain their captured project/session scope. The pinned development compiler and semantic checks now pass, resolving the earlier installation/check gap.

669 Python and 41 Node checks pass, with one Blender skip, alongside type checks, drift/lint/build and native/renderer acceptance. [Evidence, screenshots and remaining physical/provider limits](R3_UI_RPC.md). R4 is now implemented; no additional R3 substep is pending.

## Completed obsolete-path retirement (R2c)

Removed static voice declarations, ad-hoc AudioLoop CAD/browser/filesystem helpers, the standalone approval gate, fallback confirmation mapping, dead facade state and unused lifecycle injection hooks. Live configuration now builds lazily from shared schemas. `ConfirmationTransport` owns the strict renderer route and resolves only dispatcher approvals. The supported inventory remains 52 socket routes, 53 shared tools (40 text-visible) and 37 voice functions.

668 Python checks and 26 frontend checks pass, with one Blender-dependent skip; lint/build pass. [Retired paths and desktop evidence](RETIRED_PATHS.md) records the final integration results and limits. R3 UI/RPC consolidation is next.

## Completed shared voice and connection checkpoint (R2b5)

All 37 active live voice names now use generated dispatcher schemas and shared permission/approval execution. Twenty additional shared contracts/aliases cover the retained project, filesystem, routine, desktop, vision/device and printer-status actions. The inventory is 52 socket routes, 53 dispatcher tools (40 provider-visible for text) and 37 active voice functions; the original 26 static declarations remain only for cleanup reference.

`ConnectionTransport` owns private hydration and one optional face generation. Locked/control/resident/foreign channels cannot obtain private startup state. A fixed owned face worker holds the camera/model work, stops on disconnect/resource/settings/quit, drops stale callbacks and cleans transient reports. Enabling missing face setup is rejected before persistence; no model downloads or real-camera activation were performed.

666 Python checks and 26 frontend checks pass, with one Blender-dependent skip. Lint/build and actual native/fallback/CAD desktop integration pass. Short native idle is about 67 MB with zero Electron processes after workspace close. See [verification, evidence and remaining limits](VOICE_CONNECTION_POLICY.md). Actual live voice/provider, face matching and physical media acceptance remain unverified. The unused static helpers are the next cleanup target, rather than another live policy path.

## Completed workspace compatibility checkpoint (R2b4)

Ten memory/media/legacy CAD/browser wire routes now use strict owner-scoped service/transport envelopes. Memory exports stay inside the captured project and preserve existing files. Voice callbacks, bounded confirmations and detached work belong to one session generation; unstamped bus events stay internal. Direct and typed requests cancel on origin disconnect, with provider/browser cleanup. The inventory remains 52 socket routes and now contains 33 dispatcher tools (24 provider-visible), plus 26 separate legacy voice declarations.

462 Python checks pass with one Blender-dependent skip; all 26 frontend checks, lint/build and actual native/fallback/CAD desktop integration pass. Short native idle remains about 67 MB with zero Electron processes after close. See [verification and material limits](WORKSPACE_POLICY.md). Live voice/media, provider-generated CAD and autonomous browser effects were not exercised. This checkpoint does not complete voice/shared-dispatch parity or legacy worker isolation.

## Completed combined compatibility checkpoint (R2b3)

Owner-scoped Kasa/printer compatibility tools preserve saved settings and endpoint selection. The print pipeline snapshots contained project inputs, independently authorizes slice/upload/start, owns slicer process lifetime and records non-replayable attempts durably. Reminder receipts/roles and CAD planner permissions now use the owner/shared policy boundaries. The route inventory remains 52 socket routes and now contains 25 dispatcher tools, 21 provider-visible, plus 26 separate legacy voice declarations.

377 Python and 26 frontend checks pass, with one Blender-dependent skip; lint/build and actual native/fallback/CAD desktop integration pass. A reproduced Windows progress-file sharing failure no longer aborts CAD exports. Two earlier native timing failures remain a documented limitation. See [evidence, limitations and next batch](DEVICE_PRINT_POLICY.md). Real devices, printers and slicer output remain unverified; this checkpoint does not complete all R2b work.

## Completed settings/lifecycle checkpoint (R2b2)

Seven settings/permission/resource/native/shutdown routes now use injected strict-schema transports. Settings authority is an independent authenticated owner/renderer gate; a request cannot disable its own authorization. Known permission values, atomic persistence, scoped refreshes, pinned owner reconnect, strict native actions, native/fallback gaming authority and cleanup-before-exit are verified. The old settings panel waits for server acceptance before changing face/camera state; first-launch renderer connection waits for native owner registration.

288 Python and 26 frontend checks pass, plus build/lint, actual native admin socket/reopen/reminder/gaming checks and fallback lifecycle verification. Short native idle is about 67 MB with zero Electron processes after close. [Evidence and remaining limits](SETTINGS_LIFECYCLE_POLICY.md). R2b3 compatibility adapters are next; this does not complete all R2b policy migration.

## Completed route-policy checkpoint (R2b1)

The tested inventory covers 52 socket routes, `/status`, 15 shared tools and 26 separate legacy voice declarations. Seven desktop/device actions now use strict schemas and the shared dispatcher for both direct and typed model calls, with renderer checks, approval/denial, scoped responses, stamped agent event ownership, cooperative execution deadlines and origin-disconnect cancellation. Confirmation payloads now require a real boolean and an authenticated renderer; voice binding remains a legacy seam.

222 Python and 26 frontend checks pass, including 61 new policy checks. Actual native failure/reopen/reminder/gaming/shutdown verification passes; short idle is approximately 66 MB with zero Electron processes after close. New action tests use injected adapters, not real device/app actions. See [Route policy migration and limits](ROUTE_POLICY_MIGRATION.md). R2b2 is next.

## Completed core composition milestone (R2a)

`application.py` constructs the lean runtime and owns ASGI/lifespan, creative shutdown, reminder polling and event subscriptions. Injected desktop sessions own token/identity/role/native-owner checks and immutable request project snapshots. Conversation/reminder transports and event delivery are separated; the supported server retains mapped compatibility aliases and legacy handlers. Multi-channel disconnect preserves other channels' approvals. No extracted module imports the facade.

161 Python and 26 frontend checks pass, plus actual native failure/reopen/reminder/gaming verification, CAD/scene worker rendering and labelled image-fixture integration. Short native idle is approximately 66 MB with zero Electron processes after close. Remaining direct-route bypasses, legacy broadcasts and audio/face callback seams are explicitly mapped for R2b/R2c/R6. See [Core composition evidence and limits](CORE_COMPOSITION.md).

## Completed Vision studio milestone (R1)

The local camera workspace now has source/mirror/overlay/rate controls, two-hand skeletons, explicit capture/tracking state and side-classification metrics. Inference runs in an opt-in bounded Web Worker, with stream/model cleanup for source changes, device loss, close/hidden/suspend/minimize and gaming. Unused duplicate capture/tracking hooks are retired; no recording, uploads or actions were added.

146 Python and 26 frontend checks pass. Actual hidden renderer verification initializes the real bundled model and infers blank synthetic frames; labelled fixture landmarks verify overlay controls. Seven workers terminate and resident recovery is around 64 MB. Actual camera/hand accuracy and physical sleep/device acceptance remain pending. See [Vision studio](VISION_STUDIO.md).

## Completed Image atelier milestone

A responsive prompt/frame/seed/quality workspace, installation-aware local SD/SDXL adapter, owned image worker, PNG/recipe preview/download and protected revisions are implemented. CAD and image jobs now share one durable service/transport and one creative execution slot. No weights/dependencies were installed or configured. Real generation is unverified; the normal UI explains setup and disables generation. 144 Python checks and nine frontend checks pass. Actual native UI checks use labelled test-only fixtures, verify cancellation/revisions and approximately 65 MB resident recovery; production rejects fixture provenance. [Evidence and limits](IMAGE_ATELIER.md).

## Completed scene assembly milestone

Up to eight typed parametric objects, scale/XYZ rotation/translation, four materials, add/duplicate/remove, material-aware GLB preview, STL/GLB/recipe revisions and an installation-aware fixed Blender bridge are implemented. Existing job permissions, cancellation and scoped storage are retained; old revisions remain readable. The optional provider planner stays single-solid only. 116 Python checks and nine frontend checks pass; the real Blender test is skipped. Actual hidden renderer verification covers three-part editing/export/restore and approximately 65 MB resident recovery. See [Scene Studio evidence and limitations](SCENE_STUDIO.md).

## Completed CAD worker milestone

Offline box/bracket/enclosure generation, editable dimensions, real orbit/wireframe preview, STL/GLB/recipe download, protected scoped job history, shared build authorization, cancellation/timeout and owned worker cleanup are implemented. Optional AI proposals return validated recipe data for review; configuration stays deferred. The older voice adapter is preserved. See [CAD Studio evidence and limits](CAD_STUDIO.md). Typed scene assembly and an optional Blender bridge are now implemented; actual Blender execution is installation-dependent and still unverified.

## Keep model use efficient

Give each task a bounded objective, relevant files, accepted contracts and concrete completion criteria. Read the review once and avoid repeating the entire repository audit for every feature. Keep task status and important decisions in compact project notes so the next turn can resume without reconstructing the conversation.

Use Medium as the default, increase effort when complexity or a demonstrated failure warrants it, and evaluate quality on completed tasks. A failed check needs diagnosis, not repeated blind regeneration. Reserve expensive reviews for integration boundaries and release gates. Reuse valid outputs, incremental builds and relevant checks; avoid unnecessary paid end-to-end runs.

## Latest independent source milestone: scene proposals

Reviewed multi-object scene blueprints are implemented with a bounded provider schema, shared usage/permission admission, separate on-demand blockout review, draft Apply and independently approved offline build. No provider configuration or live calls were used. **215 focused Python passes / one Blender skip; 102 frontend passes**, types/contracts/lint/build and actual native acceptance pass; six owned workers exited. [Implementation, screenshots, evidence and remaining sequence](SCENE_PROPOSALS.md).

## Prompt for the next implementation session

Latest source milestone: [Node-free desktop workspace pilot](DESKTOP_WORKSPACE_PACKAGE.md), 21 October 2026. **37 packaging/native/release tests** and actual staged core/Electron UI acceptance pass with external npm resolution disabled. The 329-file unsigned pilot needs external Python; no portable core, installer or profile migration is claimed.

Latest source milestone, 21 October 2026: [Android build acceptance tooling](ANDROID_BUILD_ACCEPTANCE.md) is implemented with **24 Android-build and 11 release checks**, actual PowerShell preflight/missing-tool refusal, source guards and lint. It does not complete the blocked Android build gate. There is still no JDK/Gradle/SDK or actual APK; do not invent dependency locks/checksums or enable notification access.

Latest completed source milestone: [reviewed creative handoffs](CREATIVE_HANDOFFS.md), with **235 focused Python passes, 106 frontend passes**, type/contract/lint/build and actual native acceptance. Both destination studios preserve drafts until Apply, source fingerprints/export digests are revalidated and completed revisions retain provenance. Handoffs start no provider or worker.

> Read docs/DEFERRED_WORK.md first, then continue from docs/SIGNING_DELIVERY_PREPARATION.md. Step 4 preparation is implemented: public custody drafts/readiness, immutable controller-specific review revisions and detached delivery request/verification with signatures before payload validation. 181 focused checks pass, including 34 new checks; actual disabled-policy/draft/pending-review readiness and request refusal pass. These three tools are external trusted-checkout tools, not new bundled controller commands. The existing 2681-file lifecycle controller/pin is unchanged; renewed provenance/controller ledger has 51 pending subjects (previous 48 plus three tools), zero review events, and all 85 desktop subjects remain separately pending. Both production policies remain disabled; no real identity, key, certificate, signed release, provider or device is configured. Next implement source-neutral receiving/delivery packaging and clean-machine acceptance preparation; current verification requires a separately trusted matching source snapshot. Real custody/enrollment, evidence approvals, owned signing/timestamping, verifier/bootstrap delivery and real signed-package/native-window/clean-machine acceptance remain pending until configuration is explicitly resumed. Do not infer authority from draft/review labels or self-reported hashes, load private keys, auto-adopt pins, sign a real release, enable fixture bypasses, run received payload code before trust or silently download tools/models. Preserve all managed lifecycle invariants and exact original-account/typed recovery limits. Keep every deferral visible, existing phone accounts/numbers, WhatsApp text/outgoing actions off, Android/SIM/personal WhatsApp duplex proof separate, and provider/toolchain/device configuration and real-game benchmarking deferred.

The implementation model is a development choice. INARA's own local/cloud runtime models remain separately configured through the capability router, with dedicated speech, image and vision adapters where needed.
