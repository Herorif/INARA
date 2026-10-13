# Native Windows resident

Implemented 13–14 October 2026. `npm start` and `scripts/start.ps1` now launch the native resident through the existing Python 3.12 environment. `npm run dev` keeps Vite and the foreground native host running for development. `npm run start:legacy` retains the older Electron controller for comparison and recovery. Quit one host before switching: both use port 8000.

## Lifetime and ownership

`backend/resident_main.py` runs a Win32 message loop, tray and Ctrl+Shift+Space registration on the main thread. The existing ASGI core runs on an asyncio thread in that same Python process. Windows' virtual-environment launcher is a separate small process and is included in resource accounting. No Electron process or resident Socket.IO polling client is needed while the workspace is closed.

Opening the workspace launches `electron/native-main.cjs`, with sandboxed renderer, isolated preload, the existing responsive command deck and lazy feature panels. Closing the titlebar window disconnects the renderer and desktop control channel, then exits Electron. Reopening uses the same live core, protected database and desktop identity. A named mutex prevents another host for the same profile; a second launch posts an open request to the existing tray window.

The workspace process and descendants are assigned atomically to a Windows kill-on-close Job Object at creation. The host owns its job handle, so closing the workspace or terminating the host cleans up its workspace tree. It never searches for arbitrary Electron/Python processes to terminate. [Windows job ownership](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).

The random core token travels over an anonymous inherited stdin pipe. Only that pipe and null output handles are inherited; the workspace receives a restricted Windows environment without provider credentials or the session token. Preload obtains renderer bootstrap through trusted IPC. Tokens are absent from command-line arguments, persistent files and child environment variables. The UUID and gaming preference remain metadata; private records retain the Windows DPAPI persistence contract. [Handle inheritance](https://learn.microsoft.com/en-us/windows/win32/procthread/inheritance).

The profile remains `%APPDATA%\inara`, preserving Electron file-origin storage. Existing `resident-identity.json` is adopted. If metadata is absent, the renderer's existing local-storage UUID registers the resident identity. Corrupt metadata is preserved and blocks startup for recovery instead of silently assigning another owner. Native connections and desktop controls reject another owner; only the authenticated workspace control role can change desktop lifetime/preferences.

Startup and workspace registration have bounded timeouts, with generic status and tray retry. A busy port leaves the other listener alone. Explicit quit requests core shutdown, closes the owned workspace job, cancels core tasks and waits up to five seconds before the process exits. This is not a promise that an unfinished external tool operation can be rolled back; uncertain requests retain the existing no-replay recovery contract.

## Reminders and gaming

Reminders prefer the active renderer. When it is closed, the native tray handles the same owner's queued delivery directly. The workspace's control socket is excluded from delivery selection. The store records receipt only after a generic tray notice is queued; it does not record that the user read it. Private task text is absent from the notice. Unfinished deliveries restore when the workspace opens.

Manual gaming mode persists across restart, suppresses tray notices, closes heavy panels and blocks core heavy activation. A renderer cannot clear a native gaming selection by requesting Studio mode. CPU/GPU admission, automatic foreground-game detection and model unloading remain future work. [Native notification fields and quiet time](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/ns-shellapi-notifyicondataw).

## Runtime upgrade and verification

Electron is pinned to **44.7.0**, replacing 28.3.3. The release and dependency lock are recorded, and the actual new binary passes hidden responsive-layout, accessible-control, lazy-asset and local tracking-model initialization checks. The old controller also passes its isolated integration check. [Electron release](https://releases.electronjs.org/release/v44.7.0).

69 Python checks cover core/persistence plus metadata preservation, desktop-role authorization, native notification receipt and real Win32 job cleanup. The job check spawns a temporary parent/descendant pair and verifies both exit when the job closes. It also verifies pipe bootstrap and the absence of credentials in argv/environment. Eight frontend state/lifecycle checks pass, as do production build, Ruff and dependency consistency. Existing Vite CJS/browser-data, lazy CAD chunk-size and Starlette/httpx deprecation warnings remain.

`scripts/verify-native.py --idle-seconds 600 --failure-recovery` uses a fresh isolated profile, projects, settings and DPAPI database. It verifies busy-port failure/retry, native hotkey-message routing, single-instance reopen, two real hidden workspace opens/closes, same-core/identity retention, reminder receipt and gaming guards. It then samples resident working set/private bytes and CPU every five seconds, including the virtual-environment launcher. The final short lifecycle rerun also verifies owned-workspace crash/transport cleanup and graceful core stop. Generic balloon presentation is suppressed; no provider, microphone, camera, game, printer or phone action runs. CI runs a short lifecycle sample; remote CI remains unverified.

Hotkey registration/message routing and notification queuing are tested. Actual keyboard invocation, visual tray/balloon acceptance under Windows quiet hours, signed installer packaging and startup installation remain owner acceptance/release work. The user explicitly deferred the real-game benchmark. Idle results do not establish game FPS, thermal or GPU behavior, or memory after activating optional legacy workers.

## Resource evidence

The final **600-second** run samples both the native core/tray and its owned virtual-environment launcher:

| Measurement | Result |
| --- | --- |
| Aggregate working set, mean / peak | **64.86 / 65.30 MB** |
| Aggregate private bytes, peak | **47.54 MB** |
| Average CPU, one core = 100% | **0.3802%** |
| Resident Electron processes | **0** |
| First workspace / reopen after core readiness | **2.516 / 2.188 seconds** |

The local idle run is below the planned 150 MB / 1% CPU target. [Recorded samples](qa/native-resident-idle.json) include per-process measurements. It does not complete the game/installed-release acceptance gate. The first core-only ten-minute run averaged 59.67 MB. The earlier retained Electron snapshot was approximately 400 MB for Electron alone, plus its separate backend; different measurement methods prevent an exact percentage comparison.

Working-set sums include shared pages, so private bytes are reported separately. These measurements use the local development environment, not an installed release on the owner's Legion. Paid provider and optional creative/voice models were not initialized.

## Next bounded task

The offline CAD worker, real preview/export loop, protected job ledger and optional blueprint adapter are implemented in [CAD Studio](CAD_STUDIO.md), including warmed resource recovery. Typed scene assembly and controlled Blender execution are next. Image generation and further vision workers follow the same lifecycle. Android pairing/calls remain separate milestones; WhatsApp drafting/sending stays excluded until specifically requested.
