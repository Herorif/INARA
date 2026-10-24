# Authenticated package format and guarded installation

Implemented 22 October 2026. `scripts/signed-package.py` introduces an authenticated container and an external verification/admission entry. Its verifier and slot manager come from the trusted control checkout, never from the supplied payload. Real production identity configuration remains disabled; real package installation has not been authorized or exercised by this milestone.

## Container and signing boundary

An authenticated container has these file roots:

```text
package-manifest.json
attestation.json
payload/    exact desktop pilot, including its original desktop-pilot.json
audit/      exact notice audit and content-addressed notice copies
ledger/     exact review ledger and historical attachments
```

`package-manifest.json` has a distinct `inara-authenticated-package` format, fixture/production purpose, pinned policy digest, publisher/channel/sequence, bounded UTC validity and explicit path/size/SHA-256 records for every file under those three roots. It also binds the raw desktop manifest, audit report and ledger digests. The wrapper and attestation are the only two files outside that inventory. Request files, keys, helper executables and unknown extras are not accepted inside the final container. File content/path inventories do not authenticate Windows ACLs, file timestamps or other filesystem metadata.

Preparation uses the existing trusted source/audit/ledger validators, requires complete recorded production reviews for production purpose, and refuses disabled identity or implicit fixture mode before copying package inputs. The copies are rehashed and the copied pilot/audit/ledger are validated before the manifest is committed. It writes only **new** local assembly and separate signing-request directories. It does not install, register, select or launch a version. A prepared container without an attestation cannot verify, including in explicit fixture mode.

The signing request contains the exact public statement and message bytes. A versioned package-specific domain separator prevents signatures for the earlier standalone distribution statement from being interchangeable. External signing must cover the exact manifest digest and trust context with distinct enrolled publisher/reviewer keys. No production signer, private-key loader or certificate-store integration is provided. The QA helper signs only with ephemeral in-memory fixture keys; none are enrolled into the disabled production policy.

## Independent verification

Verification requires an external policy and independently retained policy pin, expected sequence and trusted controller/runtime. It refuses a trust policy supplied inside the container. Policy validation, signature thresholds, purpose/publisher/channel/sequence, issue/expiry and active key windows are checked **before walking and validating the payload**. Manifest/envelope metadata is bounded and schema-checked as inert data. Fixture verification requires `--fixture`; neither installation command accepts that flag.

After signature verification, the controller checks exact file closure, local canonical unlinked/unshared paths, duplicates, sizes and hashes. It validates the pilot/runtime/renderer inventory with its own validator, reproduces the bundled audit notice artifacts from the bundled data, reconstructs the complete expected review-subject inventory, and replays the ledger chain and evidence. It refuses missing subjects, changed evidence, unregistered files and incomplete production approvals. Inspection does not need the original renderer source checkout/build inputs: it checks the authenticated, bundled evidence as data rather than recollecting provenance or executing package-supplied code. It does not independently establish that the attesters' licensing/security judgments are true.

This is a detached cryptographic package format around a retained unsigned directory pilot. It does not change the pilot's `signed: false` marker or claim Windows Authenticode/SmartScreen acceptance. Attesters endorse the exact bytes, audit and ledger; historical named reviewers are not individually authenticated by that endorsement. Legal identity, authoritative evidence adequacy, Windows signing/timestamps and clean-machine acceptance remain separate. All successful verifier responses continue to report `release_authorized: false`.

Limits are 19,998 inventory files plus two wrapper/attestation files, 512 MiB per file, 2 GiB inventory bytes, 8 MiB manifest metadata and bounded attestation/ledger/notice schemas inherited from the earlier milestones. Assemblies interrupted before completion remain retained and unverifiable; choose new assembly/request locations instead of deleting or repairing arbitrary files automatically.

## Reviewed install and interrupted-copy recovery

`review-install` verifies the whole container in **production mode only**, validates the intended managed/new root and returns a review digest binding the manifest/attestation, policy, sequence, destination, current installation metadata and install/resume choice. It does not create a target folder. `install` redoes those checks, requires the exact review digest, then delegates to the external trusted slot manager. Missing signatures, wrong pins/publishers, stale sequences, incomplete approvals and fixture packages refuse before installation copies. Unknown existing directories are not adopted.

The slot manager now has optional internal admission/state hooks; the legacy unsigned CLI defaults are unchanged. Authenticated admission rechecks installation state **under its OS manager lock**, checks source bytes against the signed in-memory inventory before copy, then checks the pending copy, source and final target before registration. Rebuilding a different unsigned desktop manifest after signature verification cannot substitute a different authorized payload. Expired authorization or a changed external policy pin refuses. It never selects, migrates, launches, downloads or removes a version/profile.

