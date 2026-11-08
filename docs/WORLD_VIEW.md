# World view

World view shows the open-source [God's Eye View](https://github.com/bilawalsidhu/gods-eye-view)
3D globe (GEV) inside JARVIS: Studio > World. GEV runs on this PC as a small sidecar that
JARVIS starts when you open the page and stops when nothing uses it. JARVIS never downloads or
installs it; you set it up once with the script below.

Code: `backend/services/world_view.py` (the sidecar, its routes and the view push contract),
the `world.*` settings in `backend/services/settings.py`, and `src/features/world/` (the page).

## Setting it up

Run the setup script yourself, from the JARVIS folder:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-world-view.ps1 -WhatIf
powershell -ExecutionPolicy Bypass -File scripts\install-world-view.ps1
```

`-WhatIf` prints every step without downloading or changing anything. Without it the script:

1. **Node 24.** Downloads `node-v24.22.2-win-x64.zip` from nodejs.org, checks its SHA-256
   (`ca1bff5d8ead13c9f2ea404a176db46bd430704d5b5113734049fa365e7799e2`) and unzips it to
   `%USERPROFILE%\tools`. A file with any other hash is not unzipped. This Node is used only
   by World view; JARVIS's own toolchain keeps its own Node.
2. **God's Eye View.** Fetches commit `52187c91d188504188ea9e9ae33e5b6e24cab7f2` (shallow,
   with Git's schannel TLS backend, so the Windows certificate store is used) into
   `%USERPROFILE%\tools\gods-eye-view`, and checks it out. It stops if that folder isn't a Git
   checkout or has local changes.
3. **Packages.** `npm ci --ignore-scripts` with `PUPPETEER_SKIP_DOWNLOAD=true`, run by that
   Node (npm's own `npm-cli.js`, not `npm.cmd`). Package install scripts don't run, and no
   browser is downloaded for GEV's test tools.
4. **Build.** `npm run build` (the app, in `dist/`) and `npm run build:panel` (`dist/panel/`).

It is safe to run again: a step that is already done says so and is skipped. `-Force`
reinstalls the packages and rebuilds. It needs Git for Windows.

## Settings (`world.*`)

| Setting | Default | Notes |
| --- | --- | --- |
| `root` | `%USERPROFILE%\tools\gods-eye-view` | A full path; a leading `%USERPROFILE%` is expanded when read. |
| `node` | `%USERPROFILE%\tools\node-v24.22.2-win-x64\node.exe` | Must be an `.exe`: Node runs directly, never through a shell. |
| `port` | `4173` | 1024 to 65535, never 8000 (the core). Loopback only. |
| `idle_minutes` | `10` | 1 to 1440. |
| `enabled` | `true` | Off: World view never starts, and a running globe stops. |

A malformed saved value reads as its default. The packaged renderer's CSP allows framing only
`http://127.0.0.1:4173` (see Framing), so the page works on another port only in the dev
renderer.

## The sidecar

- **Status** (`world_status`): `not_installed` with a reason (`node_missing`, `root_missing`
  or `dist_missing`, the last also when `node_modules/vite` is missing), `stopped`,
  `starting`, `ready`, or `error` with a plain message. Diagnostics carry the exit code and
  the last stderr lines (at most 1,500 characters, colour codes removed, the profile folder
  shown as `%USERPROFILE%`, secret shapes masked). Logs carry only the state and exit code.
- **Start** (`world_start`, sent by the World page when it opens; later the brain): refused
  when `enabled` is off, when GEV isn't installed, and in gaming or resident mode (a heavy
  studio resource, through the resource governor's `require_heavy`). Then:
  - if something already answers on `127.0.0.1:<port>`, the status is the error
    "Port 4173 is in use by another program." (with the real port) and nothing starts;
  - otherwise Node starts with an explicit argv, `node.exe <root>\node_modules\vite\bin\vite.js
    preview --host 127.0.0.1 --port <port> --strictPort`, cwd `root`, no shell and no npm;
  - Windows: it starts suspended, joins a kill-on-close Job Object and then runs, so Node and
    anything it starts die with the core, even if the core crashes;
  - the environment is minimal: `SystemRoot`, `SystemDrive`, `windir`, `TEMP`, `TMP`,
    `USERPROFILE`, `LOCALAPPDATA`, `APPDATA`, the processor variables, a `PATH` of Node's
    folder and System32, `NO_COLOR`, `GEV_ALLOWED_HOSTS=127.0.0.1,localhost` and
    `GEV_EMBED_FRAME_ANCESTORS=file: http://localhost:5173`. `OPENAI_API_KEY` and
    `GEMINI_API_KEY` are set empty, so GEV's own voice and chat agent stay unconfigured (a
    `.env` in the GEV folder can't fill them in either: GEV never overrides a variable that is
    set). JARVIS is the only voice. No JARVIS key or token is passed.
- **Health**: GET `/` (HTML) and `/api/mapillary/status` (JSON, local) must both answer 200;
  polled every 250 ms for at most 60 s ("The globe didn't start within 60 seconds."). An exit
  while starting is "The globe stopped while starting."; later, "The globe stopped
  unexpectedly."
- **Stop**: the page's Stop (`world_stop`), `idle_minutes` with no World page open and no brain
  use, `enabled` turned off, gaming or resident mode (at once, from `restrict_resources`), and
  core shutdown (`Application.close`). Stop terminates the job and waits up to 5 s for Node to
  exit. Pending views fail with `world_stopped` and an active tour ends.
