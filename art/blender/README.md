# Blender scenes

Owner-generated 3D assets for JARVIS. Each `<scene>.py` in this folder is a self-contained
Blender Python script that builds a scene from code and writes its outputs. Nothing here is
hand-modelled or downloaded, so the scripts are the source of truth.

| Scene | Outputs |
| --- | --- |
| `jarvis-core.py` | `jarvis-core.glb` (app model), hero stills (`hero-splash-1920x1080.png`, `hero-lock-1440x900.png`), state stills (`state-<idle\|listening\|speaking\|working\|offline>-512.png`) |

## Running

Requires Blender **5.2.x** (portable zip is fine). `scripts/blender-build.py` looks for it in
`JARVIS_BLENDER` first, then `%USERPROFILE%\tools\blender-5.2.3-windows-x64\blender.exe`. It
refuses any other version.

```powershell
.venv\Scripts\python.exe scripts\blender-build.py --list
.venv\Scripts\python.exe scripts\blender-build.py jarvis-core
.venv\Scripts\python.exe scripts\blender-build.py jarvis-core -- --only glb      # GLB only
.venv\Scripts\python.exe scripts\blender-build.py jarvis-core -- --device auto   # opt-in GPU
```

Arguments after `--` go to the scene script. `--out` is reserved, because the build tool
sets it. `jarvis-core` accepts `--only all|glb|hero|states` and
`--device CPU|auto|OPTIX|CUDA`. **CPU is the default**, because CPU renders are
byte-identical and, for this scene, about as fast as the GPU. The GPU is opt-in: `auto` tries
OptiX, then CUDA, then CPU. Each GPU backend must pass a 16x16 probe render, because a
backend can be listed and still fail to load its kernels. On the RTX 3060 laptop with driver
566.14, OptiX fails that probe and CUDA is used.

The tool runs `blender -b --factory-startup -noaudio --python-exit-code 1 --python
<scene> -- --out <staging> ...`:

- **Environment.** Only the variables Windows and the GPU driver need are passed through
  (system root, temp, profile and AppData folders). `PATH` is reduced to the system folders,
  and `BLENDER_USER_RESOURCES` points at `.runtime/blender/home`, so no user add-ons,
  preferences or startup files are loaded. API keys and `PYTHON*` variables never reach
  Blender.
- **Staging.** Blender writes into a freshly emptied `.runtime/blender/build/<scene>/`.
- **Logs.** Blender's full output goes to `.runtime/blender/logs/<scene>.log`. The last run
  overwrites it.
- **Review.** On success, outputs are copied to `.runtime/blender/review/` together with
  `<scene>.manifest.json`, which records the generator path and SHA-256, the Blender version,
  the scene arguments, and each output's size and SHA-256. The review folder always matches
  the last build: outputs that a later run no longer produces (for example after `--only
  glb`) are removed.

`.runtime/` is gitignored, so review outputs are never committed.

## Publishing

Outputs reach the repository only through an explicit publish:

```powershell
.venv\Scripts\python.exe scripts\blender-build.py jarvis-core --publish
```

Publishing does not run Blender. It copies the reviewed bytes as they are, and only for
outputs listed in `publish.json`:

```json
{ "format": 1, "scenes": { "jarvis-core": { "jarvis-core.glb": "src/assets/models/jarvis-core.glb" } } }
```

Destinations must be relative paths under `public/`, `assets/` or `src/assets/`.

Publishing is refused when:

- the scene has no approvals in `publish.json`;
- the scene script changed since the reviewed build;
- a reviewed output is missing or its hash differs from the manifest;
- the manifest's Blender version is not 5.2.x.

`publish.json` approves one output: `jarvis-core.glb` to `src/assets/models/jarvis-core.glb`.

## Determinism rules

Scene scripts must produce the same bytes from the same script and the same Blender 5.2.x
build:

