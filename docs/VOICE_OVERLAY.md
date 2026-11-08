# Talking overlay

While a tray voice session runs ("Talk to JARVIS" or "Hey Jarvis"), the core shows a small
always-on-top panel with the live JARVIS core and live captions. It is a separate Electron
process that never takes keyboard focus and closes itself when the conversation ends.

## Files

| File | Role |
| --- | --- |
| `electron/overlay-main.cjs` | Entry. Reads and validates the bootstrap from stdin, then calls `start()`. |
| `electron/overlay-app.cjs` | `start(bootstrap, options)`: the window, the core socket and IPC. Used by the entry and the harness. |
| `electron/overlay-policy.cjs` | Pure helpers (no electron): bounds, bootstrap and payload validation. |
| `electron/overlay-preload.js` | `window.jarvisOverlay`: `onSnapshot`, `onLevel`, `ready`, `pointer`, `stop`, `open`, `done`. |
| `overlay.html`, `src/overlay/` | The renderer: `main.jsx`, `OverlayApp.jsx`, `overlayModel.js` (pure snapshot → view and close countdown), `overlay.css`. |
| `scripts/verify-overlay.cjs`, `scripts/fake-overlay-core.py` | The harness and its fake core. |

`overlay.html` is a second Vite build input; `dist/overlay.html` gets its own CSP meta (the
workspace policy with `connect-src 'self'` only, because the renderer never opens a socket).
`scripts/build-desktop-bundle.cjs` bundles `overlay-main.cjs` (with `overlay-app.cjs`,
`overlay-policy.cjs`, `security.cjs` and socket.io-client) and copies `overlay-preload.js`;
desktop pilots require `electron/overlay-main.cjs`, `electron/overlay-preload.js` and
`dist/overlay.html`.

## Contract with the core

**Bootstrap** (one JSON object on stdin, read to EOF):
`{"token", "clientId", "profile", "core", "dev"}`. The token must be 64 lowercase hex, the
client id a UUID, the profile an absolute path (the overlay's own userData), `core` exactly
`http://127.0.0.1:<port>` or `http://localhost:<port>`, and `dev` a boolean. Anything else
exits with code 1 and one line naming the failing field (never the token).

**Socket** (main process only): `io(core, { auth: { token, client_id, role: "overlay" }, reconnection: false })`.

- In: `voice_overlay` snapshots and `voice_level` (`{level}`, 0..1).
- Out, with ack and no payload: `overlay_stop` (Stop talking) and `overlay_open` (Open JARVIS).

Main validates every payload before relaying it over IPC:

- Snapshots need every contract field with the right type and a known `state` and end
  `kind`, otherwise they are dropped.
- Text is truncated (owner words 300 from the start, JARVIS words 600 keeping the newest
  end, end message 300, never splitting a surrogate pair) and control characters other than
  tab and newline are removed. Unknown fields are dropped.
- An `end` forces state `ended`; `ended` without an end reads as a quiet end.
- Levels are clamped to 0..1; non-numbers are dropped.
- `design` (true while the local owner has a live design, docs/LIVE_DESIGN.md) passes through
  as a boolean, and reads as false when absent. The core publishes a new snapshot when it
  changes during a session: `LiveDesigns` tells `VoiceOverlay.design_changed` when a design
  starts or ends. `local_voice` carries it too.

## When the overlay opens: the speaking core

The workspace's Assistant view has its own speaking core (`src/app/Conversation.jsx`, rules in
`src/app/stageModel.js`), so the overlay is not needed while the owner is looking at it.

- **To renderers.** `services/voice_overlay.py` also sends the owner's authenticated
  `renderer` sockets `local_voice` (the snapshot above plus `"source": "tray" | "wake" |
  "briefing"` (P2, the morning briefing), how
  the session started; coalesced the same way, the end at once, and sent to a renderer that
  connects while a session runs) and `local_voice_level` (`{level}`, on the same schedule as
  `voice_level`, then one final 0.0). The speaker's level is measured while an overlay or such
  a renderer is connected during the session. The renderer validates both with
  `src/features/voice/localVoice.js` (the same rules as `overlay-policy.cjs`, plus `source`)
  and keeps them in the store (`localVoice`, `localVoiceLevel`, `localVoiceEndedAt`),
  cleared on disconnect.
- **Stage visibility.** The Conversation view sends `voice_stage` `{visible}` (strict, owner
  renderer sockets only, allowed while locked, ACK `{ok}` or `{ok: false, code, message}`) 250
  ms after a change and after every (re)connect, and `{visible: false}` when it unmounts.
  Visible means the Conversation view is mounted (the Assistant page with no feature open),
  the document is visible, the window has focus and the app is not locked. The core keeps the
  latest value per socket and forgets it on disconnect; the stage counts as shown when any of
  the authenticated owner's renderer sockets reports visible.
