# Receiving a controller and preparing clean-machine acceptance

Step 5 adds `scripts/controller-receive.py`, an external receiving verifier, reviewed directory-copy preparation and a pending clean-machine acceptance plan. It does not sign, enroll, install, launch or certify a clean machine. Read [the deferral register](DEFERRED_WORK.md) before continuing.

## Independent trust comes first

Obtain the verifier, its compatible trusted helper tools and Python/cryptography environment through an independently trusted channel. Run the verifier from that location. A copy under received `evidence/external` is inert producer evidence and must never establish the verifier's trust. No received script, Python runtime or bootstrap is executed during receiving verification. This implementation supports the current controller manifest format and required source inventory; a different format needs an independently reviewed verifier update.

Retain external release and Windows policy files, their exact hashes, expected controller manifest and public enrollment hashes, and the independently current sequence. Policies must remain outside the delivered package. Embedded declarations, receipt hashes and the package's original output path confer no authority. The explicit sequence and policy floor still need independently retained current state; the receiver has no hardware anti-replay counter. Both checked-in production policies remain disabled.

Producer-side `controller-delivery.py verify` still regenerates provenance against a matching source checkout. Receiving verification uses external publisher/reviewer signatures to endorse exact producer evidence snapshots. It checks the report/queue binding, derives the queue's subject coverage, binds the producer review-tool digest, validates the complete ledger chain, attachment hashes and approved coverage, and assesses public custody assertions. It does **not** reconstruct source provenance or authenticate human/legal identity, hardware key custody or redistribution clearance. `producer_source_rederived` is explicitly false.

Detached production signatures, purpose, bounded live window, external sequence and independently expected pins are checked before payload inventory, evidence parsing or native verification. The receiver then verifies the controller's exact pinned closure and bootstrap hash, signed provenance/ledger/public-custody inventories, and cache-only native signatures against the external Windows policy. It rechecks snapshots, controller bytes and signature validity after verification. Native trust cannot be bypassed through the CLI. Public custody assertions and complete reviews are required; no key loader or signer is provided.

## Review and copy

Use the separately trusted tool with these explicit arguments (substitute actual independently obtained values; placeholders are not configuration):

```powershell
$receivingArgs = @(
  '--controller', 'C:\delivery-input\controller',
  '--evidence', 'C:\delivery-input\evidence',
  '--ledger', 'C:\delivery-input\ledger',
  '--enrollment', 'C:\delivery-input\enrollment',
  '--envelope', 'C:\delivery-input\envelope.json',
  '--expected-manifest', '<external manifest SHA256>',
  '--expected-enrollment', '<external enrollment SHA256>',
  '--policy', 'C:\independent-trust\release.json',
  '--expected-policy', '<external policy SHA256>',
  '--windows-policy', 'C:\independent-trust\windows.json',
  '--expected-windows-policy', '<external Windows policy SHA256>',
  '--sequence', '<independently current sequence>'
)
python C:\trusted-tools\scripts\controller-receive.py verify @receivingArgs
python C:\trusted-tools\scripts\controller-receive.py plan @receivingArgs --output C:\new-receiving-package
# Inspect the returned destination, exact inventory and pending acceptance plan.
python C:\trusted-tools\scripts\controller-receive.py apply @receivingArgs --output C:\new-receiving-package --expected-plan '<reviewed plan SHA256>'
```

`plan` is read-only. `apply` rederives the plan, requires its exact digest and copies to a new separate directory. It streams bounded files, checks copy hashes, revalidates both original and copied delivery, writes `acceptance.json` and then `receipt.json`, and verifies package closure. Nothing is installed or selected. It never overwrites an existing destination. Preserve incomplete output on interruption; choose a new destination for a fresh reviewed copy. The receipt contains the original *plan* with `copied:false`; only successful `package-verify` establishes that the receiving directory is complete now.

The resulting directory contains `controller/`, `evidence/`, `ledger/`, `enrollment/`, `envelope.json`, `acceptance.json` and `receipt.json`. Policies, private keys and user profiles are not included. Delivery can be relocated. To verify a complete receiving directory, use `package-verify --package <directory>` with the same external expected hashes, policy paths and sequence; omit the separate input directories, envelope, output and plan arguments. Added/missing files, changed acceptance templates and inconsistent copy receipts refuse. Receipt integrity is not a new signature or release authorization; the signed payload and independent expectations remain decisive.

Keep input and output locations under the operator's control during verification/copy. Hash rechecks detect ordinary drift, but do not make a hostile concurrent writer or compromised Windows account safe. Receiving verification is point-in-time and intentionally does not authorize later execution. The guarded bootstrap/lifecycle boundaries must perform their own current checks.

## Clean-machine acceptance remains pending

Every generated acceptance check starts `pending` with no evidence. The plan is tied to the signed statement digest. There is no CLI to turn it into a certification or automatically perform real-machine changes. Keep the template unchanged; record actual execution evidence separately and update release gates only after review.

After real configuration is explicitly resumed:

1. Complete the separate controller and desktop source/license/native/security reviews, owned identity/certificate custody and independently trusted tool delivery. Prepare actual signed artifacts with sufficient live authorization and external current sequence/checkpoint pins.
2. Record the clean Windows version/account, machine inventory, operator, UTC times, trusted verifier/runtime origins and exact input hashes. Use disposable test data and record baseline startup, services, certificate stores and network behavior.
3. Exercise invalid/missing signatures, expired/replayed authorizations, wrong pins and modified/extra/shared files. Confirm refusal before execution and no destination changes.
4. Exercise actual signed installation and native-window launch; authorization expiry and controller-death child cleanup; signed update, rollback and trust rotation; interrupted copy/commit and checkpoint recovery.
5. Exercise original-account encrypted backup/typed recovery, software removal retaining profiles, and separate explicit profile erasure with interrupted-resume phrase enforcement. Record expected versus observed outcomes, commands/log hashes and redacted screenshots. Preserve external checkpoint history and original packages for recovery.
6. Confirm no unrequested startup, downloads, account migration or collection. Keep optional providers, Android and physical calls on their separate acceptance tracks. A clean-machine desktop result does not prove personal WhatsApp/SIM two-way AI audio or authorize WhatsApp text replies.

Next work is actual owned signing/trusted delivery and real clean-machine/native lifecycle acceptance **when configuration is explicitly resumed**. While that remains deferred, independent source improvements should be chosen from remaining backlog, with their scope recorded; do not relabel another source fixture as real acceptance. See [release gates](RELEASE_GATES.json), [protected lifecycle](MANAGED_LIFECYCLE.md) and [signing preparation](SIGNING_DELIVERY_PREPARATION.md).
