# Signing custody and controller delivery preparation

Step 5 now provides a separate [source-neutral receiving path and reviewed receiving copy](CONTROLLER_RECEIVING.md). Current provenance includes seven external inputs and **52 pending controller subjects**. The Step 4 evidence/counts below remain historical. Producer-side verification still requires its matching source snapshot; the receiver explicitly relies on external signatures endorsing the producer evidence.

Step 4 adds offline preparation tools for public custody records, controller-specific review revisions and detached controller delivery statements. Production identity/certificate/key configuration, actual signing and delivery remain deferred. Both checked-in production policies stay disabled. No private key is generated, imported, signed with, scanned for or enrolled by these tools; they do not edit a certificate store or launch/install a payload.

These are **independently trusted checkout tools**, separate from the received controller. A verifier/dependency environment received from the same untrusted delivery cannot establish its own trust. The existing 2,681-file controller is unchanged; the provenance inventory now also includes the three external preparation tools. Its review scope grows from 48 to **51 pending subjects**. All original subjects remain pending, and all 85 desktop subjects remain separately pending.

## Public custody preparation

`scripts/signing-readiness.py draft --output <NEW directory>` writes only `enrollment.json` and public instructions. The template is a draft with no publisher, keys, policies, custody assignments or delivery channel selected. Keep credentials, private keys, PFX/PEM/key envelopes, profiles and tokens outside this bundle.

When configuration is explicitly resumed, an owner can supply independently pinned public release/Windows policies and public evidence for:

- Every active Ed25519 key's declared operator, opaque custody/recovery/revocation references and recovery-drill assertion.
- Independent publisher/reviewer operator declarations and an explicit independence-review assertion.
- Windows signing/timestamp/recovery/revocation responsibility and a recovery-drill assertion.
- A separately trusted bootstrap/verifier delivery channel and verification procedure.

The bundle uses exact fields, bounded public labels/references, nonfuture review dates, referenced UTF-8 evidence hashes and exact file closure. Evidence lives only at `evidence/<sha256>.txt`. Private-key fields, key envelopes, extra files, changed evidence, duplicate key records, incomplete key coverage, overlapping role operators and mismatched policy pins refuse or block readiness. Policies must remain external to the custody bundle. Assessment never writes them or switches the draft to reviewed.

These are **recorded assertions**, not verified human/legal identities, independent hardware custody or proof that a recovery drill occurred. Evidence adequacy and real operator/key/certificate custody require owner review. Distinct operator labels do not prove distinct people. A pinned, reviewed public plan is a preparation prerequisite; it is not key enrollment or release authorization.

```text
signing-readiness.py draft --output <NEW public custody directory>
signing-readiness.py assess --directory <public custody directory>
  --expected-enrollment <independently retained enrollment.json hash>
  --policy <external public release policy> --expected-policy <independent pin>
  --windows-policy <external Windows policy> --expected-windows-policy <independent pin>
```

Run with the existing trusted Python environment. Assessment emits blockers for the current disabled/draft setup, without trying a signer, certificate service or provider. Computing a hash from an untrusted received plan/policy does not establish its authority.

## Controller review revisions

`scripts/controller-review.py` turns the controller's reverified provenance checklist into a **separate ledger**, initially with every subject pending and no decisions. It does not convert the desktop ledger or treat the provenance checklist as approvals. The existing desktop review tool and its 85-subject ledger bindings are unchanged.

Each revision binds the external controller pin, exact provenance inventory, review-tool bytes, subject hashes, prior ledger bytes/head, request/evidence bytes and a new destination. Review shows the exact decision; apply rederives that review before writing a new immutable revision. Existing evidence/history remains retained. A complete ledger marker is written last. Incomplete/changed revisions, history reordering, stale reviews, missing required evidence kinds, changed sources, extra files and overwrites refuse. Delivery-input subjects require delivery evidence as well as origin/license/obligation evidence.

```text
controller-review.py create --controller <controller> --expected-manifest <independent pin>
  --evidence <verified controller provenance> --output <NEW ledger>
controller-review.py status <same controller/provenance inputs> --ledger <ledger>
controller-review.py review <same inputs> --ledger <ledger>
  --request <explicit public decision JSON> --output <NEW revision>
controller-review.py apply <same> --expected-review <exact review digest>
```

Decision fields are `subject_id`, `subject_sha256`, `status` (`pending`, `approved`, `rejected`), `reviewer`, `rationale`, `reviewed_on` and `evidence`. Status exposes the exact subject hashes and required evidence kinds. Request evidence entries contain `kind`, an explicit absolute public text `file`, and `source` (a public HTTPS reference or `local-review` where permitted). Only public text file extensions are accepted. Ledger evidence is content-addressed and reverified. No source URL is fetched.

