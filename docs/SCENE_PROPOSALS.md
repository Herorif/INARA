# Reviewed multi-object scene proposals

Implemented 20 October 2026. In **Studio > 3D studio > AI blueprint**, choose **New scene assembly**, describe the design and request a proposal. With a saved revision, the default continues to refine that revision through the existing bounded edit planner. New solid and scene blueprints can also replace a draft while preserving its selected parent for the next build.

The review surface lists proposed parts, dimensions, position and materials. **Preview proposal** opens an orbitable approximate blockout on demand. It offers no editing gizmo; the exact field comparison includes rotation and scale. Applying replaces the editable draft and selects its blockout view; it starts no worker. Build new revision remains a separate explicit action with the existing approval policy and protected parent/fingerprint checks. Discard preserves the draft. Draft edits or base changes invalidate Apply; disconnect clears the proposal, and unmount/project change discards pending client replies.

## Data and execution boundary

The existing `cad_plan` route and `plan_cad` tool accept an additive `target: solid | scene`, defaulting to solid for older clients. The scene planner uses a strict `SceneBlueprint`: one to eight box/bracket/open-enclosure parts, readable names, existing dimensions and wall constraints, finite bounded transforms and four fixed materials. Nested scenes, scripts, arbitrary meshes, paths, shaders and extra fields reject. The provider cannot select an engine; the normalized recipe uses offline generation. There are no new socket routes or executable model tools.

The provider must return exactly one data proposal through `propose_cad_recipe`. It receives the owner prompt and schema, not owner history or a general tool dispatcher. Provider close is bounded on success/failure/cancellation. The existing shared `plan_cad` permission, approval, owner authentication, resource restriction and per-call usage admission apply. Budget denial occurs before provider generation. The route rechecks its current principal/project after the asynchronous result, and the renderer validates dimensions/object count/transforms before handing data to a preview.

`backend/services/cad.py` shares the optional blueprint adapter between solid and scene schemas. `SceneBlueprint` reuses the existing typed scene parts; the fixed worker and exports are unchanged. `BlueprintReview.jsx` separates proposal presentation from draft/build state. Generated request/schema exports include the new target and proposal contract.

## Acceptance

**215 focused Python checks passed, one Blender-dependent skip; 102 frontend checks passed.** Types, generated-contract drift, lint, production build and diff checks pass. New cases exercise invalid topology/fields/transforms/count/materials, exact target, no build during planning, per-call budget denial, provider cancellation/close, stale project return and actual offline scene exports. The stricter renderer guard also covers malformed edit proposals.

Actual hidden native UI acceptance uses an injected synthetic provider, shared approvals, real offline workers and isolated projects. The review keeps the prior three-object draft/history until Apply; preview and Apply create no revision. A separately approved build produces the two-object revision. Existing solid builds, GLB import/download, scene editing, revision comparison, undo/redo and reopen checks continue passing. All six observed workers exited; geometry modules stayed absent from the resident. [Verification](qa/scene-proposals-verification.json), [desktop review](qa/scene-proposal-desktop.png), [390px review](qa/scene-proposal-390.png).

Resource admission used deterministic hardware counters. Short resident working set was 67.32 MB before the workspace and about 70.31 MB after all workers/UI exited; this is not a sustained-load or gaming benchmark. No real provider, model download, Blender, image inference, camera, phone or WhatsApp action ran. Provider output quality, latency and costs remain unverified while configuration is deferred. Assemblies remain separate closed parts, not boolean unions, fabrication certification or arbitrary generative meshes.

## Remaining sequence

1. Calls retain priority when physical setup becomes available: prove exact app controls and isolated duplex audio on the actual Fold/Legion, separately for both requested channels. Live enrollment and usage admission must precede live UI answering and real phone receipt sync. [Call gate](CALL_LAB.md).
2. Reviewed recipe-reference handoffs are now [implemented](CREATIVE_HANDOFFS.md): select a saved artifact, choose the destination studio and review its brief before any provider or worker starts. Raw camera/notification content and implicit paid calls remain excluded.
3. Complete Android reproducible build/device acceptance, real capability acceptance and signed desktop/mobile distribution/update recovery against [release gates](RELEASE_GATES.json). Existing optional dependencies and API configuration remain deferred.
