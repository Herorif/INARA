# Candidate-bound distribution review ledger

Implemented 22 October 2026. `scripts/distribution-review.py` turns the verified candidate/audit inventory into explicit review subjects, records pending/approved/rejected reviewer assertions with attached evidence, and preserves every earlier revision. It runs only on demand and adds no runtime worker, UI server, provider, network call or installation setting.

## Review subjects and boundaries

Every operation first revalidates the exact candidate and matching distribution audit using the existing package, renderer and notice validators. The ledger base binds their manifest/report digests, the exact subject inventory, evidence requirements and review-tool digest. Old or different candidate/audit/tool inputs refuse; there is no automatic migration or cross-version carry-over of decisions.

The real initial ledger at `.runtime/distribution-reviews/renderer-provenance-20261022-accepted` has **85 pending subjects, zero approvals and zero rejections**:

| Category | Count | Evidence required for a recorded approval |
| --- | ---: | --- |
| Audited component | 75 | Origin, license and obligation review |
| Asset input | 5 | Origin, license and obligation review |
| Missing recognized notice | 2 | Origin and notice text |
| CPython/Electron baseline | 2 | Source origin, support and security review |
| Vendor/native coverage | 1 | Inventory, origin, license and obligation review |

The vendor/native subject explicitly covers the candidate inventory and remaining audit gaps. It is a review obligation, not proof that all embedded subcomponents have been discovered. The runtime subjects retain the observed versions without declaring them supported or secure. Missing evidence is not fetched, substituted or inferred from a package license field. Evidence-file recognition, asset provenance and actual redistribution decisions remain distinct.

Reviewer names, dates, rationales and source references are **reviewer assertions**. The tool checks their structure, exact targets and evidence bytes; it does not authenticate the reviewer, verify a referenced website or decide whether the evidence is authoritative or legally sufficient. This is an unsigned local ledger. A party able to rewrite all unsigned data and hashes can forge a consistent history; hashes alone are not authorship or tamper-proof storage. Preserve reviewed ledger digests externally and add authenticated review/publisher trust before relying on these records for distribution.

Even when every subject is recorded as approved, the tool returns `redistribution_cleared: false`, `publisher_authenticated: false` and `release_ready: false`. `recorded_reviews_complete` means only that each current recorded status is approved. No supported runtime route, installer, updater or release gate automatically consumes that value as authorization.

## Immutable revisions and exact review

`create` writes a new directory containing `ledger.json`, with all subjects pending. `status` independently verifies and replays the event chain, lists current statuses and prints the exact subject IDs/digests needed for a request.

`review` reads a bounded JSON request and explicit local text attachments, checks the subject/evidence requirements and returns an exact review digest. It creates no output. The digest binds the current ledger bytes/head, exact request bytes/path, normalized decision and attachment digests, and the new output location. The plan identifies the subject, previous status, requested decision and destination before any effect.

`apply` repeats all verification and requires that exact digest. Changed request/evidence/subject/destination/current ledger state refuses before creating output. A successful apply creates a **new directory**, copies all historical evidence by content digest and appends a hash-linked event. It never overwrites the previous ledger, candidate or audit. Changing an approved/rejected status back to pending remains an explicit recorded event with a reviewer and rationale; old assertions and attachments are retained.

Revisions may branch from the same verified parent; this is an immutable snapshot workflow, not a central concurrent approval database. There is no implicit latest revision, global lock or automatic branch merge. Choose the intended revision explicitly and retain its digest. Reusing an existing output refuses. An interrupted write leaves a partial new directory; without a complete valid `ledger.json` it cannot verify. The previous revision remains usable. Preserve the partial output and choose another new directory; there is no blind cleanup or replay.

## Commands

