# Resident assistant and command deck

Implemented 13 October 2026. The desktop now uses an independent resident controller and a new JARVIS-inspired command deck. API configuration remains deferred.

## Using it

Run `scripts/start.ps1`. The workspace opens with command, Studio and connection views. The close button destroys the renderer and leaves the backend and tray controller running. Reopen from the tray or **Ctrl+Shift+Space**; if the hotkey is unavailable, the interface says to use the tray. **Quit INARA** in navigation or the tray ends the backend. OS startup installation is not enabled.

The tray retains the same client identity as the original desktop, preserving session ownership. First launch adopts the existing renderer UUID; subsequent launches supply it through the preload bridge. Only metadata UUID/gaming preferences are saved in the resident identity file. Private session/reminder payloads retain the protected persistence contract.

Backend readiness is bounded and checked against the spawned instance ID. A failed startup leaves visible status and a tray retry action. Single-instance locking reopens the existing workspace. Explicit quit requests authenticated graceful shutdown, with a two-second fallback confined to the owned child process tree. Duplicate quit requests wait for the same cleanup. Renderer isolation and sandboxing stay enabled; navigation is confined to the application and external links pass through a validated bridge.

## Reminders without an open window

The main process maintains a scoped resident socket independently of the renderer. Delivery prefers an open renderer; after closing, the resident receives the same identity's pending delivery. Windows tray balloons show a generic reminder notice without private task text and respect quiet time. Receipt records that the notice was queued, not that the user read it. Opening the workspace restores unfinished alerts; dismissal is a separate durable action. Other platforms may use native notifications when supported.

Gaming mode suppresses resident reminder balloons while retaining the delivery for later viewing. The laptop must be awake and the application running. This does not install an OS wake scheduler or guarantee display during Windows notification suppression. [Electron tray behavior](https://www.electronjs.org/docs/latest/tutorial/tray), [Tray balloons](https://www.electronjs.org/docs/latest/api/tray).

The redesigned reminder panel can schedule directly without an AI key. It uses the common validated dispatcher and configured approval rules, with Kuala Lumpur time, recurrence, cancellation and private persistence. Advanced routines remain accessible through the retained adapter.

## Visual and code changes

`src/App.jsx` is now a small entry point. `src/app/` owns the command deck, vector assistant core, responsive modal host and design tokens. Feature folders own reminder creation and camera lifecycle. `electron/desktop.js` owns desktop integration; `electron/resident.js` isolates lifecycle/readiness policy for deterministic tests.

The visual direction uses deep navy surfaces, cyan instrumentation, warm accents, restrained motion, clear typography and a persistent navigation rail that adapts to narrow screens. Command, Studio and Connections are functional views. Keyboard navigation, visible focus, modal focus containment, Escape cancellation, accessible names for icon controls and reduced-motion rules are implemented. Screenshots in `docs/qa/` show rendered output rather than design mockups. Some optional adapter panels retain their previous interior layout until their capability migration.

CAD, device panels, settings and camera are lazy imports. Tracking loads only after its separate activation. The initial JavaScript entry is approximately **241 KB uncompressed / 76 KB gzip**, compared with approximately **1.37 MB / 383 KB** previously. CAD remains a separate approximately 902 KB chunk; the optional tracking runtime/model add installation assets but are not fetched by the initial workspace. No external font or decorative texture request is needed for the new shell.

## Resource policy and measurements

Explicit resource states are `resident`, `chat`, `studio` and `gaming`. Closing or enabling gaming stops voice and scene-watch activity; gaming/resident block new legacy voice, CAD, browser and frame activation. Text, persistence and reminders remain available. Camera preview is separately activated, releases late permission acquisitions after closing, and shares no frames with the backend. Local hand landmarks use matched, bundled MediaPipe assets, CPU execution and an up-to-ten-Hz inference loop. Bundled model initialization is verified in packaged Electron using an empty test stream; the WASM loader uses a scoped local blob to avoid the file-URL fallback failure. Real camera/model accuracy and long-running stability have not been verified; the tests do not acquire a camera.

Gaming selection is manual. Automatic foreground-game detection, GPU/VRAM admission control, worker process isolation, thermal policy and model unloading remain future work. The shell's memory display covers Electron processes, not a claim about the entire assistant.

The native integration run showed the renderer disappearing after close and the same backend surviving reopen. Its immediate working-set snapshot still showed approximately **400 MB across retained Electron processes**, plus the separately sampled backend. Working-set sums can double-count shared pages and fluctuate; this is not a ten-minute idle measurement. **The architecture's 150 MB resident target is not met.** Prototype a lean Windows resident host with Electron retained only for an open workspace before adding persistent heavy workers. Do not describe this Electron foundation as the final lightweight resident implementation.

## Verification

- 61 deterministic Python tests cover the existing core/persistence plus resource gating, recipient handoff, authenticated shutdown and AI-independent reminder creation.
- Eight Node tests cover renderer/reminder state, camera acquisition cleanup, readiness failure, close/reopen and duplicate quit.
- The production build and Python lint/dependency checks pass.
- `scripts/verify-workspace.cjs` renders a hidden isolated window, verifies desktop/tablet/narrow layouts and modal behavior, and checks that CAD/tracking assets are absent at startup. It also verifies that opening camera preview does not load tracking, and initializes the local tracking model using an empty test stream. It saves screenshots under `.runtime/ui-qa/`.
- `scripts/verify-resident.cjs` uses fresh isolated projects, settings and storage. Real Electron/backend close/reopen, resident reminder receipt, gaming state and graceful quit pass. Windows balloon presentation is stubbed, so actual notification display and hotkey conflict behavior still need owner acceptance checks.

Both scripts require Electron application mode: clear `ELECTRON_RUN_AS_NODE` before launching the executable. They use no paid provider calls, camera/microphone sessions or printer actions. CI includes the deterministic suite and hidden renderer checks; its remote run remains unverified.

The next task is resident memory reduction and host comparison, followed by isolated CAD/Blender/image workers. A supported Electron upgrade is a release gate. Android pairing, call handling and WhatsApp replies are not introduced here.
