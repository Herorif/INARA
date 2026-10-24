# Encrypted full-profile recovery copies

Implemented 21 October 2026. `scripts/desktop-backup.py` adds original-Windows-account encrypted backup, validation-only preview and detached recovery copies to [version-slot management](DESKTOP_VERSION_SLOTS.md). These tools run only on explicit invocation, with the installation's resident stopped. No model, provider, device, phone account or startup setting is activated.

## Encryption and scope

The complete initialized slot data tree is inventoried, including settings, projects, empty directories, database, legacy input and desktop profile. Nothing is silently excluded to fit a limit. For active managed recovery profiles, only the activation management receipt is excluded from application data. The pilot refuses more than 4,096 files/directories, 32 MiB per file or 64 MiB total data. Stored ZIP entries avoid decompression bombs and compression CPU; all payloads and encryption keys are handled in memory. This is a bounded foreground operation, not resident work or a streaming large-project backup service.

A fresh random AES-256-GCM key encrypts the archive, manifest, filenames and settings. Windows user-bound DPAPI protects that key, with no machine-wide or plaintext fallback. The authenticated envelope also binds its header and wrapped key. Only encrypted bytes are written to the backup file, opened exclusively so an existing backup is never replaced. Interrupted writes leave an invalid encrypted file. This does not promise memory erasure, cross-account portability or a tested recovery after Windows-account loss.

The authenticated manifest binds the source installation ID, exact package manifest digest, resident owner, file inventory/digests and data format. New archive format 2 also records the canonical source data root for reviewed relocation; format 1 remains readable. Preview and restore require retained original installation metadata and that exact registered package. The owner is compared with the current resident identity when it exists; missing original profile files do not prevent recovery of the authenticated saved copy. A different installation, package or resident identity rejects. This is same-installation profile recovery, not bare-metal installation reconstruction.

## Validation and restoration

The existing Windows manager lease spans each operation, excluding a managed resident or competing manager. Directly bypassing the managed launcher and unrelated external file writers remain outside that lease. Backup inventories and hashes twice to reject a changing source. Pending assistant-database WAL/shared-memory/journal sidecars reject rather than guessing which pages are committed.

Preview decrypts and validates entirely in memory. It checks strict JSON, bounds, exact inventory, hashes, safe Windows paths, case collisions, directory/file conflicts, settings object, resident identity and SQLite version-1 table layout/integrity. Inner compression, duplicate entries/keys, links/hardlinks, unknown payloads, device names, traversal and alternate-stream paths reject. SQLite WAL-mode headers are changed only in the in-memory validation copy, as described by [SQLite's deserialize contract](https://sqlite.org/c3ref/deserialize.html); the archived/restored database bytes remain unchanged.

Preview emits only counts, total bytes, format/protection status and the encrypted file's SHA-256. It emits no filenames, resident IDs, settings or record values. Restore requires this reviewed digest, rereads/revalidates the encrypted backup, and accepts only a new directory outside the installation. It verifies the copied tree before marking `.inara-recovery.json` complete. Failed/interrupted restores remain incomplete and are never reused or automatically repaired. Existing profiles and installation pointers remain untouched.

**Recovery copies are not activated.** Records currently contain absolute project paths and scope hashes. These are preserved exactly, including protected values; relocating files does not automatically make all project-scoped history/memory usable at the new path. [Reviewed activation with initial typed project adapters](RECOVERY_ACTIVATION.md) is now implemented separately; unsupported record groups still reject. Do not manually replace a live slot with this detached copy and assume compatibility. Retain the original package, installation metadata and Windows account.

## Commands

Use the verified control candidate's bundled Python; no external Python/npm or download is required. All parent directories below must already exist, while backup and recovery destinations must be new.

```powershell
$control = 'C:/path/to/verified-control-candidate'
$installation = 'C:/path/to/existing-managed-installation'
$slot = '<exact registered slot identifier>'
$file = 'C:/path/to/private-backups/new-profile.inara'
& "$control/runtime/python/python.exe" -I -B "$control/scripts/desktop-backup.py" backup --root $installation --slot $slot --file $file
& "$control/runtime/python/python.exe" -I -B "$control/scripts/desktop-backup.py" preview --root $installation --slot $slot --file $file
# Review the preview and copy its digest, then choose a new owner-controlled directory.
$digest = '<SHA-256 returned by preview>'
& "$control/runtime/python/python.exe" -I -B "$control/scripts/desktop-backup.py" restore --root $installation --slot $slot --file $file --expected-sha256 $digest --destination C:/path/to/new-private-recovery
```

The recovered files retain their original content and may include sensitive settings. Use an owner-controlled destination. The encryption envelope cannot authenticate an unsigned application publisher; signing/license clearance and production distribution remain separate gates.

## Verification

46 focused recovery tests cover encryption, full-tree/empty-directory preservation, protected record recovery, original-state preservation, account/owner/version mismatch, tampering/truncation, stale digest, schema drift, compressed/duplicate/oversized payloads, strict paths and inventory, busy resident, WAL refusal, changing files, existing destinations and interrupted completion. With the existing runtime/install/package regressions, **127 focused Python checks pass**; scoped Ruff passes.

Actual bundled-runtime Windows DPAPI acceptance passes backup, preview and restore in separate processes, followed by protected-record decoding in a fourth process. Every copied file matches its original bytes and empty directories survive; original profile and installation state remain unchanged. Only the previous milestone's documented synthetic test installation is used. [Sanitized evidence](qa/encrypted-profile-recovery.json). The new unsigned control candidate is `.runtime/releases/desktop-recovery-20261021` (2,984 inventoried files); its backup tools use bundled Python/core dependencies. Cross-account and clean-machine acceptance are not claimed.

## Next implementation

[Reviewed recovery activation](RECOVERY_ACTIVATION.md) now implements the initial workspace/memory/conversation/terminal creative adapters, review and rollback. Next is Windows installation/launch/uninstall UX; additional record adapters remain explicit compatibility work. Detached restoration itself remains non-activating.

Then complete Windows install/launch/uninstall UX, signing/license review, clean-machine acceptance and signed opt-in update recovery. Android compilation/device acceptance, real providers/Blender/image/speech/camera and physical SIM/personal WhatsApp duplex media remain separately gated. WhatsApp text/outgoing actions stay off; real-game benchmarking remains deferred.
