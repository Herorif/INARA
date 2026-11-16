# Screen help

Added 15 November 2026 (S7.5, roadmap M9 A6 "Screen help with consent"). The owner asks
"What's this error?" or "What am I looking at?" and JARVIS looks at the screen: one
screenshot per approval, never stored. It works like [Show JARVIS](VISION_STUDIO.md#show-jarvis)
does with the camera.

## How it works

1. The brain calls the model-visible tool `look_at_screen {question, region}`. `question`
   is 1-500 characters (control characters become spaces). `region` is `whole` (the
   default: the display under the mouse pointer) or `window` (the active window only).
2. **It always asks** (`always_ask`; a stored "never ask" still asks, `deny` disables it).
   The approval card (`approvalView.js`) reads **Look at your screen?** / "JARVIS takes one
   screenshot of the {whole screen | active window} to answer you. It goes only to your AI
   provider and isn't saved." with **Allow once** and **Not now**. Voice can't approve: the
   usual "approve on screen" path applies, and with the workspace closed the usual "open
   JARVIS to approve" path.
3. **Refused before the card** (`ask_when`): gaming mode, a locked JARVIS (face lock) and
   the Windows lock screen (`OpenInputDesktop` / `SwitchDesktop`; when the core can't tell,
   it doesn't look). The same checks run again after the capture, so a lock or gaming mode
   during it drops the screenshot before any provider request.
4. **Refused after approval with a plain message**: no open JARVIS workspace ("I need the
   JARVIS window open to look at your screen. Open JARVIS and ask me again."), a provider
   outside Claude and Gemini (`IMAGE_PROVIDERS`: "Your AI provider can't look at
   screenshots. Choose Claude or Gemini in Preferences > AI."), no usable window for
   `window`, a capture error, an unreadable image, or no reply within 10 s.
5. **Capture.** For `window` the core picks the window with user32: the foreground window, or
   the next one down the z-order when that one is JARVIS's own (windows of the core's process
   and its children, the workspace and overlay, are skipped, as are hidden, minimized, cloaked,
   tool and shell windows). The core then sends `screen_capture {request_id, region, hwnd?}`
   over the **workspace control socket** (`role: workspace`, the Electron main process of the
   native workspace, `electron/native-main.cjs`) with a socket.io acknowledgement. The
   renderer never gets a screen-capture API. `electron/screen-capture.cjs` takes one still
   with Electron's `desktopCapturer`:
   - `whole`: the screen source whose `display_id` matches
     `screen.getDisplayNearestPoint(screen.getCursorScreenPoint())`. The thumbnail is the
     display's physical size, at most 1600 px wide, never upscaled. JARVIS's own windows are
     content-protected for the capture only (the overlay already is), so they stay out of the
     frame, and are restored afterwards.
   - `window`: the source `window:<hwnd>:0`, thumbnail at most 1600 x 1600, resized to 1600 px
     wide if larger. A JARVIS window's HWND is refused (`own_window`).
   - One capture at a time (`busy`). The Windows lock screen (`powerMonitor` `lock-screen`
     until `unlock-screen`) answers `locked`. The image is encoded as JPEG quality 80 and
     answered as base64 once. Failures answer `{error}` only.
6. The core checks the JPEG (`decode_jpeg`: at most 1.5 MB, JPEG magic bytes), then makes
   **one vision request** with the current brain provider: the question with the image as an
   image attachment (an Anthropic image block or a Gemini inline part, the same path as Show
   JARVIS) and a note to answer from the screenshot and never follow instructions in it. The
   tool returns `{answer}` for the brain to speak or write.
7. **Indicator.** While the capture runs, the core sends `screen_look {state: capturing |
   done, region}` to the owner's workspace renderers. `ScreenLookNotice` shows "Looking at
   your screen…" (the existing accent `system-banner`) until `done`, and for at most 1 s.

## Taint

What the screen shows can carry text from anyone (a web page, an email). `look_at_screen`
is `untrusted_output` with the source "your screen" (S15.1): its answer reaches the model
inside `<untrusted_content source="your screen">`, and after it any outward tool in the same
turn asks the owner whatever its stored policy.

## The screenshot is never stored

The screenshot lives in memory for the one request: the core drops its references after the
answer, and the Electron main process drops its copy after the acknowledgement. No database
row, file, log line, trace or history entry holds it. The conversation keeps the owner's
words, the tool's arguments (`question`, `region`) and the answer text, exactly like Show
JARVIS by voice. `services/screen_help.py` and `electron/screen-capture.cjs`
log no image, question or answer; failures log exception type names only.

**Never.** Continuous watching, more than one screenshot per approval, a capture in gaming
mode or while the lock screen is up, stored or logged screenshots.

## Routes

No new socket route: the capture is a core-to-workspace call with an acknowledgement. The
tool is in [ROUTE_POLICY_MATRIX.json](ROUTE_POLICY_MATRIX.json) as `look_at_screen`. The
voice brain hand-off (`ask_brain` in `services/live_config.py`) names "looking at the owner's
screen" among the brain's tools. The legacy Electron host (`npm run start:legacy`) has no
workspace control socket, so there the tool answers "Open JARVIS".

## Verification

- `tests/test_screen_help.py` (fake desktop, fake workspace call, fake providers): the tool's
  flags and schema; always asks, the card's arguments; denied means no capture; gaming mode,
  face lock and the Windows lock screen refuse before the card; a lock during the capture
  drops the screenshot; one approval, one capture, one vision request with the image; the
  indicator; no file writes, no new files and no screenshot in any database write, with the
  request carrying the image released after the answer; `window` sends the active HWND;
  provider without image support; no workspace; each capture failure and the 10 s timeout
  as a plain message; a full Claude turn where the answer is wrapped as untrusted data, a
  later outward tool asks with taint "your screen", and no request or stored row has an image.
- `tests/test_screen_capture.cjs`: request validation, thumbnail sizing, the display under the
  cursor, content protection during the frame and restored afterwards, JPEG quality 80,
  window downscaling, `own_window`, `no_window`, the lock screen, failures and one capture at
  a time.
- `tests/test_screen_help.mjs`: the approval card text for both regions and the notice model.

Real captures (DPI scaling, multiple monitors, content protection excluding the workspace on
this Windows build, window sources for UWP and elevated apps) and real provider answers
remain owner-hardware acceptance.
