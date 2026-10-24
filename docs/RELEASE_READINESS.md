# Release readiness and work after the revamp

Track the owner's [deferred work and standing constraints](DEFERRED_WORK.md) alongside [release gates](RELEASE_GATES.json). Keep deferred configuration, excluded actions and pending real acceptance visible after source milestones complete.

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

[Managed updates](MANAGED_UPDATES.md) adds current-account protected metadata checkpoints, independently pinned state, dual-policy key rotation and reviewed local signed-package update/rollback transactions. Original profiles and versions remain retained, sequence floors stay high after rollback, and interrupted writes require reviewed recovery or safe pre-commit cancellation. Format-3 adoption is explicit; legacy unsigned controls refuse rather than downgrade it.

**281 focused tests pass**, including 31 managed-state tests, with scoped Ruff, actual DPAPI protection/refusal and updated 2,672-file controller/bootstrap verification. [Execution evidence](qa/managed-update-verification.json). Production policies remain disabled, all 85 real subjects remain pending and no real production root, identity or application was signed/adopted/launched.

Next: controller-specific distribution provenance/notices and native format-3 status/update/recovery/backup/removal UX, followed by owned signed-bootstrap delivery and clean-machine resident/Electron/job acceptance. Protected checkpoint history still needs the trusted external latest pin; it is not a hardware counter or cross-account recovery scheme. No profile migration is automatic. Android/SIM/personal WhatsApp physical acceptance and provider/toolchain/model configuration remain separate gates; WhatsApp text/outgoing actions stay off.

## Renewable authorization and guarded launch, 22 October 2026

[Admission and launch](ADMISSION_LAUNCH.md) adds independently signed renewable root/version authorization, exact review/apply and retained grant/head history. The trusted controller verifies current trust/bytes/profile/native signatures before starting the selected isolated resident under manager/file leases and a kill-on-close Job Object. Expiry and controller death terminate its contained tree. Fresh signatures explicitly reauthorize an expired source package; unsigned requests and fixture trust never authorize launch.

**250 focused tests pass**, including 33 new checks, with scoped Ruff and actual isolated-Python process/lease/expiry/tree acceptance. The updated portable controller has 2,670 verified files; [execution evidence](qa/admission-launch-verification.json) records bootstrap status and refusal checks. Production policies remain disabled, all 85 actual reviews remain pending and no real INARA resident or production installation/grant was exercised.

Next: independently retained update/trust state, reviewed policy/key rotation and transactional signed update/rollback. Current rollback protection relies on the trusted external latest-grant pin, not a hardware counter. Controller-specific notices/provenance, owned signed bootstrap delivery, Electron/job compatibility and native resident/UI clean-machine acceptance remain pending. Legacy unsigned controls remain separate. Android/SIM/personal WhatsApp physical acceptance and providers remain deferred; WhatsApp text/outgoing actions stay off.

## Windows verification and portable controller, 22 October 2026

[Windows controller preparation](WINDOWS_CONTROLLER.md) adds cache-only native Windows verification with external signer/timestamp pins, a separately inventoried isolated controller and a source-trusted bootstrap that checks all bytes before starting its Python. Authenticated install/recovery retains source authorization evidence before registration. The read-only launch contract verifies current signatures/installed bytes/profile ownership, with native checks required by the controller. It grants no execution permit; local root bindings remain unsigned.

**216 focused Python checks pass**, including 33 new checks, with scoped Ruff, actual 2,668-file controller assembly, bootstrap status/refusal and native certificate probing. [Execution evidence](qa/controller-verification.json). Upstream Python's observed signer/timestamp is not enrolled as INARA identity. Both production policies are disabled, all 85 actual reviews are pending, and no production package was installed or signed.

Next: durable admission/renewal authorization and process-lifetime guarded launch, monotonic update/rollback state and reviewed trust transitions. The controller needs its own distribution notice/provenance review; owned bootstrap signing/delivery and clean-machine acceptance remain pending. One-hour source authorization still expires and legacy unsigned controls remain separate. Android/SIM/personal WhatsApp physical proof and providers remain deferred; WhatsApp text/outgoing actions stay off.

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


