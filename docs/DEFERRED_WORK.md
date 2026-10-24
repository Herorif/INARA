# Deferred work and standing constraints

Owner instruction, 22 October 2026: always keep track of what has been deferred.

Read this register and [release gates](RELEASE_GATES.json) before choosing the next implementation. Preserve these items across handoffs. A generic request to continue implementation does not, by itself, resume deferred configuration, downloads, device activation or excluded account actions. Continue independent source work when possible. Report the relevant outstanding deferrals in completion updates; do not imply that source/fixture acceptance completes real production or device acceptance.

When an item changes, record the explicit decision, prerequisites and actual evidence here and in the matching release gate. Keep pending acceptance and optional backlog distinct from owner-deferred work. Do not silently mark an item complete, remove it from the roadmap or repeatedly ask to resume a preference the owner has already deferred.

Latest owner decision, 23 October 2026: resume Android/call-bridge setup, local-only, Samsung Fold 8 (owner-reported), controlled test calls later. This specifically resumes required development downloads/build setup; it does not resume live answering, other providers/devices, signing or excluded WhatsApp text actions. [Current setup](LOCAL_ONLY_SETUP.md).

Steps 4 and 5 added public custody/delivery preparation plus source-neutral receiving copies and a pending clean-machine checklist. They did not resume real configuration, signing or device testing. See [signing/delivery preparation](SIGNING_DELIVERY_PREPARATION.md) and [controller receiving](CONTROLLER_RECEIVING.md).

Order 2 source integration, 24 October 2026: [shared call admission](CALL_ADMISSION.md) and truthful availability are implemented; the standalone live CLI is disabled. No physical verifier/public live-start route, device permission, call, cloud provider or conversational model was enabled. Optional model evaluation is the next order; this completion does not resume model downloads or physical tests. Protected mobile receipt sync is now implemented in Order 4; real phone delivery/cache acceptance remains pending.

Owner request, 24 October 2026: implement Order 3. This resumes the selected optional local conversational candidate/runtime setup and evaluation. Official Qwen3 4B Q4_K_M and portable llama.cpp are installed/verified; **actual inference acceptance is now owner-deferred due to insufficient resources** (owner confirmed they cannot free sufficient RAM, 24 October 2026). No other applications were stopped. [Current model work](LOCAL_MODEL.md). This does not resume calls, unrelated models/providers/devices, signing or excluded account actions.

Order 4, 24 October 2026: [protected mobile receipt sync](MOBILE_CALL_RECEIPTS.md) and a fresh strict offline debug APK are accepted for source/build integration. No real pairing/grant, phone install, call, notification action or model benchmark was activated. Keep real phone/call tests and local-model measurement deferred. Android build heap is now 768 MB; the model guard remains 7 GiB.

Step 5, 24 October 2026: [controlled one-call software workflow](CONTROLLED_CALL_TESTING.md) is integrated and tested with synthetic evidence/inert supervisors. Physical collector integration remains missing; the local test policy is disabled, no live review can pass and no phone/audio/call/model ran. The owner's later controlled-call session remains deferred. Source completion does not establish SIM/personal WhatsApp feasibility or authorize activation.

## Deferred work and explicitly resumed setup

