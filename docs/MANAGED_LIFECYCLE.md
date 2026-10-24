# Protected profile and removal lifecycle

Step 3 adds original-account encrypted backups, typed recovery-copy preparation, separately signed profile activation/rollback, software removal and separate profile file erasure to protected format-3 installations. The native window now exposes **Profiles** and **Lifecycle** pages alongside signed updates and interrupted-change recovery. The existing unsigned Setup controls continue to refuse protected installations.

## Backups and recovery copies

Stop the resident first. Enter the protected installation, separate checkpoint directory and independently retained latest checkpoint pin. On Profiles, enter the exact installed version identifier and a new external `.inara` file. Review encrypted backup, then confirm. The review binds the selected profile's file/directory digest, version, output path and checkpoint. Creation validates the bounded profile/database and rechecks source bytes. A changed source invalidates the review. Encryption uses a fresh AES-GCM key wrapped for the original Windows account; no plaintext archive or key is written to disk.

To restore, choose the existing backup and generate a new recovery profile identifier. **Review recovery copy** checks the original installation/version/account/owner and runs the existing typed rebind adapters. Confirm prepares a separate profile with an incomplete/prepared receipt; it leaves the current profile and signed metadata unchanged. Unknown records, unsupported migrations, active jobs, incompatible project/session scopes and altered artifacts refuse. Incomplete copies remain for inspection and are never silently adopted or overwritten. Use another new identifier for a new attempt.

Backups/copy preparation require a registered installed version. Make a backup before software removal. They do not import foreign profiles, bypass unknown ownership, recover across Windows accounts or broaden the existing typed record support. External archive/request paths must stay outside the installation, checkpoint directory and trusted controller checkout. The controller remains external to the installation it manages.

## Separately signed lifecycle changes

Profile selection and removal change signed installation metadata. They require an explicit lifecycle authorization, not an unsigned metadata edit. Prepare a request with the trusted controller, have the configured publisher/reviewer cohorts sign the exact domain-separated bytes externally, then use the signed envelope in the native Lifecycle page. No signing key loader or automatic identity enrollment is added.

The actions are:

- `activate-profile`: select a complete prepared copy while keeping the previous profile. Current and target resident owners must match. Activation rechecks receipt generation/selection, every prepared file/directory and typed database compatibility. Rewriting an unsigned receipt cannot bypass the typed check.
- `rollback-profile`: return to the previous compatible profile without deleting the current copy or original data.
- `remove-software`: remove every verified registered version and clear version/profile selections. Retain original/recovery profiles, external backups, admission capsules, signatures, grant history, sequence floor, checkpoints and policy history.
- `erase-data`: after software is removed and no unresolved versions/transactions remain, delete only installation-owned original/recovery profile files. It requires the separate exact phrase `ERASE INARA DATA` at apply and again at erasure resumption.

All changes keep format 3, increment generation/checkpoint number and retain the sequence floor and current grant head. Lifecycle changes cannot rotate trust or replace launch grants. A removed installation can report protected metadata status, but has no selected payload to launch. Reinstallation needs a fresh signed package/update above the retained sequence floor; retained profiles are not automatically rebound or activated.

Lifecycle authorization uses `INARA:managed-lifecycle:v1` plus canonical statement bytes, with both `signatures_before` and `signatures_after` meeting the same current enrolled policy's publisher/reviewer thresholds. The statement binds root/installation/anchor, old checkpoint/head, policy history, exact before/after metadata images, action, profile binding and deletion inventory digest/counts. Its live apply window is at most one hour. Managed-change signatures from the update domain cannot authorize a lifecycle action. Historical checkpoints revalidate lifecycle signatures at their issuance time, retaining the existing historical-trust model.

## Trusted command workflow

Run these finite commands through `open-trusted-controller.ps1` and the independent controller inventory pin, as documented in [native management](MANAGED_NATIVE_UI.md). Paths below are placeholders; configuration stays deferred.

