# Live design (core side)

Added 7 November 2026 (D1a). The owner asks JARVIS, by voice or chat, to design something. A draft then takes shape part by part. Each change applies at once and can be undone. Nothing is written until the owner builds, and the build needs approval. This page covers the core (the model, the brain tools, the renderer RPCs and the events) and the workspace panel (D1b).

## Model

`backend/services/cad_design.py` (`LiveDesigns`) keeps one live design per owner (principal), in core memory only. It survives renderer reloads but not core restarts. It is tied to the project that was current when it started, and builds save there. Another principal can't see or change it. All input is bounded by pydantic models with extra fields forbidden. No paths and no code are accepted. Names and text are trimmed, and control characters are removed. The owner's words are conversation content and are never logged.

The snapshot (`cad_design_get`, `cad_design` event):

```
{"design": null | {
  "id": uuid, "project": project name, "name": 1–60 chars,
  "status": "draft" | "building" | "saved" | "failed",
  "recipe": Recipe dict (shape "scene", 1–8 objects, engine "offline"),
  "steps": [{"n", "who": "jarvis"|"owner", "kind": "add"|"change"|"unsupported",
             "title" (≤ 80), "detail" (≤ 160), "added": [index after], "changed": [index after],
             "removed": [object as it was], "before": {"index after": object before},
             "undoable": bool}],
  "job": null | {"request_id", "state", "phase", "error"},
  "updated": epoch seconds}}
```

- **Starting a design** gives one `add` step per part, with the title `+ <part>` and a detail such as `open enclosure 160 × 200 × 180 mm, 3 mm walls, titanium`.
- **A change** gives one `change` step. The title is the owner's words in curly quotes, at most 78 characters inside the quotes, so the title stays within 80. The detail is generated, for example `shell 180 → 200 mm tall · + stand 150 × 190 × 10 mm, cyan`. A removed part shows as `− <part>`.
- **A request the engine can't make** gives one `unsupported` step, with the detail `not possible yet: <reason>`. Several reasons are joined with `; `.
- **Undo** restores the recipe from before the newest step that changed it, and removes that step.
  - Only the newest recipe-changing step can be undone, and only while the status is `draft`.
  - A step that has been built can never be undone.
  - The first part of a design can't be undone, because a design needs at least one part.
  - The snapshot keeps the newest 40 steps.
- **The status follows the design's CAD job.**
  - While the job runs, the status is `building`. It becomes `saved` when the job succeeds, or `failed` when it fails, is cancelled or is interrupted. The job's state, phase and error are mirrored into the snapshot.
  - A change during or after a build makes the design a `draft` again. A running job keeps going.
  - A `saved` design can't be built again until it changes. A `failed` design can be built again.

## Brain tools

These are registered by `register_cad_tools(dispatcher, service, designs)`. They are the brain's only CAD path. `generate_cad` and `plan_cad` stay registered for the 3D studio's RPCs, but they are now model-invisible.

| Tool | Arguments | Permission |
| --- | --- | --- |
| `start_live_design` | `{name, objects: 1–8 parts}`. Each part is a SceneObject with a required short `name`. | `live_design` (default `False`: never asks) |
| `change_live_design` | `{request: 1–200, add: 0–8 parts, update: 0–16 {object_index, fields}, remove: 0–8 indices, unsupported: 0–4 {feature, reason ≤ 100}}` | `live_design` |
| `undo_live_design` | `{}` | `live_design` |
| `build_live_design` | `{}` | `generate_cad` (asks by default) |

- **Changes are atomic.** Indices refer to the draft before the change, and the result must stay 1–8 valid parts. If any check fails, the draft is left unchanged.
- **The tools return the current parts** with their indices, the overall bounds in mm and a short summary for the brain to narrate.
- **The build's approval request** is the dispatcher's usual `tool_confirmation_request`, with `tool: "build_live_design"`. Its `args` hold:
  - `design_id`, `design_name`, `parts` and `project`;
  - `exports: ["stl", "glb"]`;
  - `summary`, for example `Build “Speaker box”? 2 parts · STL and GLB on this PC`.
- **If the design changes while the approval is pending**, the build is refused and the brain asks again.

## Renderer RPCs and events

