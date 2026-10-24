# Protected checkpoints, trust rotation and signed version changes

Implemented 22 October 2026. `scripts/managed-update.py` adds independently pinned account-protected checkpoints, dual-policy authorization, local authenticated-package intake and reviewed version selection/rollback. Configuration remains deferred: both checked-in production policies are disabled, actual ownership reviews remain pending and no production root was adopted.

## State and trust boundaries

The checkpoint directory must be separate from the installation. It retains public policy snapshots by raw SHA-256, immutable protected checkpoints and a current pointer. `scripts/protected-state.py` uses current-account Windows DPAPI with domain entropy, no UI and no machine-wide scope. Each encrypted checkpoint retains before/after installation and grant-head metadata images, their signed hashes, policy history, grant hash, sequence floor, previous checkpoint and signed change. It contains no private signing key or profile/database contents. See [CryptProtectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata) and [CryptUnprotectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptunprotectdata).

DPAPI provides account-bound protection, not publisher authorization or a hardware counter. The controller additionally validates detached signatures and requires an **independently retained latest plaintext-checkpoint hash**. A ciphertext/pointer cannot nominate its own trusted pin. Restoring old metadata, a prior pointer or an old checkpoint refuses against the latest pin. Deliberately accepting a stale external pin, rolling back the whole trusted environment/clock, privileged account compromise or signing-key compromise remains outside that guarantee. Cross-account/clean-machine acceptance is not claimed; loss of the original account's DPAPI access can prevent checkpoint recovery. There is no silent account migration or trust-reset fallback.

An existing format-1/2 root must already have a signed launch grant before enrollment. Successful reviewed enrollment preserves its ID, registered versions and typed recovery selection, upgrading metadata to **format 3 / authenticated-pilot-slots** with an external anchor binding. Default unsigned controls, the prior grant CLI and older format-1/2 validators refuse that format. They do not silently downgrade it. Use `managed-status`, `managed-launch` and the managed change/recovery commands for that root. Native Setup, removal, backup/recovery activation UX for format 3 still needs integration; do not adopt a real root as a substitute for that release work. Existing unmanaged roots remain unchanged by default.

## Authorized changes

Each change first needs a new launch grant in the existing grant signing domain, bound to the exact target slot, package manifest/attestation, root/ID, proposed policies, sequence and previous grant. A separate `INARA:managed-change:v1` statement binds the action, previous checkpoint/head, next number, prior sequence floor, source policy, exact before/after metadata hashes and policy-history digest. Change validity is bounded to at most one hour. Both the current and proposed release policy must independently meet their publisher **and** reviewer thresholds over that statement. Even a valid new-policy signature cannot replace old-policy approval.

Policy rotation keeps publisher/channel unchanged, advances policy sequence by exactly one and never lowers its minimum package sequence. Proposed policies must be production-purpose; absent, disabled, fixture, unknown/revoked/duplicate or insufficient signers refuse. Existing keys must still be able to authorize an ordinary change; lost/expired old authority has no bypass here. New Windows certificate expectations are also digest-bound and checked against the actual target. An update/rollback may explicitly include a trust change with the same dual-policy approval requirements.

| Action | Allowed effect |
| --- | --- |
| `enroll` | Adopt the currently selected, already admitted version into a new external anchor; application bytes/trust stay unchanged. |
| `renew` | Renew the current version under unchanged policies. |
| `rotate` | Change trust for the current version without replacing application bytes. |
| `update` | Select a different authenticated slot whose package sequence is strictly above the retained high-water mark; a new local package can be copied and registered. |
| `rollback` | Explicitly authorize a different retained older slot. The high-water mark stays unchanged, and the current policy minimum still applies. |

Source packages must belong to current/proposed or previously authorized policy history. Their original signatures, inventory and approved review evidence are checked at original issuance; **fresh grant/change signatures** authorize current use. This does not expose a generic ignore-expiry flag. Historical public policy snapshots preserve source verification across rotation; old package keys do not become current launch authority. Native signer/timestamp checks use the proposed current Windows policy.

## Transaction and data handling

`review-change` revalidates signatures and current checkpoint/state, target source/profile, native signatures and exact proposed metadata before returning a review digest and the next checkpoint hash. Inspect the signed statement together with that review. `apply-change` requires the exact review and rechecks state under the installation and external-anchor leases. It snapshots pinned policies, seals the checkpoint, retains the target grant, then writes a bounded transaction journal before copying/selecting anything. Changed external policy bytes refuse instead of being archived under a stale pin.

New local packages are copied into a pending slot, checked against the signed inventory, validated by the controller's own core/runtime verifier and renamed only after a complete check. The signature/audit/ledger admission capsule is retained and verified. A new slot receives its own original profile marker, or reuses only a compatible already owned profile. Data is **not automatically migrated between version profiles**. All older versions, original/recovery profiles and their contents remain retained; rollback selects the retained target's owned profile.

Commit writes installation metadata, the grant-head metadata, then the external checkpoint pointer. These are journaled ordered writes, not a claim of an OS-wide atomic filesystem transaction. Managed launch refuses while the journal exists or metadata does not match the externally pinned checkpoint. A completed transaction removes only its exact journal; there is no recursive version/profile deletion, download, startup registration, model configuration or automatic resident launch.

