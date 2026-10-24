# Protected installation management

Implemented 22 October 2026. A dedicated native WPF window now fronts protected metadata status, signed enrollment/renewal/trust rotation, local package updates, retained-version rollback, interrupted-change resume and pre-commit cancellation. The dark cyan interface has selectable review details, local file/folder pickers, keyboard focus cues and a scrollable layout verified at 1120 and 780 pixels.

This window manages the protected format-3 workflow. It does not replace the earlier unsigned pilot Setup window. It neither downgrades managed metadata nor routes it through unsigned installation/recovery controls. Step 3 is now implemented in [protected lifecycle](MANAGED_LIFECYCLE.md): encrypted backup, typed recovery-copy preparation, signed profile activation/rollback and separate software/profile removal.

## Open through your trusted controller

Keep the controller outside the installation it manages. Use the independently trusted bootstrap and independently retained inventory pin. The bootstrap locks and verifies the complete controller before running Python; the native entry rechecks the exact inventory before starting its fixed WPF script. The outer bootstrap retains file leases for the window lifetime. The packaged UI starts a second verified-bootstrap child for its private management worker. Neither path takes shell commands from UI inputs.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/open-trusted-controller.ps1 -Directory C:/trusted-controller -ExpectedManifest '<independent controller inventory pin>' managed-setup --expected-manifest '<same independent pin>'
```

Use a controller assembled from this milestone; older artifacts do not expose these commands. See [verification evidence](qa/managed-native-ui-verification.json) for the development artifact identity. This is a local development-host native entry, not an owned signed installer, trusted delivery channel or clean-machine certification. Provider, device and production signing configuration remain deferred.

## Status and signed changes

Enter the installation path, its separate checkpoint directory and your independently retained latest checkpoint pin. **Check protected status** verifies the protected metadata binding and reports checkpoint number, selected slot and sequence floor. It does not establish live grant/native-signature eligibility to launch. No resident or workspace is started by this UI.

For a change, choose Update, Rollback, Renew, Rotate trust or Enroll. Supply the externally signed launch grant and change envelopes, retained grant head, current release/Windows policy files and independent pins. Proposed policy files require their independent pins; rotation still needs both old and new authority cohorts. New-slot updates need the original signed package directory. Keep that package available at the reviewed path until completion or recovery. First enrollment uses the explicit `new` checkpoint sentinel; it does not infer trust from local metadata.

The existing command-line prepare-grant/prepare-change workflow and external signing process produce the signed inputs. The window does not create private keys, sign envelopes, enroll real identities or download packages. It offers already implemented backend operations through a finite control surface.

**Review signed change** validates signatures, current state, source bytes, policies and profile compatibility before showing the exact plan. Review includes installation/checkpoint location, resulting and previous checkpoints, selected slot, source package/profile and review digest. **Confirm reviewed change** consumes the review and revalidates the exact backend plan before applying. Versions/profiles remain retained under the existing transaction rules; migration and launch are not automatic.

## Interrupted changes

Use **Interrupted change** with the independently retained prepared checkpoint above and previous committed checkpoint below. `new` is allowed as the previous pin only for interrupted initial enrollment. Review resume finishes the existing journaled transaction. Review cancellation is available only while committed metadata remains untouched; it removes the journal while retaining staged copies/evidence. After commit starts, cancellation refuses and reviewed resume is required. The UI does not discover or automatically trust pins from the journal or checkpoint head.

## Review and worker lifetime

The persistent worker uses private stdin/stdout JSON, bounded complete frames and a fixed set of operations: status, review, apply and discard. It exposes no HTTP listener, assistant route, arbitrary process dispatcher or fixture/native-verification bypass. Paths are bounded local absolute paths; trust and compatibility checks stay in the existing backend.

A review lasts five minutes and has a random, single-use in-memory token binding the normalized request and exact backend review digest. Apply consumes it before validation, including failures. Status, discard, replacement or malformed requests revoke older reviews. UI input/action/page changes clear confirmation, and the worker independently rejects changed arguments, expired tokens and reused tokens. No retry or mutation is automatic.

Heavy verification/copying runs outside the WPF dispatcher. Inputs, navigation, conflicting actions and window closure are blocked while an operation is in progress. Closing idle management closes the worker input and discards reviews. A broken connection reports uncertainty and requires checking status or reviewed recovery; it does not cancel or replay a transaction. Backend journals/checkpoints remain authoritative.

Returned checkpoints can be explicitly copied. They never replace your entered pin automatically; retain the result independently before using it for the next operation. Retain prepared and previous pins before confirmation as well. On an uncertain apply, the window keeps its exact review visible with confirmation disabled and offers **Copy prepared checkpoint**; that pin is not proof of commit. Use status or reviewed recovery to resolve the outcome. Other refusals and input edits clear stale results. Production policies remain disabled by default.

## Verification and next work

Native render/interaction acceptance covers review/apply binding, expiration, single-use confirmation, input edits, recovery/cancellation routing, explicit returned pins, stale-result clearing and busy-window protection. Actual packaged isolated Python/bootstrap acceptance covers connection, repeated asynchronous messages, missing-state refusal without creating a root/anchor, idle EOF shutdown and bad-inventory-pin refusal before worker readiness. Synthetic protected enrollment exercises the real signed backend and current-account protection; changed signed inputs after review refuse. Synthetic test keys and inert native adapters do not authorize a real release.

[Execution evidence](qa/managed-native-ui-verification.json), [overview](qa/managed-overview.png) and [narrow review](qa/managed-review-780.png) retain the results. The broader managed update/signature/recovery/package regressions pass. Actual production signed-package/native-window mutation, clean-machine interruption and owned delivery acceptance remain pending. Controller distribution decisions stay separate from the desktop ledger.

Protected backup/restore and reviewed removal are now implemented in [protected lifecycle](MANAGED_LIFECYCLE.md). Next: owned publisher/reviewer identity custody, Windows signing/trusted delivery preparation and actual signed-package/clean-machine lifecycle acceptance when configuration is authorized. Android, physical SIM/personal WhatsApp control/duplex audio, real capability providers and Legion sustained-use acceptance remain separate gates. WhatsApp text/outgoing actions remain off; real-game benchmarking remains deferred.
