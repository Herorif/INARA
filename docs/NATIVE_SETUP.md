# Native Windows setup, launcher and removal controls

For protected format-3 installations, use the separate [protected management window](MANAGED_NATIVE_UI.md) for status, signed changes and interrupted-update recovery. The earlier unsigned controls below intentionally refuse protected roots; [protected profile/removal lifecycle integration](MANAGED_LIFECYCLE.md) is now available through its separately signed workflow.

Implemented 21 October 2026. A native WPF interface now fronts the [version slots](DESKTOP_VERSION_SLOTS.md), [encrypted backups](ENCRYPTED_PROFILE_RECOVERY.md) and [reviewed recovery activation](RECOVERY_ACTIVATION.md). It uses Windows PowerShell/WPF and the verified candidate's bundled Python. No browser server, Node runtime, model, provider or phone adapter is started by Setup itself.

## Open Setup

From a verified extracted bundled candidate, double-click **INARA Setup.cmd**. The adjacent PowerShell entry opens the dark cyan INARA setup window. Keep this control candidate **outside** the managed installation: it must remain available to launch and manage versions and to remove their executable files. The copy inside an installed version is not a replacement for that external control entry.

The command wrapper uses a process-only execution-policy argument. No persistent execution policy, registry app registration, Windows startup entry, file association, Start menu/desktop shortcut or MSI service is configured. This is a native interface for the directory-based local pilot, not a signed EXE/MSI installer or Windows Apps registration. Windows distribution and clean-machine acceptance remain separate gates.

The default installation location is shown as text; no directory is created until the owner reviews and confirms installation. Use **New...** to choose a parent for a new INARA folder, or **Existing...** to inspect a managed installation. **Check** refreshes its state.

## Owner workflows

**Installation** reviews a bundled package and a new/existing target folder, installs without launching or selecting it, lists builds, reviews version selection/rollback, and launches the selected version. The tray is the default launch mode; opening the full workspace is a separate unchecked preference. Startup remains manual. A launch request means the process was requested, not proof that the core reached ready state. Use INARA's tray controls to open/quit a running resident; management changes require it to stop.

**Recovery** selects an encrypted file and the installed build, reviews an original-account backup or compatible recovery copy, prepares without activating, then separately reviews activation or previous-profile rollback. It retains the existing typed adapter limits: unknown records, incompatible owners/scopes and stale/changed prepared copies refuse. It does not convert accounts, substitute versions or discard unsupported data.

**Remove** separates software removal from personal data erasure. Removing software clears registered version/profile selections and deletes only verified installed version payloads. Original data, prepared/live recovery profiles and external encrypted backups remain. Exact-build reinstall explicitly reviews reuse of retained original data or the retained selected recovery profile, including owner checks; reinstall still does not select or launch by itself.

**Permanent data erasure** is available after software removal. It is a separate review and requires typing `ERASE INARA DATA` exactly. Only installation-owned `data/<slot>` and `recovery-profiles/<uuid>` trees are eligible. External encrypted backups remain. Installation/audit metadata remains so the controls can recognize the empty managed location; no private file names/content are kept in completed removal receipts.

## Review and interruption contract

A single private stdin/stdout worker is verified once when the native window opens. The UI makes no HTTP listener and delegates only a fixed action set. User paths travel as bounded JSON, not shell fragments. Paths must be local, absolute and unlinked. No caller/model can invoke these controls over the supported assistant transport.

Each mutation has a five-minute, single-use, in-memory review token binding its exact arguments, candidate identity and installation-state fingerprint. Editing inputs invalidates the UI review. A newer/failed review replaces the old token. Apply consumes it even on failure, so an uncertain response cannot be replayed. Expired/state-changed/package-changed reviews refuse; refresh status before reviewing again.

The UI remains responsive while the worker reads/copies/verifies files. Conflicting actions and fields are disabled, progress remains visible, and closing an active operation is blocked until its result arrives. Closing an idle setup window discards pending reviews. An explicitly launched resident is independent of Setup; closing Setup does not stop INARA. Its existing OS lease still blocks installation/recovery/removal while it runs.

Removal first inventories and checks every owned path and writes a bounded `removal-pending.json` journal. All remaining files are rechecked before deletion; extra/changed/linked/foreign files refuse. Directory removal uses empty-directory operations, not blind recursive deletion. Every resolved target is checked against its fixed version/data root. Interruption preserves the journal and blocks ordinary management/launch. **Resume interrupted removal** reviews and finishes that same operation, skipping already removed entries and atomically committing metadata. Data-erasure resumption requires the exact phrase again. Completed receipts keep only operation identity/counts/retained recovery selection, never private file names or record contents.

Hashes detect drift; they do not authenticate an unsigned publisher. The same-installation/original-account and compatibility limits documented in the recovery milestones still apply. Simulated interruption tests do not certify power-loss durability or clean-machine behavior.

## Verification

**174 focused Python checks pass**, including 23 control/removal checks, plus scoped Ruff and PowerShell parser checks. Native WPF renders at 1120 and 780 pixels verify review invalidation, separate exact erasure confirmation, tray-first launch mode, recovery routing and busy-action locking. A real bundled Python worker behind the native dispatcher passes verified startup and read-only status without creating an installation, and busy window closing is refused.

The real bundled-package workflow passes installation, explicit selection, owned resident launch, independence from Setup closure, manager-lease refusal while resident runs, graceful owned shutdown, software removal retaining private test data, and separately confirmed erasure. No production profile is used. [Package evidence](qa/setup-package-verification.json), [private-worker evidence](qa/setup-bridge-verification.json), [UI evidence](qa/setup-ui-verification.json), [overview](qa/setup-overview.png), [narrow erasure review](qa/setup-erasure-780.png).

Unsigned candidates contain 2,990 inventoried files. Full workflow evidence uses `.runtime/releases/native-setup-20261021-final`; the accepted candidate `.runtime/releases/native-setup-20261021-accepted` adds only the tested empty-recovery-container status correction and passes actual native private-worker acceptance. These are development-host tests, not clean-machine certification.

## Next implementation

[Candidate-bound provenance and notice collection](DISTRIBUTION_PROVENANCE.md) is now implemented. Next: exact renderer build provenance and copied-asset ownership, followed by dependency/security baseline review, explicit redistribution decisions, owned signing identities and clean-machine install/uninstall/update/interruption acceptance. No signing certificate, provider configuration, SDK/model download or production activation is implied. Signing and an actual clean Windows account/machine need their own evidence.

Broader recovery adapters remain explicit work. Android tooling/device acceptance, real providers/Blender/image/speech/camera, physical SIM/personal WhatsApp control/duplex media and sustained Legion acceptance stay separately gated. WhatsApp text/outgoing actions remain off; real-game benchmarking remains deferred.