- **The rule.** A tray session that starts while no stage is shown opens the overlay
  (`started`) as before. One that starts while a stage is shown does not: the overlay is owed,
  and no `voice_overlay` or `voice_level` goes to overlay sockets meanwhile (so an overlay still
  fading out from the last session never shows this one). As soon as no stage is shown (the
  window hidden, minimised or unfocused, another page, or the renderer gone) the host is told
  `started` and the overlay shows the session. At most one overlay per session; once open it
  stays for the rest of the session and is never closed because the stage came back.
  `ended` and `disabled` are unchanged.
- **Stop talking.** The stage's button sends `local_voice_stop` (no fields, owner renderer
  only, allowed while locked): the tray's "Stop talking", `VoiceService.stop_local()`. Window
  voice stops through the renderer's own live voice (`voice_stop`).

Captions are never logged on either side. Tests: `tests/test_speaking_core.py` and
`tests/test_speaking_core.mjs`.

## Window

- Frameless, transparent (`#00000000`), no shadow, not resizable or movable, `focusable: false`,
  skip taskbar, always on top at the `screen-saver` level, content protection on (hidden from
  screen sharing and screenshots), sandboxed with context isolation, no background throttling.
- Placed on the display nearest the cursor at start, inside its work area (which excludes the
  taskbar):
  - 608 × 156, centred, bottom edge on the work area's bottom edge;
  - work areas narrower than 640 px use their width minus 32.
- The 560 px panel sits 16 px above the window's bottom edge and grows upward.
- Click-through (`setIgnoreMouseEvents(true, { forward: true })`) except while the pointer is over
  the panel; the renderer reports enter and leave.
- Shown with `showInactive()` only after the renderer reports its first snapshot painted.
  Never focused.
- Every permission request and check is denied, new windows are denied, navigation away from
  the overlay page is blocked, and every IPC message must come from the overlay page's main
  frame (`security.trustedSender`).

## Panel

The panel holds the core (PresenceRing at 64 px), the captions and the buttons:

- **Ring:** connecting, thinking and working show "working"; listening, speaking and ended show
  listening, speaking and offline.
- **Top line:**
  - "Connecting…" or "Listening" in text-3;
  - otherwise the owner's words in curly quotes, with a leading "Hey Jarvis" removed: text-1
    while they speak, text-2 once final, text-3 once JARVIS's words show;
  - "Voice is off" after a quiet end; hidden after an error.
- **Main caption** (up to 3 lines, newest at the bottom, a 12 px top fade only while clipped):
  - "Thinking…" or "Working on it…" until JARVIS has words;
  - JARVIS's words in text-1 while speaking and text-2 otherwise;
  - an error end's message in warn.
- **Buttons** (Stop always sits at the far right; "Open JARVIS" comes before it):
  - Stop until the session ends;
  - "Open JARVIS" when approval is needed or JARVIS is designing (`design`), and after a quiet
    end. After the end it also fades the panel out. While designing, it opens the workspace,
    whose Assistant page shows the live design beside the conversation.

Captions are rendered as text only.

## Closing

The renderer model decides when to close, then calls `done()`:

- A quiet end holds 4 s, an error end 8 s, then the panel fades out (180 ms).
- A `now` end clears all text in the same frame and fades at once.
- The pointer over the panel pauses the countdown; leaving resumes it with at least 2 s left.
- A new running session (a different session id) during the hold or fade cancels the close.

Main also quits on its own:

- A lost or refused core connection fades the window out over 1 s with no text change, then
  quits.
- No valid snapshot within 10 s of start quits too.

Exit codes:

- 0: `done()`, or the core closing the socket.
- 1: a bad bootstrap, a refused or dropped connection, no snapshot, a load failure, or a
  renderer crash.

The token and caption text are never logged.

## Harness

`npm run build`, then `npm run verify:overlay` (hold the QA lock around both). The harness runs
`start()` in-process with an offscreen window (show, showInactive and focus are stubbed, so
nothing reaches the screen) and isolated userData under `.runtime/ui-qa/overlay/`, against
`scripts/fake-overlay-core.py`. The fake core uses python-socketio and uvicorn from `.venv` on a
free 127.0.0.1 port (never 8000) and checks the token, client id and role.

The harness:

- asserts the window options, bounds, transparency, the bridge members and the CSP of
  `dist/overlay.html`;
- drives one session: connecting, listening, hearing "Hey Jarvis, …", thinking, working, speaking
  with levels, listening with the dimmed answer, approval (clicking Stop and Open JARVIS must reach
  the fake core), then a quiet end that asks to quit after about 4.2 s;
- drives an error end (with a hover pause), a `now` end (cleared in the same commit), a new
  session cancelling a hold, a server disconnect (1 s fade), a refused token and the 10 s
  no-snapshot timeout with invalid payloads dropped;
- checks that no log line contains the token or a caption.

Screenshots of every state over a light and a dark backdrop (injected by the harness only)
go to `.runtime/ui-qa/overlay/`, with `report.json`. The pure rules are covered by
`tests/test_overlay_model.mjs` (`npm run test:client`).