[Reviewed recovery activation](RECOVERY_ACTIVATION.md) now provides initial typed workspace/memory/conversation/terminal creative adapters, atomic format-2 profile selection and rollback. Unknown records remain a compatibility refusal. Native Setup is implemented; broader adapters, signing and clean-machine acceptance remain pending.

[Original-account encrypted profile recovery](ENCRYPTED_PROFILE_RECOVERY.md) adds bounded full-tree backup, validation preview and digest-confirmed detached restoration. Initial reviewed activation and Native Setup are implemented; broader compatibility, signing and clean-machine acceptance remain pending.

[Directory-based version-slot management](DESKTOP_VERSION_SLOTS.md) now implements explicit selection, isolated per-version data, interrupted-copy recovery, rollback and a resident-lifetime manager lock. Initial reviewed activation and native install/removal controls are implemented; signed updates and clean-machine acceptance remain pending.

R1-R8 source milestones are implemented within their documented offline/fixture limits. The project is still a development/source pilot, not a signed, self-contained desktop or Android release. [Machine-readable gates](RELEASE_GATES.json) keep actual acceptance separate from source implementation. No additional R8 lettered step is planned.

Read-only Web inspector and printer-observation cleanup are implemented with synthetic acceptance; interactive desktop/browser automation and physical device acceptance remain pending. See [behavior and next implementation](BROWSER_INSPECTOR.md).

Reviewed desktop tasks are implemented with per-step approval, protected non-replayable receipts and fixture/native UI acceptance. Device/printer protocol separation and local Connections readiness are now implemented with fixture/native acceptance. See [adapter behavior and remaining limits](CONNECTION_ADAPTERS.md). [Behavior and limits](REVIEWED_TASKS.md).

## Offline release/support tools implemented

The [portable Python/core desktop pilot](PORTABLE_CORE_RUNTIME.md) is staged and locally accepted using its own isolated Python, core dependencies and Electron runtime without external npm resolution. Native install/removal controls and initial recovery are implemented; clean-machine acceptance, signing/license review and signed updates remain pending. The pilot launcher requires new isolated data and never adopts the production profile.

Android [build acceptance tooling](ANDROID_BUILD_ACCEPTANCE.md) is now implemented (21 October 2026): read-only preflight, strict offline builds, explicit dependency recording and fresh JVM/APK/signature/source evidence checks. The initial source-only milestone is historical. The 23 October strict offline build is now accepted; see [actual build evidence](qa/android-build-verification.json). Fixture behavior and a compiled APK still do not establish device installability or physical acceptance.

Reviewed [creative recipe handoffs](CREATIVE_HANDOFFS.md) are implemented with native fixture acceptance and durable provenance. This completes the latest independent source milestone; physical call bridge proof, Android/toolchain/device checks and signed self-contained distribution/recovery remain open.

Run with the existing environment; no command below installs packages, contacts a network, opens the private database, reads real notifications or changes startup settings:

```powershell
.venv/Scripts/python.exe scripts/release-tools.py diagnostics
.venv/Scripts/python.exe scripts/release-tools.py inventory
.venv/Scripts/python.exe scripts/release-tools.py readiness
.venv/Scripts/python.exe scripts/release-tools.py stage --directory .runtime/releases/my-new-pilot
.venv/Scripts/python.exe scripts/release-tools.py verify --directory .runtime/releases/my-new-pilot
```

Diagnostics emit an explicit whitelist: OS/architecture/Python version, presence of UI/Electron/core lock and Android tools, and SDK-configured boolean. They omit environment values, addresses, IDs, profiles, logs, paths, prompts, credentials and notification content. Inventory records installed Python package versions/license expressions and npm locked versions/license/integrity presence. Unknown licenses remain `REVIEW_REQUIRED`; this does not grant redistribution permission or cover Android/model assets.

Staging only creates a **new** direct child of `.runtime/releases`. It copies a bounded allowlist of runtime source, built UI/assets, launch helpers, dependency manifests, license and public configuration example. It excludes `.env`, backend settings, project/private data, cache, venv, node_modules, keys and databases. It rejects linked payloads/destinations. A SHA-256/size manifest is written last; interruption leaves an invalid partial directory, and no old pilot is overwritten. Verification rejects changed/missing/extra files, duplicate/noncanonical paths and links. Hashes detect accidental drift; they do not authenticate an unsigned manifest.