An interrupted copy remains unregistered under the existing slot transaction rules. Use **both** review and apply with `--resume` to verify and recover the exact signed slot. Recovery checks pending/final bytes against the signed inventory and rechecks state under the same manager lock. It refuses partial, changed or ambiguous copies; it does not blindly replay a failed install or delete the evidence. If a one-hour package authorization has expired, a fresh externally signed container and fresh review are required. The original version/data and selection remain retained.

The admission result identifies the manifest and installed slot. This does **not** convert the underlying installation metadata into a permanently authenticated installation, add an independently signed admission receipt, or enforce trust on every future launch. Existing unsigned Setup/CLI management remains an explicitly separate owner-operated pilot path; it can manage directory pilot slots under its existing rules. Selecting/launching with that path is not a signed-flow authorization. Do not call the new container globally enforced signed installation, an authenticated resident launcher or an updater. Local privileged edits after admission and trusted-controller replacement are outside this admission snapshot; verified launch/receipt/bootstrap delivery and durable update state need further work.

## Commands

Use an independently trusted checkout/runtime and external owner-enrolled policy. These examples do not configure an identity; the checked-in disabled policy refuses production operations.

```powershell
# Packaging assembly, not installation. Both outputs must be new and separate.
.venv/Scripts/python.exe scripts/signed-package.py prepare --candidate C:/candidate --audit C:/audit --ledger C:/reviewed-ledger --policy C:/trusted/policy.json --expected-policy '<trusted pin>' --sequence 1 --output C:/new-container --request-output C:/new-signing-request
# External owned publisher/reviewer signing produces only attestation.json in the container.
.venv/Scripts/python.exe scripts/signed-package.py verify --package C:/new-container --policy C:/trusted/policy.json --expected-policy '<trusted pin>' --sequence 1
.venv/Scripts/python.exe scripts/signed-package.py review-install --package C:/new-container --policy C:/trusted/policy.json --expected-policy '<trusted pin>' --sequence 1 --root C:/managed-inara
.venv/Scripts/python.exe scripts/signed-package.py install --package C:/new-container --policy C:/trusted/policy.json --expected-policy '<trusted pin>' --sequence 1 --root C:/managed-inara --expected-review '<review_sha256>'
# For a genuinely interrupted owned copy, add --resume to BOTH review-install and install.
```

Copying a container/audit/ledger can include attribution text, reviewer labels and historical evidence attachments. Review that material before any later distribution; no publishing occurs here. Never derive a production trust pin from an untrusted received policy or execute a payload's setup/Python/validator to establish its initial trust.

## Acceptance and next implementation

**183 focused Python checks pass**, including 27 authenticated-package checks, with scoped Ruff. Synthetic production-purpose test identities and inert test payloads exercise review/apply, no selection/launch, replay refusal, state changes under lock, unsigned-payload substitution after verification and interrupted-copy recovery. Other tests cover path traversal/duplicates, missing/changed/extra/shared files, signatures, time/sequence/policy and pending-ledger promotion. No synthetic approval is a real ownership or release decision. Existing installation, removal-control, backup, recovery activation and trust checks remain passing with the default optional hooks.

Actual acceptance at `.runtime/signed-package-qa/20261022-accepted` assembles and verifies a fixture container from the retained real candidate, audit and pending ledger: **3,067 inventory files plus two container/attestation files**, with 85 review subjects still pending. Missing attestation, fixture installation and disabled production policy all refuse. No target installation folder is created, candidate code is not executed, original ledger bytes remain unchanged and no private key is persisted. [Sanitized evidence](qa/signed-package-verification.json). This is development-host fixture acceptance; no real production identity or Windows-signed release was created.

The next source milestone is now implemented in [Windows verification and trusted controller preparation](WINDOWS_CONTROLLER.md): native verification, final-byte portable controller/bootstrap, retained signature/audit/ledger capsules before registration and a read-only launch contract. The earlier description above records the original admission-only milestone; retained evidence now supports source-independent revalidation, but local root metadata remains unsigned and there is still no guarded resident launcher or durable admission renewal. Real certificate provisioning, authoritative review decisions, owned bootstrap delivery and clean-machine acceptance remain pending. Durable admission/renewal, process-lifetime launch and signed-update sequence/rollback state follow.

Preserve current recovery compatibility boundaries, Android build/device gates and physical SIM/personal WhatsApp control/duplex-media proof. WhatsApp text/outgoing actions stay off, providers/toolchains/models remain unconfigured, and the real-game benchmark remains deferred.