- Start from `read_factory_settings(use_empty=True)`, and build everything from code.
- Never use random numbers, time, the date, or the machine or user name, in data-block names
  or anywhere else. Blender's embedded Python ignores `PYTHONHASHSEED`, so never depend on the
  iteration order of a `set` of strings.
- Fix the Cycles `seed` (no animated seed), the sample counts and the filter width. Turn off
  adaptive sampling.
- Run OpenImageDenoise on the CPU (`denoising_use_gpu = False`).
- Use the Standard view transform. Turn off dither and compositing.
- Turn off all `use_stamp*` metadata, and strip PNG text and EXIF chunks after each render,
  because Cycles writes render timings into them.
- Export the GLB with explicit options and no extras, animations or images. Export it before
  any render-only modifiers are added.

Checked on 2026-11-05 by running the scene twice with the same Blender build:

- `jarvis-core.glb` and every CPU render (the default) were byte-identical.
- With `--device auto` (CUDA), renders were visually identical but not bit-exact: at most
  6 pixels per image differed, by at most 1/255, because GPU float accumulation is not
  bit-exact.

## Asset ownership

Published outputs are **owner-generated**: the JARVIS owner made them with these scripts. No
third-party model, texture or font goes into them.

[`docs/ASSET_OWNERSHIP.json`](../../docs/ASSET_OWNERSHIP.json) must list every published
asset the renderer ships. `scripts/renderer-provenance.py` refuses any entry that:

- is not an observed renderer asset (`.glb` and similar files under `public/`, `assets/`
  or `src/`);
- has a `sha256` different from the shipped bytes;
- has a `decision` other than `"pending"`;
- has an `owner` other than `null`;
- has `license_evidence` other than `[]`.

So an entry for a generated asset must contain exactly these values:

| Field | Value |
| --- | --- |
| `path` | Repository path of the published file, for example `src/assets/models/jarvis-core.glb`. |
| `sha256` | SHA-256 of the published output. It equals the hash in the review manifest. |
| `origin` | `"owner-generated: art/blender/<scene>.py (sha256 <generator sha256>), Blender <x.y.z>"`. This records the **generator script**, its hash and the **Blender version**. |
| `owner` | `null` |
| `license_evidence` | `[]` |
| `decision` | `"pending"` |

`--publish` prints this entry ready to paste. Add it in the same commit as the published file.
Never add entries for outputs that are still only in `.runtime/blender/review/`: the
provenance check refuses entries whose path is not a shipped asset.

## jarvis-core

Design summary (the constants are at the top of `jarvis-core.py`):

- A unit-radius armillary instrument on `#05080C`.
- Lines: primary `#70E0ED`; secondary is the same cyan at 35% (display-space mix); offline
  lines are `#5B6B73` at 50%.
- Core faces: `#0A1418`.
- Core: a base icosahedron (20 faces, no subdivision) of radius 0.17. It is turned so that
  one face points straight at the default view: no vertex points at the camera, and the
  silhouette is a clean hexagon of facets.
- Beads: two solid cubes with 0.024 edges, in the primary colour, sitting on the middle ring
  at 0° and 180°.

**GLB.**

- Y-up, plain glTF: no Draco, meshopt, textures or extensions. About 21 KB.
- Root node `jarvis_core`, with child nodes `ring_outer`, `ticks_minor`, `ticks_major`,
  `arc_band`, `ring_mid` (with child `beads`), `ring_inner`, `core_edges`, `core_faces` and
  `reticle`.
- `core_faces` and `beads` are triangle meshes. Every other node is a `LINES` primitive
  (loose edges).
- Materials:
  - `line_primary`;
  - `line_secondary` (base-colour alpha 0.35, `BLEND`);
  - `core_face`;
  - `bead_face` (solid primary cyan for the bead cubes).