Approval is a reviewer assertion; ledger completeness does not authenticate the reviewer, establish redistribution clearance or authorize release. A later detached delivery reviewer key endorses the exact complete ledger snapshot, not each historical named author's identity. **No actual review decision was entered for Step 4.**

## Detached delivery statements

`scripts/controller-delivery.py readiness` checks the four separate input directories (controller, provenance, ledger, public custody), independent external public-policy pins, custody assertions and controller review completeness. Native Windows signature enforcement runs only after these public prerequisites pass. It uses the existing cache-only native policy checker; missing/incorrect native coverage, signer/timestamp results or trust failures block request creation. No online fallback runs.

`prepare` writes a new unsigned `statement.json` and exact `signing-message.bin` only when those prerequisites pass. The domain is `INARA:controller-delivery:v1`, separate from package, update, lifecycle and grant signatures. A statement binds:

- Exact controller manifest pin and bootstrap script bytes.
- Complete provenance, ledger and custody-bundle inventories, plus ledger head and custody-plan pin.
- Both external policy pins, publisher/channel, explicit expected sequence and a window of at most one hour.

An external owned publisher/reviewer signing process supplies an envelope containing `statement` and `signatures` (`key_id`, canonical base64 `signature`). This code has no signer adapter, private-key loader, key URL or fixture-verification CLI switch. Preparation requires sufficient active enrolled keys covering the complete requested window. It never approves pending reviews or changes a custody plan to make a request possible.

`verify` requires the same independent expectations and explicit sequence. It verifies purpose, policy/channel/window/sequence and role signatures **before** controller inventory/provenance/native validation. It then rederives the complete controller review/provenance/custody bindings, enforces native trust and rechecks signatures and evidence/file snapshots for drift. Missing/extra/unknown/duplicate/revoked signatures refuse through the shared strict role verifier. Fixture policies cannot satisfy production delivery trust.

```text
Common arguments:
  --controller <controller> --expected-manifest <independent controller pin>
  --evidence <controller provenance> --ledger <controller-specific ledger>
  --enrollment <public custody bundle> --expected-enrollment <independent plan pin>
  --policy <external release policy> --expected-policy <independent pin>
  --windows-policy <external Windows policy> --expected-windows-policy <independent pin>

controller-delivery.py readiness <common>
controller-delivery.py prepare <common> --sequence <expected sequence>
  --minutes 30 --output <NEW unsigned request>
controller-delivery.py verify <common> --sequence <expected sequence>
  --envelope <external detached envelope>
```

All commands run from the trusted checkout with its existing Python. `--source` may identify a separately retained matching source snapshot; its files are read as evidence, never executed. This version requires that trusted matching source snapshot for provenance rederivation. The separate [source-neutral receiving verifier](CONTROLLER_RECEIVING.md) now handles signed evidence endorsement without the build checkout. Actual independently trusted delivery, owned signing and real installer/machine acceptance remain pending.

Successful verification remains read-only: `release_authorized`, `installed`, `launched`, `policy_enrolled` and `legal_identity_established` stay false. It is not a reusable execution permit. The existing independent bootstrap must recheck and lease the exact controller bytes before any later execution. The caller must retain trusted sequence/pin expectations; this adds no hardware counter, persistent delivery rollback state, online revocation/time service or policy auto-update. Statement times are checked against the local UTC clock, not a timestamp authority. Detached script binding is separate from an owned signed Windows installer and real trusted delivery acceptance.

## Retained local preparation and next steps

The public draft is `.runtime/signing-preparation/20261022`; the retained Step 4 controller provenance is `.runtime/controller-provenance/signing-preparation-20261022`; the retained Step 4 controller ledger is `.runtime/controller-reviews/signing-preparation-20261022`. That historical ledger retains **51 pending controller decisions**. The current Step 5 ledger contains **52 pending subjects**; all **85 desktop decisions** remain pending separately. Readiness is blocked, and real unsigned delivery-request preparation is expected to refuse without creating its destination.

[Verification evidence](qa/signing-delivery-verification.json) records source tests, actual artifact/provenance/ledger rederivation, disabled-policy/draft assessment and request refusal. Positive cryptographic tests use ephemeral in-memory test keys, synthetic public assertions, inert controller fixtures and injected native acceptance; they authorize no real release. The current controller bytes and existing installed/private data remain unchanged.

Next: resume real enrollment/custody decisions, authoritative license/source/security/delivery reviews, actual owned Windows signing/timestamps and trusted verifier/bootstrap delivery **when configuration is explicitly resumed**, then real signed-package/native-window and clean-machine lifecycle acceptance. Until then, those gates stay open. Preserve every other item in the [deferral register](DEFERRED_WORK.md): Android/toolchain downloads, physical phones/live-call audio, providers/models/devices, model cost/quality acceptance and Legion/game measurements. WhatsApp text/outgoing actions remain excluded.
