# Distribution provenance and signing readiness

[Exact observed renderer/worker build provenance and copied-asset inventory](RENDERER_PROVENANCE.md) are now implemented for newly staged candidates. The conservative counts and missing-record inventory below describe the earlier candidate and remain historical. New auditing selects observed chunk/copy package origins while preserving all unresolved ownership and signing gates.

Implemented 21 October 2026. `scripts/distribution-audit.py` collects offline, candidate-bound dependency and notice evidence for a verified bundled-core pilot. It uses the standard library and existing integrity validators, including their host-environment `packaging` dependency for pinned requirement checks. It neither modifies the candidate nor signs, publishes, downloads or activates anything.

## What is recorded

- The exact candidate manifest/inventory SHA-256 and collector-script SHA-256.
- Application, CPython and Electron/Chromium notice files retained in that candidate.
- Every pinned Python runtime distribution, its candidate METADATA, declared license and recognized notice files. Declared `License-File` entries must exist; unknown, duplicate or mismatched distributions refuse.
- Native Electron bundle input hashes and the corresponding installed npm package metadata matched to the candidate's npm lock.
- A conservative superset of non-development npm-lock packages for the renderer, including installed path identity for nested/duplicate versions. This is explicitly **not an exact renderer module graph**. Unused packages may appear, and copied/vendor assets need additional ownership evidence.
- Raw notice files copied verbatim to content-addressed filenames, a readable combined `THIRD_PARTY_NOTICES.txt`, and an inventory of missing recognized notice files. License declarations and notice availability remain separate fields. No redistribution decision is automatically approved.

The collector reads only the selected candidate, its own script and the explicit local build inputs. It does not query installed Python distributions outside the candidate, execute code from the candidate or npm build inputs, open profile databases, inspect environment variables or contact license/provider servers. Attribution text can include authors' names and contact details as present in the dependency notices. Absolute workstation paths, lockfile download URLs and Git remotes are not copied into the report.

## Commands and retained evidence

Use an intact bundled-core candidate and its matching local npm lock, native bundle inputs and installed npm metadata. Output must be a **new** directory outside the candidate. Existing evidence is never overwritten. The default source is the repository containing the script.

```powershell
.venv/Scripts/python.exe scripts/distribution-audit.py collect --candidate .runtime/releases/native-setup-20261021-accepted --output .runtime/distribution-audits/my-new-audit
.venv/Scripts/python.exe scripts/distribution-audit.py verify --candidate .runtime/releases/native-setup-20261021-accepted --output .runtime/distribution-audits/my-new-audit
```

Verification rechecks the entire candidate with the existing validators, rederives all collected records/notices from their current inputs, and compares the exact expected output bytes and file set. A modified report cannot grant clearance. Changed candidates, dependency metadata, notices, native inputs, collectors, missing files and extra audit files refuse. Retain the matching collector and local inputs alongside the candidate for later verification; the sidecar alone does not authenticate a publisher or provide a hermetic rebuild. A partial interrupted collection remains for inspection; choose a new output directory rather than overwriting it.

Paths are local, canonical and unlinked. Observed evidence files reject hard links. Metadata, dependency counts and notice sizes have explicit bounds; recognized notices are decoded for the combined UTF-8 document, while individual copies retain their original bytes. Unsupported encoding or excessive content refuses instead of silently truncating. Missing recognized npm notice files are visible review gaps, not an invented license text. README-only, unusual filename/location and vendored-license attribution need explicit follow-up.

## Local acceptance

The accepted audit is `.runtime/distribution-audits/native-setup-20261021-final`, bound to the existing 2,990-file native Setup candidate. It contains **143 component records and 147 notice evidence files**. The combined notice document is about 20 MiB, primarily the retained Chromium notice. It remains local rather than adding that runtime text to source documentation. [Sanitized execution evidence](qa/distribution-audit-verification.json).