```powershell
$candidate = '.runtime/releases/renderer-provenance-20261021'
$audit = '.runtime/distribution-audits/renderer-provenance-20261021'
$ledger = '.runtime/distribution-reviews/renderer-provenance-20261022-accepted'
# For a fresh inventory, choose a NEW output:
.venv/Scripts/python.exe scripts/distribution-review.py create --candidate $candidate --audit $audit --output .runtime/distribution-reviews/my-new-inventory
.venv/Scripts/python.exe scripts/distribution-review.py status --candidate $candidate --audit $audit --ledger $ledger
# Prepare the request below using a subject ID/digest from status and actual reviewed evidence.
.venv/Scripts/python.exe scripts/distribution-review.py review --candidate $candidate --audit $audit --ledger $ledger --request C:/path/to/review-request.json --output .runtime/distribution-reviews/my-new-decision
# Inspect the returned plan and use its exact digest; this records an assertion, not release clearance.
.venv/Scripts/python.exe scripts/distribution-review.py apply --candidate $candidate --audit $audit --ledger $ledger --request C:/path/to/review-request.json --output .runtime/distribution-reviews/my-new-decision --expected-review '<review_sha256>'
```

Request shape (illustrative pending assertion; IDs and files must be real local reviewed inputs):

```json
{
  "subject_id": "<exact subject ID>",
  "subject_sha256": "<exact subject digest>",
  "status": "pending",
  "reviewer": "<reviewer's declared identity>",
  "rationale": "Authoritative origin and license evidence are still awaited.",
  "reviewed_on": "2026-10-22",
  "evidence": []
}
```

Approval attachments use `{"kind":"origin","file":"C:/path/to/source-evidence.txt","source":"https://official-source.example/path"}`. The reference is stored as supplied and **never fetched or automatically authenticated**. Origin/license/notice/support/security evidence requires a public HTTPS reference without credentials, query data or fragments. Obligation and inventory notes may use `local-review`. Approval requires all subject-specific evidence kinds. Rejected/pending assertions may omit attachments but still require a reviewer, rationale and valid declared review date. Supplying the right evidence kinds does not prove their truth or adequacy.

Only explicitly selected local, canonical, unlinked/unshared, nonempty UTF-8 text evidence is accepted. Requests/attachments refuse network paths; signing-key/container/database extensions are excluded. No profile or certificate store is scanned. Attachment paths stay in the local request; ledger events retain evidence digests/sizes/kinds/source references and content-addressed text copies, not absolute workstation paths. The review preview shows the concrete request/output paths locally. Evidence may contain author/contact details present in the selected text, so retain the ledger privately unless those contents are reviewed for distribution.

Limits: 2 MiB per attachment/request, 32 attachments per decision, 32 MiB of unique evidence per revision, 4,096 subjects/events and 8 MiB of ledger JSON. The commit marker is written last, individual files are created exclusively, and missing/extra/changed evidence, unexpected fields, invalid dates/statuses and changed/reordered event hashes refuse. Completed ledger snapshots are self-contained for their review history and attachments; verification still needs the matching candidate, audit, collector/build inputs and review tool.

## Acceptance and next implementation

**82 focused Python checks pass**, including 39 review-ledger tests, with scoped Ruff. Tests use clearly synthetic evidence/identities for approvals, rejections and resets. They verify retained earlier revisions, evidence requirements, stale exact reviews, changed targets/destinations, forged release fields, audit failure, replay/history tampering, sensitive/network inputs, shared files, interrupted commits and refusal to grant release authorization even after all synthetic approvals.

Actual creation and separate CLI status verification use the unchanged 2,993-file renderer-provenance candidate and its 75-component/82-notice audit. All **85 real subjects remain pending**. [Sanitized execution evidence](qa/distribution-review-verification.json). No real ownership/license/security decision, dependency update, evidence download, signing, profile adoption, provider configuration or phone action occurred.

[Publisher/reviewer trust and detached whole-payload attestation preparation](RELEASE_TRUST.md) is now implemented with explicit fixture separation and disabled production identity. Next is an independently trusted verify-before-install boundary and signed-package format. Actual certificate ownership/provisioning, authoritative evidence decisions, signed artifacts and clean-machine install/remove/update acceptance remain outstanding; do not fabricate identity or promote an unsigned ledger into trust. Keep existing recovery compatibility limits, Android build/device gates and physical SIM/personal WhatsApp duplex-media proof separate. WhatsApp text/outgoing actions stay off; the real-game benchmark remains deferred.