- Ring tilts are stored as node rotations, not baked into vertices: `ring_mid` is tilted 62°
  about X and `ring_inner` −48° about Y. A ring can therefore spin in its own plane (rotate
  about its local Z in glTF) or ease toward facing the camera (reduce the tilt).
- `core_edges` sits 0.4% outside `core_faces` to avoid z-fighting.
- The scene checks the GLB after export: node names, primitive modes, materials, no
  textures or Draco, and a size under 150 KB.

**Default view.** The GLB has no camera, so the app must reproduce this view. Every still
(except the hero lock) and the three.js size captures use it:

- **Camera direction (glTF / three.js, Y-up):** the camera sits at
  `d * (cos(el) * sin(az), sin(el), cos(el) * cos(az))` with `az = 24°` and `el = 12°`. It
  looks at the origin with up `+Y`. The model keeps its identity transform.
- **Lens:** 100 mm on a 36 mm sensor. For a square frame, the vertical FOV is
  `2 * atan(18 / 100)` = 20.41°. For a landscape frame, use `2 * atan(18 * h / w / 100)`.
- **Framing:** the outer reticle (r = 1.2) spans 228/512 of half the frame, so
  `d = (1.2 * 256 / 228) / tan(fov / 2)`.
- **Hero lock:** a touch calmer at `az = 20°`, `el = 10°`, with the core at 40% of the
  height.

In this view the middle ring reads as a diagonal orbit. Never flatten it into a horizontal
ellipse: at small sizes, a ring with a dot inside reads as an eye.

**Level of detail (for the app).**

- **Small, below 96 px:** show `ring_outer`, `ring_mid`, `beads`, `core_faces` and
  `core_edges`. Draw `core_edges` at secondary strength (35% opacity), so the core reads as a
  dim faceted crystal, never a bright dot. Frame the outer ring (r = 1.0) to 88% of the
  canvas: `d = 1.0 / (0.88 * tan(fov / 2))`.
- **Full, 96 px and up:** show every node, with `core_edges` at primary strength, and use the
  default framing above.

**States.** The review stills are posed with the `STATES` table in the script:

| State | Pose |
| --- | --- |
| idle | Small spin offsets |
| listening | Tilts eased to 35% of rest; arc band at full strength |
| speaking | Core at 108%; arc band at full strength |
| working | Arc band spun 40°; inner dashes spun half a dash |
| offline | Every line steel at 50%; core faces dark neutral; rest pose |

The stills only show one phase of each; the app animates them (see "In the app").

## In the app

`PresenceRing` (`src/app/PresenceRing.jsx`) renders the published GLB live with three.js
(`src/app/JarvisCore.jsx`, loaded lazily so three.js stays out of the main chunk) wherever
presence is shown at 64 px or more: the quick assistant and the context inspector. The GLB
is inlined into that chunk and parsed in memory (`src/app/coreAsset.js`), so the file://
renderer needs no fetch and no CSP change. Lines are 1 CSS px at every display scale.

The flat SVG ring stays in use:

- below 64 px;
- when the system asks for reduced motion;
- in low power: gaming mode, or the battery discharging at 20% or less;
- when WebGL is unavailable, the model cannot be parsed or the WebGL context is lost (one
  console warning, no retry for that mount).

At the small LOD (the 64 px quick assistant and inspector) the arc band and inner ring are
hidden, so each state has its own cue:

- **listening:** the rings tilt to face you;
- **speaking:** the crystal glows and swells with the voice (the voice level, or a slow
  synthetic pulse when no level arrives);
- **working:** arcs sweep the dial;
- **offline:** everything turns steel.

The state targets, easing time constants, level envelope, voice and sweep mappings, frame
rates, LOD rule and camera framing live in `src/app/coreModel.js`; `src/app/coreScene.js`
applies them to the scene. The loop runs at 15 fps when idle (its motion is a few pixels a
second, and the inspector can stay open all day) and 60 fps while live or easing, pauses
while the window is hidden or the core is off-screen, and stops once offline has settled.
