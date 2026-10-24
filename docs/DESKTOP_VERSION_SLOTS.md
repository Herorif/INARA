# Desktop version slots and interrupted-install recovery

Implemented 21 October 2026. The offline pilot manager adds verified version folders, explicit selection, separate owned data, rollback and interrupted-copy recovery to the [portable core runtime](PORTABLE_CORE_RUNTIME.md). This is directory-based pilot installation tooling, not a signed Windows installer/updater. It changes no registry, startup task, file association or production profile, and performs no downloads or recursive deletion.

## Behavior

`scripts/desktop-install.py` creates only a **new** explicitly named installation root. It never adopts an existing directory. The root contains `installation.json`, `versions/`, `transactions/` and `data/`. Version identifiers are the complete SHA-256 of the candidate's desktop manifest; arbitrary paths cannot be used as identifiers. Only integrity-verified bundled core pilots are accepted, with at most 16 registered slots.

Install first verifies the source, copies into a transaction directory, verifies the copied package and source identity, then renames into the version directory on the same filesystem. It writes a separate data ownership marker and finally commits registration by flushed temporary-file replacement. Installing or recovering a version never selects it. Selection and rollback verify package integrity and data ownership before atomically replacing the current/previous pointers. Interrupted selection leaves the old committed pointer in place. A damaged state file is preserved and rejected; it is never guessed or silently rebuilt.

Each version has its own data directory. Database, settings, projects, legacy input and desktop profile all point there. A new version starts empty; no settings, keys, databases, histories or projects are copied from an old version. Rollback restores the previous package **with that version's original data**, without merging work from the newer version. Export/reviewed migration remains separate release work; encrypted detached full-profile recovery is now implemented as described below. Existing protected project-memory and migration recovery retain their documented original-account limits.

`launch` must run with the selected version's bundled Python. It runs the resident in the same process and holds a Windows OS byte lock throughout its lifetime. Other manager operations refuse while that lock is held. The OS releases the lock after a crash; no stale-lock file is deleted. Existing native supervision owns resident child jobs. Directly bypassing this launcher is outside the managed-slot contract. This is a single installation-root lease, not a global prohibition on separately launched development profiles.

Links/junctions, incompatible metadata, unknown versions, changed packages, ambiguous transaction/version copies and unowned fixed data paths reject. Imported manager tooling disables bytecode writes so it cannot dirty its own package. Hashes detect drift and bind a slot to its manifest; they do not authenticate an unsigned publisher or defend against a hostile local user rewriting the entire installation.

## Commands

The control script is included in newly staged desktop packages and uses standard library plus bundled core dependencies. Keep a verified control candidate available even when rolling back to an older package that predates this script. Use its Python for management commands; launch requires the selected installed Python.

```powershell
$control = 'C:/path/to/verified-control-candidate'
$installation = 'C:/path/to/new-isolated-installation'
& "$control/runtime/python/python.exe" -I -B "$control/scripts/desktop-install.py" init --root $installation
& "$control/runtime/python/python.exe" -I -B "$control/scripts/desktop-install.py" install --root $installation --package $control
& "$control/runtime/python/python.exe" -I -B "$control/scripts/desktop-install.py" status --root $installation
# Copy the exact returned slot identifier into $slot, then explicitly select it.
$slot = '<full slot identifier returned by install>'
& "$control/runtime/python/python.exe" -I -B "$control/scripts/desktop-install.py" activate --root $installation --slot $slot
& "$installation/versions/$slot/runtime/python/python.exe" -I -B "$control/scripts/desktop-install.py" launch --root $installation
```

`launch --resident-only` starts the tray without opening the workspace. Quit INARA normally before management operations.

```powershell
# Explicitly return to the previous version and its separate data.
& "$control/runtime/python/python.exe" -I -B "$control/scripts/desktop-install.py" rollback --root $installation
# Finish registering a complete interrupted copy; this does not activate it.
& "$control/runtime/python/python.exe" -I -B "$control/scripts/desktop-install.py" recover --root $installation --slot $slot
# Clear the selected version while preserving every package and data folder.
& "$control/runtime/python/python.exe" -I -B "$control/scripts/desktop-install.py" deactivate --root $installation
```

A partial copy cannot be recovered until it independently passes full package verification. Preserve it and install a newly staged candidate separately. No cleanup command removes incomplete copies or old data. `deactivate` is not a Windows uninstall; data removal needs a future explicit, separately reviewed flow.

## Verification

Focused tests cover separate data/rollback, partial and complete interrupted copies, interruption after rename/data creation, atomic selection failure, changed payload/manifests, ownership and junction refusal, unknown/traversal identifiers, duplicate/root adoption refusal, damaged state, lock contention, process-death lock release and interpreter/environment isolation. **81 focused Python checks pass**, including 23 version-slot checks, plus scoped Ruff. Full-profile recovery, power-loss durability and clean-machine behavior are not established by simulated process/file-operation interruptions. Two real bundled core packages were installed, explicitly switched and rolled back under `.runtime/installations/slots-20261021`, preserving the original synthetic data. The final 2,983-file candidate, `.runtime/releases/desktop-slots-20261021-final`, was installed using its bundled Python under a separate fresh root. [Sanitized package/rollback evidence](qa/desktop-version-slots.json). The final installed resident passes actual native startup/shutdown using its own core/Python and fresh data, blocks switching during its lifetime, leaves its package unchanged and releases the lock after stopping. No workspace or model/device worker starts. [Native installed-slot acceptance](qa/desktop-install-native-verification.json).

## Next implementation

[Original-account encrypted detached recovery](ENCRYPTED_PROFILE_RECOVERY.md) is now implemented and validated. Next: reviewed recovery activation/project-path compatibility and Windows launch/install/uninstall UX that preserves data, then signing/license clearance and clean-machine interrupted-install/update acceptance. Signed opt-in updating and schema-compatible reviewed migration remain open. Directory snapshots and rollback pointers alone are not disaster recovery or cross-account portability.

The implemented [encrypted recovery contract](ENCRYPTED_PROFILE_RECOVERY.md) requires the resident to be stopped, uses bounded original-account encryption, validates ownership/schema/inventory before preview, and restores only into a new detached destination. Its activation and project-path compatibility limits remain explicit.

Android toolchain/device acceptance, actual provider/creative adapters and physical SIM/personal WhatsApp control/duplex-media proof remain separate gates. No account, call, phone permission, provider setting or WhatsApp text/outgoing action was activated.