## Interrupted changes

Retain the review's proposed new checkpoint hash and prior checkpoint hash. `review-resume`/`resume-change` require both pins and an exact recovery review. They verify protected metadata images and the signed transition, refuse unknown partial metadata or pointers, verify the retained target grant's exact bytes/current validity, then recheck source/profile/native trust before completing the same ordered commit. The transition itself is replayed at its signed issuance time only for this already prepared recovery; the launch grant must still be live. There is no automatic retry, selection fallback or downgrade.

Keep the original authenticated package available at its reviewed path until commit/recovery completes. Missing sources, partial/altered copies, conflicting capsules or an expired target grant refuse and remain retained. A complete pending copy can be verified and finalized; arbitrary partial bytes are never overwritten or silently repaired. Recovery after grant expiry or lost account protection requires further explicit owner recovery work.

`review-abort`/`abort-change` may cancel a prepared change **only before any committed metadata has changed**, after exact journal/checkpoint/before-state validation and review. It removes only the journal, retaining copied files, policy/grant history and protected evidence. Once metadata commit has started, cancellation refuses; use reviewed resume. After cancelled initial enrollment, the unmanaged root is retained and a later enrollment needs a new external anchor directory. This is cancellation of unapplied work, not an unsigned downgrade of a committed managed version.

## Controller workflow

Commands run through the independently trusted bootstrap/controller inventory pin. Paths, source package and policy inputs are local; trust inputs and request outputs stay outside the installation and checkpoint directories. Do not infer pins from untrusted received files.

```text
Common change inputs:
  --root <installation> --anchor <separate directory>
  --expected-state <latest checkpoint hash, or new for initial enrollment>
  --expected-head <current grant hash>
  --policy <current external release policy> --expected-policy <retained pin>
  --windows-policy <current external native policy> --expected-windows-policy <pin>
  --action enroll|renew|rotate|update|rollback
Optional proposed trust:
  --next-policy <file> --expected-next-policy <pin>
  --next-windows-policy <file> --expected-next-windows-policy <pin>

prepare-managed-grant <common> --slot <target> --sequence <package sequence>
  [--package <new authenticated container>] --hours 24 --output <new request>
# External owner signer cohorts sign the exact launch-grant request.
prepare-change <common> --grant <signed grant> [--package <new container>]
  --minutes 30 --output <new change request>
# External old/new cohorts sign the same domain-separated change message.
# Envelope: statement, signatures_before, signatures_after.
review-change <common> --grant <signed grant> --change <signed change> [--package ...]
apply-change <same inputs> --expected-review <review digest>
# Retain the returned checkpoint independently.
managed-status --root ... --anchor ... --expected-state <latest checkpoint>
managed-launch --root ... --anchor ... --expected-state <latest checkpoint> [--resident-only]

review-resume --root ... --anchor ... --expected-state <prepared new checkpoint>
  --previous-state <prior checkpoint, or new>
resume-change <same recovery inputs> --expected-review <recovery digest>
review-abort/abort-change use the same old/new pins; abort-change requires its review.
```

There is no private-key loader or signing CLI. The checkpoint-pinned launcher reuses the existing isolated resident/process-tree guard, manager/file leases and owned profile environment, using archived source policies and current grant/native trust. Root metadata, policy history and checkpoint are rechecked after file leases. Renewal/changes refuse while a managed resident holds the leases. No fixture adapter is exposed as a command option.

## Acceptance and remaining work

**281 focused Python checks pass**, including 31 managed-state tests, plus 11 release-boundary checks and scoped Ruff. Source acceptance uses synthetic production-purpose policies, ephemeral in-memory test keys, approved **synthetic** ledgers and inert payloads. It covers real account protection, enrollment, fresh keys, renewal across source expiry, new-slot intake, rollback without lowering the sequence floor, write-boundary recovery, cancellation, stale pins/reviews, damaged journals/ciphertext/policies, profile preservation and lifetime leases. Native signature adapters are injected for these inert fixtures; this is not a real signed desktop update or clean-machine acceptance. [Sanitized execution evidence](qa/managed-update-verification.json) records the focused test result, actual DPAPI refusal probes and updated controller/bootstrap verification. No real release key, certificate, profile or production root is configured; all 85 actual review subjects remain pending.

Controller-specific inventory/notices and the pending review checklist are now implemented in [controller provenance](CONTROLLER_PROVENANCE.md); 48 controller reviews remain pending separately from the 85 desktop subjects. The native format-3 status/update/resume/cancellation interface is now implemented in [protected management](MANAGED_NATIVE_UI.md). Protected backup/restore, signed profile selection and separate software/profile removal are now implemented in [protected lifecycle](MANAGED_LIFECYCLE.md). Lifecycle checkpoints use a separate signed domain, retain format 3, grant history and sequence floors, and share exact journal recovery with deletion-aware cancellation. Next: owned signed-bootstrap delivery and clean-machine resident/Electron/job/lifecycle acceptance. Owner certificate and redistribution decisions remain separate gates. Keep Android/physical SIM/personal WhatsApp duplex-media proof separate, WhatsApp text/outgoing actions off, provider/toolchain/model configuration deferred and the real-game benchmark deferred.
