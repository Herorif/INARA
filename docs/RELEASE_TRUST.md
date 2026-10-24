# Publisher/reviewer trust and detached payload attestations

Implemented 22 October 2026. `scripts/release-trust.py` prepares unsigned signing messages and verifies externally produced detached attestations for the exact candidate, audit and review ledger. It uses the existing core `cryptography` dependency; no package, model, SDK or signing tool was downloaded. It has **no private-key import, generation, signing, certificate-store or network CLI**.

The checked-in [RELEASE_TRUST_POLICY.json](RELEASE_TRUST_POLICY.json) is deliberately disabled: no publisher identity and zero enrolled keys. No INARA production signing identity was created or inferred. Policy inspection succeeds, while preparation/verification with that disabled policy refuses before writing a signing request or validating a candidate as trusted.

## External trust policy

Every operation requires the explicit policy file and an independently supplied SHA-256 pin. Preparation/verification reject a policy carried inside the candidate, audit or ledger. Nothing loads an embedded public key, follows a key URL, scans the Windows certificate store, accepts an envelope's chosen identity or updates trust automatically.

The pin must come from an owner-controlled, independently trusted enrollment process. Computing a pin from an untrusted downloaded policy does not establish trust. `policy_sequence` is metadata under that pin; this tool has no automatic policy update protocol. Key rotation/revocation requires an explicitly enrolled replacement policy and new trusted pin. Retain and protect the verifier/dependencies separately from unverified payloads; replacing the verifier itself defeats its checks.

Policies have explicit `disabled`, `fixture` or `production` modes, a publisher label, release channel, minimum release sequence, independent publisher/reviewer thresholds and bounded public-key records. Each key has one role, a raw-public-key SHA-256 identifier, declared identity, active/revoked state and UTC validity window. Duplicate fingerprints cannot satisfy two roles or count twice. Distinct keys do not prove distinct human operators or a legal company identity; those enrollment/custody decisions remain owner work.

Fixture preparation/verification requires the explicit `--fixture` option. A fixture statement cannot satisfy a production policy, and changing its mode or other signed fields invalidates its signature/bindings. Production preparation and verification additionally require every current ledger subject to be recorded as approved. This does not turn the underlying unsigned historical reviewer labels into authenticated identities: the attestation reviewer key endorses the **exact whole ledger snapshot**, not each named historical author.

## Whole-payload statement and signature checks

The signed statement binds all of:

- Exact candidate manifest SHA-256 and its full file-inventory digest.
- Exact audit report SHA-256.
- Exact ledger bytes and hash-chain head, whose attachment bytes are reverified through the existing ledger validator.
- External policy digest, publisher label, channel, release sequence, fixture/production purpose and bounded UTC issue/expiry window.

The verifier independently rechecks the package's file inventory, renderer main/worker output provenance, audit notices and ledger history/evidence before accepting their bindings. This covers scripts, XAML, resources, runtime binaries and other inventoried files; signing an unchanged upstream executable alone would not cover the assembled payload.

