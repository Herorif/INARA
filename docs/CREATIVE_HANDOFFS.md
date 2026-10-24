# Reviewed creative handoffs

Implemented 20 October 2026. In **Studio > Artifacts**, choose a successful saved revision, select **3D blueprint brief** or **Image concept brief**, then **Review handoff**. The destination opens with a separate review card; the existing draft remains intact. Apply transfers the reviewed brief. Discard preserves the draft. Generating an image, proposing geometry and building remain separate actions with their existing permissions and approvals.

This milestone transfers **recipe metadata**, not media. CAD recipes contribute bounded dimensions/transforms/materials; image recipes contribute their saved text prompt. No PNG/GLB, camera frame, notification content, pixel analysis, image-to-image conditioning or inferred geometry is passed to a model. The UI states this boundary and shows the actual proposed brief. A new CAD brief selects the scene proposal mode; the owner must separately request, review and apply a blueprint before building.

## Source integrity and lifetime

`creative_handoff` is a strict read-only, authenticated unlocked-owner renderer route. The current owner/project must contain a successful source with the exact UUID and recipe fingerprint. Its saved JSON export is read with existing bounds/hash checks. A changed, missing, foreign, incomplete or linked-outside-project source rejects. Neither caller-supplied paths nor arbitrary destinations are accepted.

The returned reference pins source kind, UUID, normalized recipe fingerprint and JSON export SHA-256. Apply attaches that reference to the local draft. Before CAD planning or either creative build, the core revalidates the source against its protected receipt; queued builds revalidate immediately before starting a worker. Duplicate request IDs cannot change source provenance. Completed protected job receipts expose the reference in revision history and Artifacts. Worker recipes remain unchanged and contain no source path or provenance command.

The pending global navigation state contains only project/source/destination identifiers and a local selection ID. Briefs and exports stay inside the mounted review. Closing the panel disposes pending RPCs and clears the handoff; project change, disconnect and lock clear it too. Reconnection does not replay it. Destination draft edits invalidate Apply, including edits to an existing CAD brief. The owner can explicitly detach an applied reference; reselecting saved revisions restores their recorded provenance. References do not assert that generated work faithfully reproduces its source.

## Verification

**235 focused Python checks and 106 frontend checks pass**, plus types, generated contracts, lint, build and diff checks. Ten new Python cases cover four source/destination combinations, owner/project/role/lock gates, strict inputs, edited exports, forged digest rejection, rejected admission, queued revalidation, duplicate conflicts and reference persistence through actual offline CAD and synthetic image workers. Four frontend cases cover scoped response validation, no implicit execution, late/disconnected reply rejection and metadata-only global activity state. Eleven release-tool checks also pass after updating the gates.

Actual hidden native UI acceptance passes both directions, review/Apply/Discard, rejection after editing a CAD brief, and 390px layout. Handoffs cause no extra provider call or worker; all seven verification workers exit (six offline CAD builds and one labeled synthetic image). [Evidence](qa/creative-handoffs-verification.json), [image destination](qa/handoff-image-desktop.png), [3D destination](qa/handoff-cad-desktop.png), [390px review](qa/handoff-image-390.png). Resource admission used deterministic hardware counters. Short resident working set was 68.95 MB before opening and 70.63 MB after workers/UI exited; this is not a sustained-load or gaming benchmark.

Real provider quality, image inference, Blender, camera and phone acceptance remain deferred. The synthetic image adapter exists only in verification code and is not installed as a production generator. The broader environment's previously documented optional dependency/key failures have not been hidden or repaired by configuring providers.

## Remaining priorities

The next required call gate is still physical proof of exact controls and isolated duplex audio on the Fold/Legion, separately for SIM/Phone Link and personal WhatsApp Windows. After proof: validated enrollment, live usage admission, message-taking acceptance, protected real-call inbox, channel acceptance and authenticated Android receipt sync. [Call lab and limits](CALL_LAB.md).

Android reproducible builds/device testing, real AI/Blender/image/speech/vision acceptance, packaging/signing/licenses and update/recovery remain open. Those require actual tooling, configuration, devices or signing inputs; this handoff does not complete them. WhatsApp text replies and outgoing calls remain off, and the real-game benchmark remains deferred. [Release gates](RELEASE_GATES.json).
