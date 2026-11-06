# Blender scenes

Owner-generated 3D assets for JARVIS. Each `<scene>.py` in this folder is a self-contained
Blender Python script that builds a scene from code and writes its outputs. Nothing here is
hand-modelled or downloaded, so the scripts are the source of truth.

| Scene | Outputs |
| --- | --- |
| `jarvis-core.py` | `jarvis-core.glb` (app model), hero stills (`hero-splash-1920x1080.png`, `hero-lock-1440x900.png`), state stills (`state-<idle\|listening\|speaking\|working\|offline>-512.png`), brand renders (`splash-core-720.png`, `lock-dial-720.png`, `setup-banner-410x1700.png`) |
| `jarvis-emblem.py` | App icon renders: `emblem-<256\|128\|96\|64\|48>.png` (full), `emblem-<40\|32>.png` (simplified), Android `android-foreground-<size>.png` and `android-monochrome-<size>.png` (108, 162, 216, 324, 432) |

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
sets it. `jarvis-core` accepts `--only all|glb|hero|states|brand` and
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

Destinations must be relative paths under `public/`, `assets/`, `src/assets/` or
`native/setup/` (the Setup window's packaged art).

Publishing is refused when:

- the scene has no approvals in `publish.json`;
- the scene script changed since the reviewed build;
- a reviewed output is missing or its hash differs from the manifest;
- the manifest's Blender version is not 5.2.x.

`publish.json` approves four `jarvis-core` outputs:

| Output | Published to |
| --- | --- |
| `jarvis-core.glb` | `src/assets/models/jarvis-core.glb` |
| `splash-core-720.png` | `src/assets/brand/splash-core-720.png` (startup splash) |
| `lock-dial-720.png` | `src/assets/brand/lock-dial-720.png` (lock screen dial) |
| `setup-banner-410x1700.png` | `native/setup/setup-banner.png` (Setup sidebar watermark) |

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

`--publish` prints these entries ready to paste, for renderer assets only (paths under
`public/`, `assets/` or `src/`): `native/setup/` files are not renderer assets and get no
entry. Add them in the same commit as the published files.
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

**Brand renders.** Published (see "Publishing"); RGBA on a transparent film, CPU, 128
samples, the same seed, filter, view transform and metadata stripping as the stills. The
constants are `SPLASH`, `LOCK_DIAL` and `BANNER` in the script.

| Output | What it shows |
| --- | --- |
| `splash-core-720.png` | The whole core in the idle pose, default view (the hero look), the rig (r = 1.2) spanning 86% of the frame. Shown at min(40vmin, 360px) on the startup splash (`index.html`). |
| `lock-dial-720.png` | Only the outer dial, head-on (`az = el = 0`), so the outer ring is a true circle: `ring_outer`, `ticks_minor`, `ticks_major`, `arc_band` and `reticle`. The ring is 576 px across (80%), and the centre is empty for the face camera (`AuthLock`). |
| `setup-banner-410x1700.png` | The same head-on dial, ring 600 px across, centred at (64, 1540), so it runs past the left and bottom edges. 2x art for the 205x850 Setup sidebar, with 38% opacity baked into the alpha. |

The two 720 px renders are shown at roughly half size, so their lines are thicker than the
stills' (`lines` in `SPLASH` and `LOCK_DIAL`): tube radii 2.25x for the splash, with bead
cubes 1.5x, and 2x for the lock dial, so primary lines read about 1.5-2 CSS px wide, like the
hero still at 1:1. The banner is shown at its 2x size and keeps the stills' widths. The GLB
and the stills are unaffected (the widths are reset after each brand render).

The splash keeps the hero materials (secondary lines pre-mixed toward `#05080C`, which is
the splash background). The dial renders use coverage instead: primary lines are the cyan
at full alpha and secondary lines at 35% alpha (times 38% for the banner), so they read the
same over any dark surface. Only the first surface a camera ray meets counts, so a tick
running into the ring never stacks above its alpha.

## jarvis-emblem

The app icon: the core's crystal cut into a letter J, inside the core's dial ring, on a dark
disc. It takes no scene arguments besides `--out`. The constants are at the top of
`jarvis-emblem.py`; the geometry is the approved mockup's 256-unit grid (x right, y down).

- **Camera:** orthographic and head-on, so the 256 grid fills the frame. Outside the disc
  the film is transparent (RGBA PNG).
- **Disc:** radius 124, `#0A1017`.
- **Dial ring:** radius 108, 3 wide, `#2A8A96`. Four cardinal ticks from radius 100 to 114,
  3 wide, `#70E0ED`. A bead of radius 6, `#70E0ED`, on the ring 40° clockwise from top.
- **Crystal J:** a real 3D chiselled letter whose cross-section is a roof: a ridge 10 units
  high along the stroke's centre line, falling to the outer and inner contours. The whole J
  is shifted by (-3, 0). Each stroke segment has two flat faces (ridge to outer, ridge to
  inner).
- **Facet tones:** flat emission, no lights, noise or shadows. `#B0EFF5` (facing the key
  light from the upper-left front), `#8AE8F2`, `#4FCFDD`, `#34AEBD` (away). The stem's left
  face is lightest and its right face `#4FCFDD`; on the hook the inner faces are lighter
  than the outer ones, and the two tip segments are a step lighter on both sides. The
  `FACET_TONES` table fixes the approved mockup's assignment per facet: no single light
  direction reproduces it on this roof, so tones are not computed at render time.
- **Ridge highlight:** a 1.6-wide `#E6FBFD` line along the ridge, round joins.
- **Variants:**
  - full (256, 128, 96, 64, 48): everything above;
  - simplified (40, 32): no ticks, no ridge highlight, ring 1.4/32 of the size wide, bead
    radius 1.5/32 of the size (the mockup's 32 px symbol);
  - Android foreground: J, ridge highlight, ring and bead, no disc, on a transparent
    108-unit canvas. The bead's outer edge sits 32 units from the centre, inside the
    66-unit safe zone (radius 33);
  - Android monochrome: the same J, ring and bead silhouette in flat white.
- **Render:** Cycles on the CPU, 256 samples, seed 0, no denoising, a one-pixel box filter
  (each pixel is the artwork's exact area coverage, so edges stay crisp), each size rendered
  at its exact pixel size.

`scripts/build-icons.py` turns the reviewed renders into the icon files (it draws the 16,
20, 24 and 32 px frames itself, on the pixel grid) in `.runtime/icons/review/`, and
`scripts/icon-review.cjs` captures a review sheet from them offscreen. The scene's renders
are never published directly (nothing from it is in `art/blender/publish.json`): the icon
files are, through `build-icons.py --publish` (see "Icons" below).

### Icons

```powershell
.venv\Scripts\python.exe scripts\blender-build.py jarvis-emblem   # renders, for review
.venv\Scripts\python.exe scripts\build-icons.py                   # icon files, for review
node_modules\.bin\electron scripts\icon-review.cjs                  # review sheet
.venv\Scripts\python.exe scripts\build-icons.py --publish         # after the owner approves
```

The review build writes, into a freshly emptied `.runtime/icons/review/`, with a
`manifest.json` (each file's size, SHA-256 and pixel sizes or ICO frames; the hashes of
`build-icons.py`, the scene script and the scene manifest; the Blender version):

| Output | What it is | Published to |
| --- | --- | --- |
| `jarvis.ico` | App icon: pixel frames 16, 20, 24; renders 32 to 256 | `assets/icons/jarvis.ico` (window, taskbar, Alt-Tab) |
| `jarvis.png` | The 256 render | `assets/icons/jarvis.png` (window icon off Windows) |
| `tray/jarvis-<state>.ico` | Tray icons, pixel frames 16, 20, 24, 32: `ready`, `talking`, `calls`, `attention`, `paused` | `assets/icons/tray/` |
| `ui/mark-<24\|32\|48\|64\|96>.png` | In-app mark: 24 is the ready pixel frame, 32 the simplified render, 48 and up the full renders | `src/assets/icons/mark-<size>.png` |
| `setup/emblem-128.png`, `setup/emblem-64.png` | Setup header renders | `native/setup/emblem-128.png` (64 is review only) |
| `android/res/...` | Adaptive launcher icon XML, background colour, foreground and monochrome mipmaps for mdpi to xxxhdpi | `android/app/src/main/res/` |

`--publish` mirrors `blender-build.py --publish`. It does not rebuild: it copies the reviewed
bytes as they are, and only to the destinations approved in `art/icons/publish.json`:

```json
{ "format": 1, "outputs": { "jarvis.ico": "assets/icons/jarvis.ico", "...": "..." } }
```

Destinations must be relative paths under `assets/`, `src/assets/`,
`android/app/src/main/res/` or `native/setup/`. Every check runs before anything is copied.
Publishing is refused when:

- `art/icons/publish.json` is missing, malformed or empty, or a destination or output name
  is outside those folders, absolute, has a drive, a backslash, or an empty, `.` or `..` part;
- there is no review build, or its `manifest.json` is not a `build-icons.py` manifest;
- `scripts/build-icons.py` or `art/blender/jarvis-emblem.py` changed since the review build,
  or the renders were not made with Blender 5.2.x;
- a reviewed file is missing or its size or SHA-256 differs from the manifest;
- the approvals, a reviewed file or a destination goes through a symlink or junction, or a
  destination resolves outside the repository.

Each copy is checked against its reviewed hash. `--publish` then prints the
`docs/ASSET_OWNERSHIP.json` entries for the renderer assets among the destinations (paths
under `assets/`, `public/` or `src/`; the Android and Setup files are not renderer assets,
and `scripts/renderer-provenance.py` refuses entries for anything else). Their `origin`
names both generators:

```text
owner-generated: scripts/build-icons.py (sha256 <hash>) from art/blender/jarvis-emblem.py (sha256 <hash>), Blender 5.2.3
```

Replace or add those entries in the same commit as the published files.
`tests/test_build_icons.py` pins the SHA-256 of every published file from the approved
review build, so a later review build or publish that changes their bytes fails the tests.

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