| Item | Still deferred / unverified | What permits resumption |
| --- | --- | --- |
| Production identities and signing | Publisher/reviewer enrollment and key custody, real certificates/timestamps, production signing and activation. Both production policies remain disabled. | Explicit configuration decision and owned identity/certificate inputs; source preparation can continue independently. |
| Android toolchain | **Setup resumed by the owner, 23 October 2026.** Workspace-local JDK/Gradle/SDK downloads and actual build/dependency recording are authorized. Tools/SDK installed and **actual strict offline debug build accepted**, 23 October: complete locks/SHA-256 metadata, Kotlin/Java compilation, one JVM protocol test and apksigner verification. Gradle 8.14.6 plus isolated per-project user-temp cache works; earlier failures are retained. [Build evidence](qa/android-build-verification.json). No device installation or permission is automatic. | Owner authorization is recorded. See [local-only setup](LOCAL_ONLY_SETUP.md) and its QA for current tool/build evidence. Device tests remain pending. Gate: `android-build`. |
| Providers and local models | **Local-only call speech setup resumed, 23 October 2026.** Small English Vosk model and Windows SAPI are configured and verified with synthetic in-memory audio. Cloud call inference/fallback is excluded by the selected mode. Order 3 explicitly resumes the selected Qwen/llama.cpp conversational candidate only; installation is verified but real model evaluation was refused for insufficient free RAM and remains pending. Other providers/image/general-purpose specialist models, Blender/kernel exports and camera/printer setup remain deferred. Physical call audio is unverified. | Owner authorized local call/Android setup only. Actual caller quality, latency, audio isolation and call-device tests remain pending; unrelated setup still needs an explicit decision. Gate: `real-capabilities`. |
| Real model cost and quality | Provider-specific pricing, invoice reconciliation, real-model task quality and latency. Current admission allowances are not a guaranteed invoice ceiling. | Chosen provider/model setup and measured evidence. Gate: `provider-cost-quality-acceptance`. |
| Legion sustained-use acceptance | Exact hardware inventory, idle measurement and multi-hour mixed-use acceptance remain outstanding. The real-game benchmark was explicitly deferred. | Owner resumes the relevant measurement; the real-game benchmark stays deferred until selected explicitly. Gate: `legion-soak`. |
| Live incoming calls | Setup resumed, but the owner explicitly scheduled **controlled test calls for later**, 23 October 2026. SIM/personal WhatsApp controls and isolated two-way audio remain unverified; no live answering is armed. | Resume the controlled test session with the actual Fold/host and a second caller. Dedicated audio routes and control enrollment must pass physical proof. Gate: `phone-call-feasibility`. |

## Standing exclusions and phone requirements

- Keep the owner's existing SIM and personal WhatsApp numbers/accounts. INARA speaking with incoming callers and taking a message remains the intended outcome.
- WhatsApp reply drafting/sending, acknowledgements and notification actions remain excluded until specifically requested. Gate: `whatsapp-actions`.
- Outgoing calls, call forwarding and WhatsApp Business migration have not been selected. Do not substitute them for the requested personal-account behavior or enable them automatically.
- Do not configure devices, enable collection, silently download SDKs/models, adopt real profiles or migrate private data as an incidental implementation step.

## Pending acceptance and backlog (not completed or automatically authorized)

| Area | Remaining work / gate |
| --- | --- |
| Controller and desktop distribution review | All **52 controller** ledger subjects and **85 desktop** ledger subjects remain separately pending. The controller scope increased from 51 by adding the external receiving tool (the prior three preparation tools increased 48 to 51); no subject was approved. Earlier immutable ledgers are retained. Provenance collection is not ownership/license approval. `controller-distribution-review`, `distribution-signing-licenses`. |
| Production Windows lifecycle | Owned signed-package/native-window mutation, trusted bootstrap delivery and clean Windows account/machine install, launch, update/rollback, interruption recovery and removal acceptance. `managed-native-lifecycle-ux`, `clean-machine-install`, `update-rollback`. Step 3 source lifecycle integration is complete; these real acceptance gates remain open. |
| Physical Android and distribution | Fold device Keystore, process death, fold/unfold, Doze, TLS, permissions/revocation/privacy, plus APK signing/recovery ownership and install/update/removal acceptance. Requires the actual build and owner-approved device setup. `fold8-device`, `android-distribution`. |
| Local candidate acceptance | Order 3 real quality/latency/peak-RAM evaluation requires at least 7 GiB available RAM. It refused before loading; no measured model-quality claim is made. The owner confirmed insufficient resources on 24 October 2026; the real benchmark is now explicitly deferred until resources are available. Do not lower the guard or silently substitute/download another model. `local-call-model-quality`. |
| Broader recovery and memory | Unsupported record adapters, portable cross-account recovery keys and optional embedding-based semantic retrieval. Existing ownership/type limits remain enforced. `memory-enhancements`; compatibility also remains part of `update-rollback`. |
| Interactive automation and real adapters | Interactive browser action policy and actual vendor SDK/network/physical-device acceptance. Existing read-only/reviewed fixture checks do not complete real adapter acceptance. `automation-device-modernization`. |

Current implementation and evidence: [handoff](IMPLEMENTATION_HANDOFF.md), [status](IMPLEMENTATION_STATUS.md), [release readiness](RELEASE_READINESS.md), [protected lifecycle](MANAGED_LIFECYCLE.md). The release-gate file remains the machine-readable acceptance record; this register preserves the owner's deferral decisions and constraints.
