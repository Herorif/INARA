# Release readiness and work after the revamp

R1-R8 source milestones are implemented within their documented offline/fixture limits. The project is still a development/source pilot, not a signed, self-contained desktop or Android release. [Machine-readable gates](RELEASE_GATES.json) keep actual acceptance separate from source implementation. No additional R8 lettered step is planned.

## Offline release/support tools implemented

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
| 5 | Update and recovery | Signed explicit opt-in updates, staged versions, interruption recovery and rollback; original-account protected backup/restore without overwriting a live profile |
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
| Calls | Handset/OEM/carrier feasibility first. Ordinary Android dialer control does not imply SIM/personal WhatsApp audio access. No forwarding/number migration/live-call action has been performed |
| WhatsApp actions | Excluded until specifically requested: no reply drafting, sending, acknowledgements or notification action execution |

Continue with source-only backlog work while setup remains deferred. Do not call the entire advanced roadmap complete, and do not create arbitrary lettered milestones for acceptance prerequisites.


## First post-revamp step completed

[Project memory](PROJECT_MEMORY.md) is implemented and fixture/native-desktop verified. This does not close Android/installer/signing gates. Usage allowance controls and offline evaluations are also implemented. The next source implementation is browser/device/printing modernization. No provider configuration or physical-device permissions were enabled.


## Second post-revamp step completed

[Usage and quality](USAGE_AND_QUALITY.md) implements conservative INARA admission allowances and explicit fixture evaluations. Monitor-only is the default; no live provider pricing or invoice ceiling is claimed. Source acceptance does not close provider-quality, Android, signing, installer or long-run hardware gates. Continue with owned browser/desktop tasks and device-adapter cleanup while setup stays deferred.
