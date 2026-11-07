# Live design (core side)

Added 7 November 2026 (D1a). The owner asks JARVIS, by voice or chat, to design something. A draft then takes shape part by part. Each change applies at once and can be undone. Nothing is written until the owner builds, and the build needs approval. This page covers the core: the model, the brain tools, the renderer RPCs and the events. The workspace panel is task D1b.

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

Tests: `tests/test_live_design.py`.