The resulting source pilot still needs Python 3.12 and a freshly created locked venv, Node 24, installed Electron/npm dependencies, and explicit optional mobile dependencies. It is not an installer and cannot be copied to another computer and run without setup. Python venvs and DPAPI profiles are not portable payloads. The staged pilot was verified locally; no deployment or actual installation was performed.

## Required release sequence

| Order | Work | Acceptance |
| --- | --- | --- |
| 1 | Android build environment and dependency verification, only when authorized | Compile APK/JVM tests with existing pinned versions, record locks/verification metadata and actual results; never infer success from source guards |
| 2 | Fold8 controlled acceptance | Explicit test-build/system-access consent; generated notifications first; Keystore recovery, fold/unfold, secure screen, network/lock/revoke, process death, queue ordering and Doze; real content only with explicit permission |
| 3 | Desktop packaging | Reproducible self-contained core plus separate optional worker/model bundles; clean Windows install/uninstall preserving user data; startup remains opt-in |
| 4 | Signing/license review | Owned signing/recovery identity; dependency/model/Android licenses and distribution rules; signed builds and verifiable provenance |
| 5 | Update and recovery | Signed explicit opt-in updates, staged versions, interruption recovery and rollback; encrypted detached profile recovery is implemented; reviewed activation/path compatibility and clean-machine original-account recovery remain pending |
| 6 | Laptop acceptance | Record exact Legion CPU/GPU/VRAM/RAM; ten-minute idle and multi-hour soak; user-deferred real-game benchmark stays deferred |

These gates need external tooling, physical devices, signing ownership or the previously deferred configuration. None was silently enabled to make a checklist appear complete. Existing [protected migration backup recovery](PERSISTENCE.md) remains available; release update/rollback is separate unfinished work.

## Advanced-feature backlog

| Track | Still pending |
| --- | --- |
| Memory enhancements | Project memory is implemented with local lexical search, consent, retention/forget and same-profile protected recovery. Optional embedding retrieval and portable cross-account recovery keys remain future work. See [Project memory](PROJECT_MEMORY.md). |
| Browser/desktop automation | Owned browser tasks, bounded DOM/accessibility contracts, hostile-content handling and app-specific acceptance |
| Devices/printing | Further adapter decomposition, actual capability discovery, slicer/printer completion and physical acceptance |
| Provider cost and quality acceptance | Usage allowance controls, token/local-job receipts and 12 offline contract evaluations are implemented. Actual provider invoice calibration and real model accuracy/creativity/latency acceptance remain deferred. See [Usage and quality](USAGE_AND_QUALITY.md). |
| Creative/media acceptance | Real Blender/local diffusion/kernel exports and microphone/camera/Bluetooth/sleep/voice quality once setup is explicitly chosen |
| Calls | The one-call CLI uses an owned Windows worker/watchdog; Connections exposes owner/project-scoped offline checks, Stop and synthetic records. 103 focused Python and 98 frontend checks, actual job termination and native UI acceptance pass. Live SIM/personal WhatsApp control/media still require physical proof; live enrollment/budget admission, owner live controls and phone receipt delivery are pending. [Lab and gates](CALL_LAB.md). No live call, driver installation, forwarding or account migration has been performed |
| WhatsApp actions | Excluded until specifically requested: no reply drafting, sending, acknowledgements or notification action execution |

Continue with source-only backlog work while setup remains deferred. Do not call the entire advanced roadmap complete, and do not create arbitrary lettered milestones for acceptance prerequisites.


## First post-revamp step completed

[Project memory](PROJECT_MEMORY.md) is implemented and fixture/native-desktop verified. This does not close Android/installer/signing gates. Usage allowance controls and offline evaluations are also implemented. The next source implementation is browser/device/printing modernization. No provider configuration or physical-device permissions were enabled.


## Second post-revamp step completed

[Usage and quality](USAGE_AND_QUALITY.md) implements conservative INARA admission allowances and explicit fixture evaluations. Monitor-only is the default; no live provider pricing or invoice ceiling is claimed. Source acceptance does not close provider-quality, Android, signing, installer or long-run hardware gates. Continue with owned browser/desktop tasks and device-adapter cleanup while setup stays deferred.