These are for the owner's authenticated renderer sockets. Each RPC acknowledges with `{ok, ...snapshot}`, or with `{ok: false, code, message}`.

- `cad_design_get` returns the snapshot.
- `cad_design_undo {design_id, step}` undoes only the newest undoable step. A stale request returns `That change is no longer the latest.`
- `cad_design_build {design_id}` builds the design. The panel's Build click is the owner's consent, so no second approval prompt appears.
  - Denial (`generate_cad: "deny"`), the authentication recheck and the heavy-resource rules still apply. For example, gaming mode refuses the build.
  - The build is the same `generate_cad` service path as the studio's `cad_submit`: the offline engine, a new revision and the studio history.
- `cad_design_end {design_id}` ends the design. A running build continues and lands in the studio history.
- The `cad_design` event carries the snapshot. It goes to the owner's renderer sockets after every change and job update. It is also sent on renderer connect, or after unlocking, when a design exists. The studio's `cad_job` events are unchanged.
- `LiveDesigns.observer` (`callable(owner, active)`) is told when an owner's design starts or ends. `application.py` points it at the talking overlay, which then offers "Open JARVIS" while JARVIS designs (`design` in docs/VOICE_OVERLAY.md).

## Workspace panel

Added 7 November 2026 (D1b). The renderer shows the design beside the conversation.

**Files.**

| File | Role |
| --- | --- |
| `src/app/AssistantView.jsx` | The Assistant page: the conversation, plus the panel while a design exists. |
| `src/features/liveDesign/LiveDesignPanel.jsx` | Header, canvas, steps and footer; the RPCs and approvals. |
| `src/features/liveDesign/LiveDesignCanvas.jsx` | The react-three-fiber view: blueprint, solid, reveal, highlights, ghosts and the camera. |
| `src/features/liveDesign/model.js` | Pure rules: snapshot validation, the `bounds()` port, the reveal queue, ghosts and every label. |
| `src/store/liveDesignSlice.js`, `src/services/events/liveDesign.js` | The validated snapshot in the store, from `cad_design`. |

**Where it shows.**