- **Page presence**: the World page sends `world_status {page: true}` when it opens and every
  30 s, and `{page: false}` when it closes. A page that stops reporting counts as closed
  after 120 s.

## The World page

Studio's tabs: 3D studio, Images, Vision, Web, **World**, Artifacts. World is a heavy feature,
so gaming mode disables the tab and closes the page, and opening it sets the studio resource
state. The header has the HUD label WORLD, "God's Eye View" and a chip: Not set up, Starting,
Ready, JARVIS is driving (a tour is active) or Error. On the right, Open in browser (the full
app at `http://127.0.0.1:<port>/` in the system browser) and Stop (which also closes the page).

- **Not set up**: "World view isn't installed yet", one line about the globe and the one-time
  download you approve, and "How to set it up" with the script's steps.
- **Starting**: the globe area dimmed, with "Starting the globe on this PC…".
- **Ready**: the embedded globe fills the page.
- **Error**: the globe area dimmed, with the message.
- **Tour bar**: docked at the bottom of the globe while the core says a tour is active, in the
  talking overlay's style: a 44 px presence ring, "TOUR · <title>" in accent, the caption of
  what JARVIS is saying, and Stop tour.

## Framing

The globe is an iframe of `http://127.0.0.1:<port>/?embed=1` (GEV's embed mode: only the
globe).

- `sandbox="allow-scripts allow-same-origin"`: GEV needs scripts and its own origin (its
  workers, storage and the replies it posts). No top navigation, popups, forms or downloads.
- `allow="camera 'none'; microphone 'none'; geolocation 'none'; display-capture 'none'"`, and
  the workspace's permission handlers grant nothing to any subframe anyway.
- `referrerpolicy="no-referrer"`.
- JARVIS's packaged CSP (`vite.config.js`) adds only `frame-src http://127.0.0.1:4173` to the
  workspace page; the talking overlay's policy has no frame source. The dev renderer has no
  CSP.
- GEV keeps `X-Frame-Options: DENY` and `frame-ancestors 'none'` unless
  `GEV_EMBED_FRAME_ANCESTORS` names the framing pages, and then only for embed documents.
  JARVIS sets it to its two renderer origins:
  - dev: `http://localhost:5173`, the Vite dev server;
  - production: the workspace loads `dist/index.html` over `file://`, whose origin
    serialises as `file://`. CSP has no source expression for one file URL, so it is named by
    its scheme, `file:`. That lets any local `file://` page frame the embed and change what it
    shows; the embed holds no keys and GEV's other documents are never framable.

  Checked in a hidden Electron window: a `file://` page with this CSP framed the real GEV,
  got `gev:ready`, posted a view and got `gev:view-applied` with `ok: true`.
- **Message bridge** (`src/features/world/worldBridge.js`): a message is read only when its
  source is the iframe's own window and its origin is exactly `http://127.0.0.1:<port>`.
  Views wait for `gev:ready`, then go out as `{type: 'gev:view', id, view}` to that origin
  only. Each `gev:view-applied` for a view the bridge sent is relayed once.

## The view push contract (for the brain)

- `app.world.show_view(view, *, title=None)`: checks the view (a JSON object of at most
  16 KiB; never the `cctv` or `alpr-cameras` layers), starts the globe if needed and waits
  until it is ready, then sends `world_view {id, view, title}` to the owner's renderer whose
  World page is open (else the first owner renderer, which opens the page). It awaits that
  renderer's `world_view_result {id, ok, steps}` for 15 s (`world_view_timeout` after) and
  returns `{ok, steps}`. It needs the unlocked owner and refuses in gaming mode.
- `app.world.set_tour(active, *, title=None, caption=None)` sends `world_tour {active, title,
  caption}` to the owner's renderers (the tour bar). `world_tour_stop` (Stop tour) calls
  `app.world.on_tour_stop` (set by the tour's driver), then ends the tour.
- `app.world.touch()` counts as brain use for the idle timer; `ensure_ready()` starts the
  globe and waits.

## Routes

All five are owner-only (the authenticated, unlocked desktop owner's renderer) and in
`docs/ROUTE_POLICY_MATRIX.json`: `world_status`, `world_start`, `world_stop`,
`world_view_result` and `world_tour_stop`. Events to the owner's renderers: `world_status`,
`world_tour` and (to one renderer) `world_view`.

## Licences

- God's Eye View's code is MIT (© 2026 Bilawal Sidhu).
- Some data it bundles or loads is not: for example TeleGeography's submarine cables
  (CC BY-NC-SA 3.0) and the Bhote Koshi event pack (CC BY-NC 4.0) are non-commercial, and
  OpenStreetMap-derived data is ODbL 1.0 (attribution and share-alike). See GEV's
  `DATA_SOURCES.md` and `THIRD_PARTY_NOTICES.md`. Use World view for personal use only.
- Map imagery keeps its providers' attribution on the globe.

## Privacy

- Everything runs on this PC on 127.0.0.1. GEV fetches public feeds (flights, ships,
  satellites, weather and so on) and map tiles from their providers as the layers need them.
- GEV's voice and chat agent are off: no AI keys are passed, and JARVIS is the only voice.
- CCTV and licence-plate cameras are off: JARVIS never turns on the `cctv` or `alpr-cameras`
  layers (`show_view` refuses a view with them), and the embedded globe has no layer controls.
  GEV's CCTV and licence-plate tools (`find_cctv_cameras`, `get_cctv_snapshot`,
  `find_alpr_cameras`) stay off too: World view doesn't expose GEV's tools, and the MCP
  connector that will (W3b) is to deny them.
- Open in browser shows the full GEV app, where its own controls are yours to use.
