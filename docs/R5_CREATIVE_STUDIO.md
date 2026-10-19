# R5 Creative Studio v2

Implemented as one offline creative-workflow milestone on 19 October 2026. Engineering-kernel features and real provider/Blender/image acceptance remain deferred. The next whole milestone is R6 quick assistant and voice consolidation.

## Editing and review

CAD and image panels now keep editable drafts separate from immutable saved revisions. A shared bounded history supports fifty undo steps, redo, reload-base and independent copies. Starting another edit after undo discards the abandoned redo branch. History is panel-local; saved revisions survive panel/core closure. Opening a saved revision reloads its recipe. The branch banner identifies the base of the next build, and the field comparison shows pending changes without claiming the old saved model reflects the draft.

Scene object selection is shared between the object roster and offline saved-model picking. Blender mesh picking is disabled until the installed bridge/object mapping is accepted; the roster remains available. Numeric dimensions, CAD X/Y/Z rotation, scale, materials and translation remain bounded by the backend contracts. A separate demand-rendered draft blockout provides object picking and a translation gizmo with local axes, one-millimetre snap and one committed undo step per drag. CAD uses millimetres and Z up, displayed through a Y-up view transform. The Euler order implements scale, then X/Y/Z rotation, then translation. Box-part blockouts are visual aids: they do not establish closed topology, fuse overlapping parts or generate export files. Only the owned worker validates and saves geometry. Saved statistics/exports are explicitly labelled when inspecting an unvalidated draft.

Saved model controls provide fit, frame selected object, top/front views and revision-scoped camera bookmarks. Only bounded camera position/target coordinates are retained in the renderer profile; no prompts or geometry enter browser storage. Bookmarks survive panel closure. Unavailable storage falls back to a clearly labelled panel-local bookmark. Comparison is explicit: choosing a saved revision opens two independent demand-rendered saved views and a recipe field comparison. Each extra preview releases its renderer/artifact scope when closed.

The image panel shares undo/redo, branching and recipe comparison. Its optional gallery loads at most four recent successful images, only when expanded. Reuse explicitly reloads a chosen saved recipe; it never starts generation. Comparison loads the chosen saved image beside the selected revision. Preview blobs and RPC listeners are disposed when their scope closes. Existing hash/size checks remain on artifact reads.

## Immutable revision references

`services/revisions.py` provides paired base UUID/fingerprint fields for CAD and image requests. Fingerprints hash normalized recipe data, with equivalent integer/float values represented consistently. Owner/project/adapter scope is resolved by the existing application services. A child requires a successful saved parent and its matching fingerprint. A changed/missing/foreign parent rejects before job claim, reservation or worker creation. Deliberate branches from older immutable revisions are allowed; being older than another revision does not make a base stale.

The encrypted job record and public metadata retain `base_request_id`, `base_fingerprint` and `recipe_fingerprint`. Parent references stay outside recipe/worker inputs. Reusing an existing request ID requires the same recipe and parent; it cannot be repurposed into a different branch. Existing exported recipe/geometry files remain unchanged. Branch badges appear in revision history and Activity. The recent-history window remains twelve jobs per adapter, with the existing 128-job project limit; this milestone does not introduce an unbounded artifact browser.

Old records lacking parent metadata remain readable. Their normalized recipe fingerprint includes current explicit defaults. Existing artifact bytes are not rewritten during hydration or comparison.

## Data-only change proposals

`services/cad_changes.py` owns strict bounded changes: an explicit base UUID/hash, at most sixteen field edits, and optional object indices referring to that base's object order. Supported fields cover dimensions, names, existing-object transforms/materials and fixed presentation presets. Extra fields, arbitrary paths, scripts, topology operations, invalid indices, nonfinite/bool transform values and invalid wall dimensions reject. Final recipes pass the same CAD schema used by manual builds.

`cad_review_changes` computes a proposal against that exact saved base. `cad_plan_changes` uses the shared dispatcher and generate_cad permission, with a separate hidden planning tool, to ask an optional configured provider for the same bounded schema. SDK schemas expand references through the existing shared helper. Provider output cannot launch a worker or modify artifacts. Owner/base validity is checked before and after provider planning; provider timeout/cancellation closes its session and releases planning ownership. Closing the panel cancels planners and approvals through the existing lifetime service.

