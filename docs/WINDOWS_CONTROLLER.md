# Windows verification and trusted controller preparation

Implemented 22 October 2026. This milestone adds a native Windows signature adapter, a separately inventoried portable controller, retained package authorization evidence and a read-only launch contract. It does not provision an identity, install a production package or start the assistant. Production release and Windows signing policies remain disabled.

## Native Windows verification

`scripts/windows-signature.py` calls the system-directory `wintrust.dll` directly. It requests Generic Verify V2, no UI, whole-chain revocation with the root excluded, cache-only URL retrieval and MD2/MD4 refusal. It always closes Windows trust state, including failed verification and failed certificate extraction. There is no online retry, certificate enrollment, trust-store editing or signing command. These flags follow the [Windows trust-data contract](https://learn.microsoft.com/en-us/windows/win32/api/wintrust/ns-wintrust-wintrust_data).

Only a zero Windows trust status can pass. Certificate fingerprints come from the actual provider's first signer chain and recognized first countersigner chain through [WTHelperGetProvSignerFromChain](https://learn.microsoft.com/en-us/windows/win32/api/wintrust/nf-wintrust-wthelpergetprovsignerfromchain), rather than any arbitrary certificate found in a signature container. SHA-256 covers each leaf certificate's complete DER bytes. Missing/unrecognized timestamp evidence, signer errors and cache-dependent trust failures refuse; no timestamp is invented from file dates. Native provider compatibility beyond the exercised host remains unverified. This is Windows' reported chain/timestamp result, not an independent timestamp parser or security-baseline review.

An externally pinned `inara-windows-signing-policy` contains `format: 1`, `mode: production` and an exact `targets` list. Each target names a relative `.exe`, `.dll` or `.pyd` path, `signer_sha256` and `timestamp_sha256`. Every native file in the checked directory must be covered, with no missing, extra or duplicate target. Certificate rotation requires a deliberately reviewed replacement policy/pin. Vendored binaries may need their own independently verified publisher certificates; do not enroll an upstream certificate as INARA's identity. Unsigned bundled native dependencies will refuse until their ownership, redistribution and signing decisions are resolved.

The checked-in [Windows policy](WINDOWS_SIGNING_POLICY.json) is disabled with zero targets. `probe` is diagnostic and can report failure without a nonzero process exit; `check` is the enforcement operation and exits unsuccessfully on refusal. Neither result grants release authorization. Hashes before/after each probe detect ordinary file changes; they do not defend against a privileged concurrent writer restoring the same bytes. Cache-only flags were exercised; no packet-capture/no-network acceptance is claimed.

## Controller assembly and bootstrap

`scripts/controller-package.py` copies the already verified isolated core Python runtime and a finite set of trusted controller/validator scripts, the core dependency lock, disabled public policies and project license into a **new** output directory. It includes no user profiles, keys, models, renderer, node toolchain or candidate application code. The controller is consequently smaller in scope than a desktop package, although it still carries all 41 core Python dependencies. Runtime minimization is future work.

The final `controller-manifest.json` records every file's path, size and SHA-256. Assembly verifies original and copied bytes and the isolated runtime. Verification requires an independently retained manifest pin, exact file closure, safe local unshared paths and the runtime dependency lock. This establishes byte identity under that external pin; a self-reported digest alone is not publisher authentication. The current dirty trusted checkout is the source of these scripts; no clean-commit/reproducible-build claim is made.

`scripts/open-trusted-controller.ps1` must itself arrive through an independently trusted route. It checks the external manifest pin **before starting bundled Python**, rejects missing/extra/linked/shared/changed files, then runs only the fixed controller entry with `-I -B` and an argument array. It holds read handles denying file writes/deletion through the child lifetime. It never evaluates an argument as shell code, adds startup settings or downloads anything. This is a source-delivered bootstrap, not a signed installer or self-authenticating bundle; trusting a bootstrap and pin obtained from an untrusted bundle would bypass its premise. Privileged concurrent filesystem replacement is outside this development-host acceptance.

Controller commands are finite: `policy-status`, production package `verify`, `review-install`, `install`, `launch-check`, `windows-probe` and `windows-check`. There is no fixture-install switch, package preparation, arbitrary module execution or resident launch command. `policy-status` only describes the bundled policies; operational commands require explicit external policy paths and pins. The controller cannot authorize itself through that diagnostic command.

Signing/timestamping changes file bytes. Resolve native signatures first, regenerate affected runtime/native/desktop manifests and audit/review bindings, then assemble attestations and controller inventory from the **final** bytes. Any later signing or modification invalidates those inventories. This controller is a separate distribution artifact: the older desktop candidate's 85-subject audit does not automatically clear controller redistribution, its runtime notices or its bootstrap.

## Retained admission evidence and launch contract

Authenticated install/recovery now uses an optional slot-manager hook under the manager lease, after final payload checking and **before registration**. It retains:

```text
admissions/<slot>/package-manifest.json
admissions/<slot>/attestation.json
admissions/<slot>/audit/...
admissions/<slot>/ledger/...
admissions/<slot>.json                  local root/installation binding
versions/<slot>/...                     single installed payload
```

The capsule retains the externally signed authorization and review evidence, not another executable copy. The local binding records canonical root, installation ID, slot, policy, sequence and reviewed raw manifest/envelope hashes. It is **local metadata**, not an independently signed owner/root receipt. The external package signatures authenticate payload/evidence bytes; editable installation metadata is never described as cryptographically authenticated. The source package may subsequently be unavailable without preventing verification of the retained evidence.

The copied capsule is verified against the installed payload and exact reviewed authorization before registration. Receipt failure leaves the version unregistered. Recovery may reuse only a complete identical capsule and binding; a partial/conflicting capsule refuses and is retained for inspection, without silent deletion or repair. Existing removal operations leave admission evidence retained; this milestone does not add receipt erasure or auto-renewal.

`launch-check` verifies the selected registered slot, external release policy, live signature/key windows and sequence, exact installed bytes and audit/ledger evidence, local root binding and current profile ownership. Signatures are checked before walking payload files. The controller additionally requires the external Windows policy/pin and executes native checks while the manager lease is held. It reports `launched: false`, `launch_authorized: false` and `installation_metadata_signed: false`, even after successful checks. This is a read-only prerequisite contract, **not an execution permit usable later**. A future launcher must recheck trust and preserve the lock across the actual resident lifetime.

Original one-hour package authorization remains in force: expired evidence refuses rather than silently acquiring indefinite installation trust. A durable, independently authorized admission/renewal policy and monotonic update state are still needed. There is no global enforcement across the legacy unsigned Setup/CLI; those owner-operated paths remain separate and unchanged by default. Fixture packages still cannot install or enter this launch contract. Actual owned certificate, production package, clean-machine and live resident acceptance remain pending.

## Commands and acceptance

From the independently trusted checkout, using existing local runtime inputs:

```powershell
.venv/Scripts/python.exe scripts/controller-package.py stage --runtime .runtime/python-runtimes/core-20261021-v2 --directory C:/new-controller
# Retain the resulting manifest pin through an independently trusted route.
powershell.exe -NoProfile -File scripts/open-trusted-controller.ps1 -Directory C:/new-controller -ExpectedManifest '<external controller pin>' policy-status
.venv/Scripts/python.exe scripts/windows-signature.py probe --file C:/new-controller/runtime/python.exe
# Production configuration is deliberately deferred; these placeholders refuse.
powershell.exe -NoProfile -File scripts/open-trusted-controller.ps1 -Directory C:/new-controller -ExpectedManifest '<external controller pin>' launch-check --root C:/managed-inara --policy C:/trusted/release.json --expected-policy '<release pin>' --sequence 1 --windows-policy C:/trusted/windows.json --expected-windows-policy '<Windows pin>'
```

Acceptance covers 33 new controller/receipt/native checks and 183 existing focused package/trust/installation/recovery checks. It includes synthetic production-purpose identities and inert payloads, interrupted receipts/registration, source-independent verification, expiry/tampering and bootstrap refusal before runtime execution. Synthetic review assertions never approve real ownership or legal decisions. Scoped Ruff passes. [Sanitized execution evidence](qa/controller-verification.json) records actual portable assembly, external-bootstrap policy status, wrong-pin refusal, native unsigned-input refusal and the upstream Python probe on this development host. Upstream certificate observations are not enrolled production identities. No production installation, profile, phone/account, provider, certificate store or startup setting is configured.

The next source milestone is now implemented in [renewable admission and guarded launch](ADMISSION_LAUNCH.md): separate signed renewal, externally pinned grant history and a process-lifetime guarded launcher. This document records the earlier read-only milestone; its original `launch-check` contract remains separate. Protected update/trust state, review-bound policy rotation, transactional signed update/rollback, controller-specific provenance/notices and owned signed-bootstrap delivery/clean-machine acceptance remain pending. Actual reviewer decisions, owned certificates and physical devices remain explicit gates. Android/SIM/personal WhatsApp control and duplex-media proof remain separate; WhatsApp text/outgoing actions stay off and the real-game benchmark stays deferred.