Six npm records lack recognized local notice files: two separately installed `@mediapipe/tasks-vision` records, `@react-three/fiber`, `draco3d`, `maath` and `stats-gl`. The report retains their versions, metadata paths and declared licenses. This finding means evidence is missing under the collector's recognition rules; it does not establish an absence of licensing or a redistribution decision. No missing text was fetched or substituted.

The locally retained CPython 3.12.10 and Electron 44.7.0 versions are observations, not a current support/security recommendation. This milestone does not update dependencies or reuse historical version labels as proof of safety. Security advisories, supported update targets, binary provenance and all transitive/native components still need a deliberate baseline review before distribution.

**79 focused checks pass**, including 31 audit checks, with scoped Ruff. Focused tests cover evidence preservation, exact revalidation, forged clearance claims, altered/missing/extra files, source/lock/version mismatches, missing declared Python licenses, path escapes, existing-output preservation, shared-file refusal, size limits and refusal before output on candidate failure. Actual collection and a separate CLI verification run against the retained real candidate pass. Fixture tests do not establish signing or legal clearance.

## Signing and distribution acceptance contract

The release readiness gate `distribution-signing-licenses` remains pending. There is no configured INARA certificate, verified legal publisher identity, timestamp service, signing tool or approved distribution channel. Upstream runtime signatures, if present, do not authenticate INARA's scripts or a locally assembled package. This tool does not inspect or certify those signatures. No private key, certificate password or signing credential belongs in source, audit JSON or command-line arguments.

Before a public release, record the owner-approved publisher identity and certificate/key custodian, signing and recovery process, protected signing environment and independently trusted verification policy. The final distribution design must authenticate the **whole payload and its manifest**, including scripts/XAML/resources, rather than only an unchanged upstream executable. Define trusted publisher/key rotation and revocation handling before a signed updater can accept replacement payloads. Missing identity, missing/untrusted/expired evidence and changed payloads must refuse; development hashes and self-asserted report flags cannot authorize release or updates.

Signing changes binary hashes. The release pipeline must retain the reviewed build inputs/notices, sign the intended final artifacts under the owned identity, regenerate the final payload inventory/provenance for those exact signed bytes, and independently verify signatures and inventory. Windows acceptance must exercise the actual distributed entry points and payload verification. Do not label this unsigned directory pilot as signed MSI/EXE, a reproducible build or a completed updater.

## Next implementations

1. **Exact renderer provenance and asset inventory: implemented.** See [the new milestone](RENDERER_PROVENANCE.md) for main/worker graphs, copy origins and package/audit bindings. Ownership and missing notice decisions remain pending. Next is their digest-bound review ledger; downloads/configuration remain deferred.
2. **Distribution baseline and owner decisions:** review supported dependency/security baselines, nested/native dependencies and runtime source origins; record retained license obligations/notices and explicit redistribution decisions for application assets and bundled components. Preserve models/optional worker tooling as separate opt-in inventories.
3. **Owned signing and authenticated packaging:** implement the reviewed identity/trust policy and verify final signed artifacts. Actual certificate provisioning and public distribution remain dependent on owner configuration.
4. **Clean Windows acceptance:** on a genuinely clean account/machine, verify download/extraction or installer trust, install, tray launch/full workspace, version rollback, supported backup/recovery, busy refusal, interrupted copy/removal, software-only uninstall and separately confirmed data erasure. Record offline startup, Defender/SmartScreen observations and unsigned/signed distinctions without disabling protection.
5. **Signed opt-in update acceptance:** authenticate exact replacement payloads before installation, reject wrong publisher/tampering/replay/downgrade according to reviewed policy, preserve data and recover from interrupted updates. Broader recovery adapters and cross-version data compatibility must be explicitly tested.

Android build/device acceptance, actual SIM/personal WhatsApp call control and duplex audio, configured creative providers and Legion sustained-use acceptance remain separate. WhatsApp text/outgoing actions stay off. The real-game benchmark remains deferred.
