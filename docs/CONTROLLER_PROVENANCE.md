# Controller provenance and notice evidence

The trusted controller is audited separately from the desktop candidate. `scripts/controller-provenance.py` verifies its independently retained manifest pin and full file closure using trusted checkout code, without executing the packaged runtime. It requires a source snapshot matching every packaged source file. It neither changes nor repackages the controller.

The offline evidence includes all shipped Python dependencies, CPython and project license text, verbatim deduplicated notices, metadata origin hints, and the exact native executable/library inventory. It also retains copies and hashes of the external PowerShell bootstrap, assembly tool and collector as delivery-source inputs, recording which also ship in the controller. The current controller carries the complete core runtime: dependencies are inventoried even if the controller does not import them. No npm, Electron, renderer, model or phone ownership decision is inherited from another artifact.

Metadata URLs are unverified hints. Local bytes establish neither an upstream acquisition chain nor native/vendor subcomponent coverage. Missing undeclared notices become explicit pending subjects; a missing declared license, dependency mismatch or source drift refuses collection. Runtime support, security baselines, license obligations, native internals and delivery ownership remain owner-review work.

## Reproduce against retained local inputs

Run from the independently trusted source snapshot. Obtain the expected manifest pin independently; do not adopt one from a received artifact. Use a new, separate output directory for each collection. This collector is checkout tooling, not a new command exposed by the packaged controller.

```powershell
.venv/Scripts/python.exe scripts/controller-provenance.py collect --controller .runtime/controllers/managed-lifecycle-20261022-accepted --expected-manifest eec5097e7ddea570ab46213ad79fd910c8c886dc1462a538de5e3a35eec66d89 --output .runtime/controller-provenance/receiving-20261022-accepted
.venv/Scripts/python.exe scripts/controller-provenance.py verify --controller .runtime/controllers/managed-lifecycle-20261022-accepted --expected-manifest eec5097e7ddea570ab46213ad79fd910c8c886dc1462a538de5e3a35eec66d89 --output .runtime/controller-provenance/receiving-20261022-accepted
```

`--source` may identify an exact retained checkout snapshot. Verification regenerates every report, queue entry, copied delivery input and notice from the pinned controller and source. It rejects extras, missing files, edits, source drift and claims of approval. Collection never overwrites existing evidence. A later collector/source/controller revision needs fresh collection and review.

## Evidence and remaining decisions

The existing **2,681-file controller** yields **43 components, 51 notice files, 38 native files and 52 pending review subjects**, with zero missing component-level notices. These are observed inventories, not complete native subcomponent attribution or license clearance. The 52 subjects comprise 43 components, one CPython support/security baseline, one native/vendor coverage review and seven external delivery inputs. Three Step 4 preparation tools expanded 48 to 51; the Step 5 receiving tool expanded 51 to 52. All subjects remain pending. See [receiving preparation](CONTROLLER_RECEIVING.md); producer collection/rederivation still requires the matching source while receiving verification endorses the signed evidence without source regeneration.

Retained output `.runtime/controller-provenance/receiving-20261022-accepted` contains:

- `controller-provenance.json`: bound input hashes, metadata, native inventory and review gaps.
- `THIRD_PARTY_NOTICES.txt` and `notices/`: combined and exact verbatim notice evidence.
- `external/`: the separate bootstrap/assembly/collector source copies.
- `controller-review-queue.json`: deterministic subject identities and required evidence categories, all pending.

The queue remains an immutable pending review checklist. A separate [controller ledger and custody/delivery preparation workflow](SIGNING_DELIVERY_PREPARATION.md) now records explicit owner-reviewed assertions in new revisions; it does not rewrite or approve the queue. It is not accepted as the desktop distribution ledger or a release authorization input. Real source/license/obligation/custody/delivery decisions, independent enrollment and actual production acceptance remain required before distribution. All **85 desktop review subjects** remain pending separately. Both production policies remain disabled; nothing is signed, installed, downloaded, migrated or launched by collection.

[Current verification evidence](qa/controller-receiving-verification.json) and [historical Step 1 evidence](qa/controller-provenance-verification.json) records the actual pinned-artifact result and focused checks. The native format-3 status/update/recovery window is now implemented in [protected management](MANAGED_NATIVE_UI.md). Protected backup/restore and signed removal are now implemented in [protected lifecycle](MANAGED_LIFECYCLE.md). Next: owned signing/trusted delivery and signed clean-machine acceptance. The original Step 1 evidence remains a historical 2,672-file artifact/source snapshot; updated collector/source revisions require fresh evidence. See [managed updates](MANAGED_UPDATES.md).