The UI first presents before/after fields and requires **Apply to draft**. This still does not build. **Build new revision** retains the existing generation approval and worker admission. If the draft or selected base changes during planning/review, application is rejected and a new proposal is required. Planning targets the saved base; the review shows any current unsaved fields that would be replaced. Independent new-solid proposals now use this explicit review step as well. Missing configuration preserves manual editing and saved previews. There is no generated Python or arbitrary execution path in these new workflows.

The supported inventory is 57 socket routes, 54 dispatcher tools (40 text-visible) and 37 voice mappings. The new ChangeSet/ChangePrompt and paired revision fields are exported to generated Pydantic JSON schemas/TypeScript. The additive UI contract remains version 1.

## Fixed adapters and remaining gates

The Blender bridge accepts typed camera, lighting, background and preview/standard quality presets, with fixed CPU rendering, thread count, resolution/sample ceilings and the existing owned process/deadline. It still imports only the bundled worker's embedded GLB; it does not accept Blender scripts or external scene files. Materials/transforms remain typed scene data. Actual Blender load/save/render/export is **unverified because Blender is not installed**. The offline worker is independent of it.

Holes, fillets, booleans and STEP are explicitly unavailable in the CAD capability response and UI. No engineering kernel is installed/enabled or claimed accepted. Kernel-backed operations require a separately implemented/validated owned adapter and representative topology/export acceptance. Local Diffusers remains unconfigured/unverified. Reference-image editing, masks, upscalers, cloud image engines and CUDA profiles remain separate adapter/acceptance work. No models, kernels or applications were installed.

R4's bounded FIFO queue, fixed estimates, gaming/resource restrictions, captured owner/project context, explicit background choice, cancellation and cleanup remain authoritative. The new UI adds no resident background loop and no startup microphone/camera/model work.

## Validation and evidence

707 Python tests pass with one Blender-dependent skip; all 52 Node checks pass. Semantic TypeScript, generated-contract drift, scoped Ruff, production build and whitespace checks pass. The CI workflow includes the new cases; hosted CI has not been run here. Existing Vite CJS/large-chunk/Browserslist and Node module-type notices remain. Initial renderer JavaScript is about 248.53 KB; the heavy CAD preview remains lazy.

| Native acceptance | Evidence | Outcome |
| --- | --- | --- |
| Offline CAD and reviewed branch | [Report](qa/r5-cad-verification.json) | Five actual offline workers started/exited. Real STL/GLB/JSON exports, typed scene transforms/materials, undo/redo, a labelled proposal fixture requiring explicit review, child/parent comparison, camera bookmarks after panel closure and Activity restore pass. No geometry module loaded in the resident. Short recovery: 67.14 MB. |
| Image recipe/gallery workflow | [Report](qa/r5-image-verification.json) | Four labelled fixture workers started/exited. Branch ancestry, undo/redo, explicit gallery/comparison, real fixture exports, reconnect/history recovery and foreground/background cancellation pass. No real image model or Torch/Diffusers/PIL module loaded in the resident. Short recovery: 66.58 MB. |

Native suites ran serially with isolated profiles and no external asset requests. Layout checks cover 390, 768 and 1440 pixels. Visually inspected [draft blockout](qa/r5-draft-blockout.png), [saved CAD comparison](qa/r5-revision-compare.png), [image comparison](qa/r5-image-compare.png), [gallery](qa/r5-image-gallery.png), [mobile CAD](qa/r5-cad-mobile.png) and [mobile image controls](qa/r5-image-mobile.png).

 Tests cover immutable branching, scoped/stale references, exact replay identity, strict edit/vector/wall/render schemas, provider cleanup and post-provider checks, planner cancellation, undo/redo, transform order, bounded blockouts, camera bookmarks and typed proposal ACKs. Native UI verification uses real offline CAD workers and clearly labelled proposal/image fixtures; it makes no claim of real provider or image-model execution.

Physical gizmo-pointer/device acceptance, installed Blender/kernel behavior, real image/provider quality, GPU measurements, physical audio/camera/printer acceptance and the user-deferred game benchmark remain outside this verification. No new ten-minute idle target claim is made from short post-worker recovery samples. Exact Legion/Fold specifications and API configuration remain unconfirmed/deferred. Existing SIM/personal WhatsApp identity remains unchanged, and WhatsApp reply drafting/sending remains excluded.