```text
Common inputs:
  --root <protected installation> --anchor <separate checkpoint directory>
  --expected-state <independently retained latest checkpoint>

review-profile-copy <common> --copy-operation backup --slot <version> --file <NEW external .inara>
apply-profile-copy <same> --expected-review <copy review>

review-profile-copy <common> --copy-operation prepare-profile --slot <version>
  --file <existing external .inara> --profile <new UUID hex>
apply-profile-copy <same> --expected-review <copy review>

prepare-lifecycle <common> --action activate-profile --slot <version>
  --profile <prepared UUID hex> --output <NEW external request directory> --minutes 30
# Other actions: rollback-profile, remove-software, erase-data.
# Omit --profile for those actions; --slot retains the explicit version context.
# External cohorts sign signing-message.bin; envelope fields:
# statement, signatures_before, signatures_after.

review-lifecycle <common> --change <signed lifecycle envelope>
apply-lifecycle <same> --expected-review <lifecycle review>
# Erasure additionally requires --confirmation "ERASE INARA DATA".
# Independently retain the returned checkpoint; it is never automatically adopted.

review-resume --root ... --anchor ... --expected-state <prepared checkpoint>
  --previous-state <previous committed checkpoint>
resume-change <same> --expected-review <recovery review>
# Erasure resumption additionally requires --confirmation "ERASE INARA DATA".
review-abort/abort-change use the same exact pins and require a fresh abort review.
```

The native UI uses the same finite private worker, five-minute single-use reviews and exact backend revalidation. Profile copy and lifecycle fields invalidate reviews on edit; conflicting actions and window closure are blocked while busy. No provider, model, resident, phone adapter or network listener starts. The worker resolves the packaged lifecycle/copy adapters before announcing readiness. Returned or prepared pins remain explicit owner inputs.

## Removal, interruption and retained evidence

Before deletion, the controller rederives the exact signed inventory, verifies owned roots and all remaining bytes, seals the inventory with current-account protection in the external anchor, writes a protected signed checkpoint and creates the existing update transaction journal. Private filename inventories are not written as plaintext journal/receipt content. Only scoped individual files are unlinked; directories are removed only when empty. There is no blind recursive deletion.

Reviewed recovery binds the prepared and previous checkpoint pins, exact signed journal/metadata images and sealed deletion inventory. It accepts only matching remaining files and already removed entries. Changed/partial files, extra files, unknown roots, links, corrupted inventories or conflicting metadata refuse with evidence retained. Resume repeats the same originally signed operation under a fresh local review; historical authorization may be replayed only for that exact retained transaction. No new deletion scope or trust is inferred from local pointers.

Cancellation requires unchanged committed metadata **and all original removal entries still present**. It refuses after the first deletion, even before metadata commit. Successful cancellation removes only the journal and retains copied files/checkpoint/inventory evidence. Signed update recovery remains separate internally but shares the native recovery controls. All ordinary management and guarded launch refuse while the journal is pending.

Software removal retains personal data. Separate erasure removes owned profile files; it is not secure disk sanitization and does not erase external backups, admission/signature evidence, protected metadata history or encrypted deletion inventories. The latter retain file-path metadata needed for audit/recovery, not profile contents. The existing account-compromise and independently retained latest-pin limitations still apply; DPAPI is not a hardware counter or cross-account recovery key.

## Acceptance and next steps

[Execution evidence](qa/managed-lifecycle-verification.json) records focused signed lifecycle/update/profile/storage regressions, real Windows account-protected backup/preparation, native wide/narrow interaction renders, packaged worker/bootstrap acceptance and fresh controller provenance. Tests use synthetic signing identities, inert payloads and injected native-signature adapters for source fixtures. No production profile or identity is configured, real release signed, provider contacted or physical device enabled. Production native-window mutations, owned signing/delivery and clean-machine interruption acceptance remain separate gates.

The controller inventory/notice review is renewed for the new artifact; all controller and desktop ownership decisions remain pending separately. Next: owned publisher/reviewer identity custody and Windows signing/trusted delivery preparation, followed by real signed-package and clean-machine lifecycle acceptance when configuration is authorized. Android and physical SIM/personal WhatsApp duplex-audio feasibility, real creative/voice/vision providers and sustained Legion acceptance remain separate. WhatsApp text/outgoing actions stay off; real-game benchmarking remains deferred.