The signature input is a fixed versioned domain separator followed by the existing deterministic sorted ASCII JSON encoding. Detached Ed25519 verification uses the pinned key bytes through [cryptography's documented verifier](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/). Envelope/statement/policy schemas reject unknown and duplicate JSON fields. Canonical base64, key/signature lengths, integer fields, timestamps and inventory identities are checked. Extra untrusted, duplicate, revoked or invalid signatures refuse even if another subset might meet thresholds.

Verification requires the caller's expected sequence, which must meet the policy minimum. The envelope cannot choose its own accepted older version. Rechecking the same statement is intentionally idempotent: there is no installer effect or persistent consumed-sequence database. This is **not an implemented updater replay/downgrade state machine**. A future installer/updater must protect its own monotonic acceptance state and define intentional rollback separately.

Issue/expiry values are signed claims checked against the verifier's current UTC clock, not a trusted timestamp authority. Future, expired, nonpositive and greater-than-24-hour statement windows refuse. Signing preparation requires enough active keys whose validity covers the complete requested window. Verification checks key state and validity again. No online revocation/time service runs; a trustworthy clock and current external policy remain prerequisites. Production ownership, cryptographic identity enrollment and durable rollback/freshness acceptance are not supplied by these checks alone.

Successful verification reports key and whole-payload binding verification, with explicit fixture status. It **always** returns `release_authorized: false`, `legal_identity_established: false`, `authenticode_verified: false` and `clean_machine_acceptance: false`. It does not change installation metadata, select a version, launch code, publish artifacts or update release gates. The existing unsigned package format remains unsigned.

## Commands and signing boundary

```powershell
# Use the independently retained pin; do not derive production trust from an untrusted payload.
.venv/Scripts/python.exe scripts/release-trust.py policy --policy C:/trusted/release-policy.json --expected-policy '<trusted policy SHA-256>'
.venv/Scripts/python.exe scripts/release-trust.py prepare --candidate C:/candidate --audit C:/audit --ledger C:/reviewed-ledger --policy C:/trusted/release-policy.json --expected-policy '<trusted policy SHA-256>' --sequence 1 --output C:/new-detached-request
.venv/Scripts/python.exe scripts/release-trust.py verify --candidate C:/candidate --audit C:/audit --ledger C:/reviewed-ledger --policy C:/trusted/release-policy.json --expected-policy '<trusted policy SHA-256>' --sequence 1 --envelope C:/detached-attestation.json
```

The default request validity is 60 minutes; `--valid-minutes` accepts 1–1,440. Preparation writes only a **new** detached directory containing `statement.json` and the exact public `signing-message.bin`. Existing requests and candidate/audit/ledger locations are never overwritten. Keep request/envelope files separate from those bound immutable inputs. Interruption can leave a partial request directory; retain it and choose a new destination. No signing operation is retried or executed by preparation.

An external owned signer must sign the exact message bytes, with separate publisher and reviewer keys, and produce an envelope containing `format: 1`, `kind: inara-detached-attestation`, the exact statement, and signature records with only `key_id` and canonical base64 `signature`. The envelope cannot enroll its own keys. This source milestone intentionally supplies no production signer/key storage integration.

For Windows distribution, detached attestations and Authenticode are separate requirements. Actual Windows signing/timestamp validation remains unimplemented/unconfigured; see Microsoft's [SignTool verification](https://learn.microsoft.com/windows/win32/seccrypto/signtool) and [Authenticode timestamping](https://learn.microsoft.com/en-us/windows/win32/seccrypto/time-stamping-authenticode-signatures). When binary signatures change bytes, sign the intended binaries first, regenerate the final package/renderer-compatible inventory and audit/review bindings, then attest those **final bytes**. Current package controls still require their documented unsigned pilot format; do not silently relabel it as a signed installer. No certificate/container password or private key belongs in these JSON files, source or CLI arguments.

## Acceptance

**90 focused Python checks pass**, including 40 trust checks, with scoped Ruff. Ephemeral test keys cover role separation, wrong pins, changed inventories/audits/ledgers, mode/channel/identity mismatch, replay floors, expired/future statements and keys, revocation, duplicate/missing/unknown keys, malformed schemas/encodings, explicit fixture opt-in, incomplete production reviews and non-overwriting preparation. Synthetic signing occurs only in tests/QA, never through the release CLI.

`scripts/verify-release-trust.py` uses the retained real renderer-provenance candidate, audit and 85-pending-subject ledger with explicitly labeled ephemeral fixture keys held only in memory. Only fixture **public** keys, statements and signatures are retained under `.runtime/release-trust-qa/20261022-accepted`; private keys are not serialized. The real production policy remains disabled and all 85 real review decisions remain pending. [Sanitized acceptance evidence](qa/release-trust-verification.json) records real-payload verification separately from production trust. No provider, phone, startup, profile or installed version was changed.

## Next implementation

[The authenticated package and guarded install boundary](SIGNED_PACKAGE.md) are now implemented with purpose-separated fixture verification, production-only review/apply and interrupted-copy admission checks. Next is Windows signing/verification adapter and trusted-controller distribution preparation, including authenticated admission receipts and a verified-launch contract. The existing unsigned pilot remains separate; candidate-provided validators never establish initial trust.

Actual publisher/reviewer enrollment and custody, authoritative evidence decisions, Windows signing/timestamp verification, trusted bootstrap delivery, clean-machine acceptance and durable signed-update state remain separate gates requiring real evidence. Broader recovery adapters, Android toolchain/device checks, physical SIM/personal WhatsApp duplex media and real providers remain open. WhatsApp text/outgoing actions stay off and the real-game benchmark remains deferred.