- On the Assistant page with no feature open, while a design exists. A workspace canvas 900 px or wider (the owner's 1440 px window keeps the split with the context inspector open) shows the conversation on the left (flex 2, min 360 px) and the panel on the right (flex 3, min 420 px), with a 1 px divider. A narrower canvas shows a "Conversation | Live design" switch, which turns to Live design whenever a new design starts. Conversation stays mounted in both layouts, so the speaking core keeps reporting its visibility.
- When steps arrive while the owner is on another page or has a feature open, an accent banner reads "JARVIS is designing “<name>”." with "Open live design", which goes to the Assistant page. It hides once the panel shows them, or when the design ends.
- A design from another project adds "· in <project>" to the header.

**Store and events.** `cad_design` snapshots (and the RPC replies) are validated by `sanitizeDesignSnapshot`: only contract fields, at most 8 parts and the newest 40 steps, strings trimmed and clipped. An invalid snapshot is dropped. The renderer also asks `cad_design_get` on every connect and unlock, so a design that ended meanwhile clears. On disconnect the last snapshot stays and the footer says "Core offline", with the actions disabled. `liveDesignSeen` (`{id, n}`) is the newest step the panel has shown; the first snapshot after a page load marks every step seen, so a reload never replays the reveal.

**Header.** "LIVE DESIGN", the name and a status chip: "Drafting · k of n" while new parts are revealed, "Draft · not built", "Needs your approval" while an approval card shows, "Building", "Saved" or "Failed". Two icon buttons: "Open in 3D studio" and "End live design". End asks "End without building?" for a draft, and ends at once otherwise (`cad_design_end`).

**Canvas.** The parts' blockout boxes, framed isometrically and orbited by dragging, over a floor grid. Drafts are a blueprint: translucent faces and edge lines in the material colour.

- New "add" steps reveal their parts one at a time, 400 ms apart. Each fades in and drops 8 mm into place over 300 ms. There is no reveal under reduced motion, and none on the first snapshot after a load. The steps list shows each row as its part appears.
- The newest step's new or changed parts have accent edges for 1.2 s.
- A change's old parts and removed parts show as dashed ghosts until the next step, an undo, or 6 s.
- The camera refits, with a short ease, when the bounds change, keeping the orbit direction, but not while parts are being revealed.
- A saved design shows the built model (`ModelPreview` in its `bare` mode) once its GLB loads, and the recipe solid otherwise.
- The overlays are a callout chip of the newest step, a HUD line about the geometry, and "Drag to orbit".

**Steps.** About five rows, newest at the bottom and scrolled into view. Each row has "YOU" or "JARVIS", the title and the detail; unsupported details are in warn. An undoable row has "Undo" (`cad_design_undo`). Errors from any action show under the list for 6 s, for example gaming mode's refusal of a build.

**Footer.**

- Draft: "N parts · W × D × H mm · draft" and "Build it". The bounds are the renderer port of `bounds()`.
- The approval card: "Build “<name>”?", "N parts · STL and GLB on this PC · about 10 s", and Not now and Build.
  - After "Build it", Build sends `cad_design_build`.
  - For a pending `tool_confirmation_request` with `tool: "build_live_design"` and this design's id, the buttons answer it (`confirm_tool`). While the panel is on screen the global approval popup skips such requests; otherwise it shows them, with the "Build live design" layout.
- Building: "Building geometry", "Checking the solid" and "Saving exports" from the job's phase, a progress line and Cancel (`cad_cancel`).
- Saved: "N closed parts · W × D × H mm", STL and GLB downloads (`cad_artifact`) and "Open in 3D studio".
- Failed: the job's error and "Try again", which opens the approval card.

**Open in 3D studio.** A saved design of the current project opens the studio with its revision selected (`studioSelection`). Anything else is handed to the studio as its working draft (`cadDraftHandoff`, read once when the studio mounts), shown as "Draft blockout". The hand-off is one-way; the live design stays open.

Tests: `tests/test_live_design.py` and `tests/test_live_design_panel.mjs`.

## The CAD engine: feature steps and draft previews

Added 15 November 2026 (S3, M7 K1). With the CAD engine installed, a live design is more than boxes: it is a **feature tree**, its parts followed by feature steps, built into real geometry by build123d. The brain never writes code; it sends validated steps, and an isolated worker builds them. Without the engine, everything above is unchanged.

**The CAD engine.** build123d 0.13.0 in its own Python 3.13 environment, `.venv-cad` at the repo root, apart from the core's `.venv`.

- `backend/services/cad_features.py` validates the tree: at most 40 features, parts included; sizes 0.1–2000 mm; text up to 40 characters. It gives each tree a stable hash.
- `backend/workers/cad_kernel_worker.py` builds the tree. It runs as `.venv-cad\Scripts\python.exe -I`, speaks JSON lines over stdin and stdout, never uses the network, and works in a temp job folder.
- `backend/services/cad_kernel.py` starts the worker on the first build and reuses it. The worker stops after 5 idle minutes. Builds time out (20 s for a draft, 120 s for a final build), and a timeout kills the process tree. Kernel errors become plain messages, for example "A 3 mm fillet does not fit a 4 mm edge".
- **Setup.** The owner runs `scripts/setup-cad-engine.ps1` once: `powershell -ExecutionPolicy Bypass -File scripts\setup-cad-engine.ps1`. It creates `.venv-cad` from `requirements-cad-kernel.lock`, a hash-pinned lock, then runs a smoke check. It is safe to run again. JARVIS never runs it and never downloads anything for the engine.
- **Without the engine**, feature steps are refused with "Holes, fillets and cut-outs need the CAD engine. Run scripts/setup-cad-engine.ps1." Box, bracket and enclosure parts still work as before.

**Feature steps.** `change_live_design` takes `features`, steps added in order after the parts. Each step targets a part by name.

| Op | Fields |
| --- | --- |
| `hole` | `target, face, at [u, v], diameter, depth` ("through" or mm); optional `cb_diameter`, `cb_depth` for a counterbore |
| `slot` | `target, face, at, length, width, depth, angle` |
| `fillet` / `chamfer` | `target, edges` (`all`, `vertical`, `top`, `bottom`), `radius` / `distance` |
| `cut` | `target, tool` (an inline box, cylinder or sphere at its centre `at`) or `target, bodies` (part names) |
| `shell` | `target, thickness, open` (the open face) |
| `text` | `target, face, text, size, depth, mode` (`engrave` or `emboss`), optional `at` |
| `pattern` | `of` (the id of an earlier hole, slot, text or cut), `linear` with `count [nx, ny]` and `spacing [dx, dy]`, or `polar` with `count`, `radius` and optional `angle` |
| `mirror` | `target, plane` (`XY`, `YZ` or `XZ`) |

- Faces: top +Z, bottom −Z, front −Y, back +Y, left −X, right +X. A face's `at [u, v]` is in mm from the face's corner with the smallest coordinates.
- **Shells before fillets.** Put `shell` before `fillet` and `chamfer`. Shelling a body that is already rounded often fails, or leaves walls thinner than asked.
- Each feature step is an ordinary step row with Undo. If the tree or the kernel refuses a step, it becomes a "not possible" row with a plain reason. The draft stays as it was, and the brain hears the reason in `not_possible`.
- Threads and free-form curves can't be made. They go into `unsupported`, as before.

**Draft previews.** Every change asks for a draft GLB build. Builds are debounced (150 ms), one at a time per design, low quality, and cached by tree hash. The `cad_design` snapshot then has `preview`. The field exists only on the kernel path, so the renderer keeps the box path whenever it is missing:

```
"preview": {"engine": "kernel",
  "state": "starting" | "building" | "ready" | "failed" | "paused" | "unavailable",
  "message": text | null, "current": bool,
  "glb": null | {"request_id": uuid, "format": "glb", "bytes": n, "sha256": hex},
  "facts": null | {"volume_mm3", "bbox_mm": [x, y, z], "min_mm": [x, y, z], "faces", "edges", "solids", "valid"},
  "warnings": [{"code", "index", "message"}], "seconds", "cached"}
```

- `current` is true when the shown model matches the current draft. The last good `glb` and `facts` stay while the next draft builds or fails.
- Gaming mode pauses draft builds (`paused`). They resume when the owner looks at the design again.

**In the panel** (`LiveDesignCanvas.jsx`, with the rules in `liveDesignKernelModel.js`).

- **Loading the GLB.** The canvas fetches the GLB with `cad_artifact {request_id, format: "glb"}` whenever the reference changes. GLBs travel over the socket, so the CSP needs no new `connect-src`.
  - The reply's size and digest must match the snapshot. The decoded bytes' SHA-256 is checked with SubtleCrypto before parsing.
  - The last four GLBs are kept in memory by SHA-256, so an undo shows at once.
  - A reply is dropped when a newer GLB was asked for meanwhile. A GLB that fails to load leaves the last good model in place.
- **Style.** The model is drawn as a blueprint: accent-tinted faces at about 12 % opacity, and bright accent edges where faces meet at 20° or more, so holes, fillets and text read clearly.
- **Change highlight.** When a new GLB replaces the shown one after a step, its edges flash in `--accent-hot` for 1.2 s. There is no flash under reduced motion.
- **Camera.** The camera frames the model once. It refits only when a side changes by more than 20 % of the largest side, or the centre moves by more than 20 % of the radius, so adding a hole or a fillet keeps the view still.
- **Before the first GLB** arrives, the parts' blockout boxes stand in.
- **Status chip.** A chip in the canvas's top-right corner shows the preview state while the shown model isn't current:

  | State | Chip |
  | --- | --- |
  | `starting` | "Starting the CAD engine…" |
  | `building` | "Updating…" |
  | `failed` | The message, in warn |
  | `paused` | "Paused in gaming mode" |
  | `unavailable` | The message |

  The last good model stays on screen in every state.
- **Facts and warnings.** The draft footer shows the kernel's facts in place of the part count, for example "Volume 11.6 cm³ · 60 × 40 × 5 mm" (mm³ shown as cm³ with one decimal). The kernel's warnings show as small warn rows above the footer.
- **A saved design** still shows the built revision through `ModelPreview`, the solid style.

**STEP export.** With the engine installed, "Build it" saves GLB, STL and STEP through the normal `generate_cad` job, and the approval card says "STL, GLB and STEP on this PC". The STEP file lands in the project's revision with the others. Without the engine, a build saves STL and GLB as before.

Tests: `tests/test_live_design.py` (core), `tests/test_live_design_kernel.mjs` (the preview rules).
