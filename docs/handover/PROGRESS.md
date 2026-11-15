# Progress ledger — "continue finishing jarvis"

The next task is the first unticked line whose dependencies are ticked. Tick a line as
`- [x] … — <commit>`; mark a blocked one `- [!] … BLOCKED: <reason>`. Rules are in
`RUNBOOK.md`. Specs are in `9NovWork-specs.md` (section named on each line).

Legend: tier **L** light, **M** medium, **C** careful, **H** heavy · **D** needs an
approved download (fallback in the runbook) · **O** ends in an owner-only step (build
everything up to it, leave the feature off, add it to the owner checklist below).

Last verified baseline: `a6233db`, full pytest 3301 passed. Checkpoint commit `1c7ca80`.

---

## Wave 0 — it must answer (S1, S2, S4)


- [x] **S1.1** Weather service, `weather` brain tool, `assistant.home_place`, "Home town" field · S1 layer 2 · M · tests: `tests/test_weather.py` — f7a0284
- [x] **S1.2** Voice instant tools `quick_weather`, `quick_agenda`, `quick_home`; date and time in the Live system text · S1 layer 1 · C · needs S1.1 · tests: instant tool answers without a brain turn — 9390198
- [x] **S1.3** Globe is opt-in: description edit, world tool group gate, `show_view` checks for a window before starting · S1 layer 4 · C — 3926985
- [x] **S1.4** Turn budget, `ToolSpec.long_running`, tool caps, first-token fallback, truthful timeout answer · S1 layer 5 · C — 480715a
- [x] **S1.5** Two-phase `ask_brain` with progress phrases; `ASK_BRAIN` description rewrite · S1 layer 6 · C · needs S1.4 — 5759510
- [x] **S1.6** Claude web search and fetch tools, `pause_turn`, pricing · S1 layer 3 · C · read the `claude-api` skill first — a109ea2
- [x] **S1.7** `turn_timing` log line, `brain_check` RPC, "Run a check" button · S1 layer 7 · M — 8b7c6de (also fixes the owner's effort being overridden by a fixed "medium")
- [ ] **S1.8** `tests/test_no_stall.py` (all seven cases), docs, full suite · S1 layer 7 · C · needs S1.1–S1.7
- [x] **S2.1** Settings `assistant.claude_model`, `assistant.effort`, `assistant.gemini_model`; router; `brain_models` RPC · S2 · M — c258a80
- [x] **S2.2** Preferences: Brain select and Effort control; captures · S2 · M · needs S2.1 — 0479190 (captures `.runtime/ui-qa/brain-picker/`)
- [ ] **S4.1** Turn trace ring buffer (`services/trace.py`) fed by the conversation and voice paths · S4 · M · needs S1.7
- [ ] **S4.2** "Export diagnostics" (tray and Preferences), redaction tests · S4 · M · needs S4.1
- [ ] **S4.3** "Activity → What JARVIS did" list · S4 · M · needs S4.1
- [ ] **W0** Wave check: full pytest, client tests, build

## Wave 1 — real CAD and the JARVIS look (S3, S13a) — the two groups may run in parallel

- [x] **S3.1** `cad_features.py`: feature tree models, limits, stable hash · S3 · C — 3fcb382
- [x] **S3.2** `cad_kernel_worker.py` (build123d in `.venv-cad`) and `cad_kernel.py` (start, reuse, timeout, kill tree, error mapping, fallback to the box engine) · S3 · C · needs S3.1 · opt-in real-kernel tests — 113fb59 (application wiring lands with S3.3)
- [ ] **S3.3** Live design: feature steps (hole, fillet, chamfer, cut, shell, text, pattern), tool descriptions · S3 · C · needs S3.2
- [ ] **S3.4** Live design canvas loads the kernel's GLB draft with the blueprint material · S3 · M · needs S3.3
- [ ] **S3.5** `scripts/setup-cad-engine.ps1`, `requirements-cad-kernel.lock`, `docs/CAD_STUDIO.md` · S3 · L
- [x] **S13a.1** New tokens, 12 px minimum label size, colour roles, alias cleanup · S13a · M — 844dae0 (captures `.runtime/ui-qa/jarvis-language/tokens/`)
- [x] **S13a.2** `HudFrame` and the materialise motion helper · S13a · C · D (`motion`; fallback CSS) — 8cfb2a9 (captures `.runtime/ui-qa/jarvis-language/hud/`)
- [ ] **S13a.3** Core glow sprite, breathing glow, dot grid with pointer parallax · S13a · C
- [ ] **S13a.4** Interface sounds (eight synthesized cues), setting and volume · S13a · M
- [ ] **S13a.5** `services/vitals.py` and the Systems rail replacing the inspector content · S13a · C · needs S1.1
- [ ] **W1** Wave check; captures in `.runtime/ui-qa/jarvis-language/`

## Wave 2 — trust, memory, initiative (S15, S6, S7, S5)

- [ ] **S15.1** Taint rule in `ToolDispatcher`, untrusted-content wrapping, approval card line · S15 · C
- [ ] **S15.2** Sidecars start with a minimal environment and a job object · S15 · C
- [ ] **S6.1** Memory store (tables, FTS5), `memory_search`, `memory_remember`, `memory_forget` · S6 · C
- [ ] **S6.2** Extractor after idle (Haiku, structured output), rules, pause switch · S6 · C · needs S6.1
- [ ] **S6.3** Read path: pinned profile and top facts placed after the cache breakpoint · S6 · C · needs S6.1
- [ ] **S6.4** "What JARVIS knows" page and the Markdown mirror · S6 · M · needs S6.1
- [ ] **S7.1** `Signal`, the bus contract, producers for calendar, weather, calls and jobs · S7 · C · needs S1.1
- [ ] **S7.2** Proactive engine: scoring, chattiness, quiet hours, delivery by presence, mute rules, Activity list · S7 · C · needs S7.1
- [ ] **S7.3** Heartbeat and `HEARTBEAT.md` · S7 · M · needs S7.2
- [ ] **S7.4** Routines: store, triggers, `routine_run`, `routine_save`, the Routines page · S7 · C · needs S7.1
- [ ] **S7.5** Screen help with consent: one screenshot per approval ("What's this error?") · roadmap M9 A6 · M
- [ ] **S5.1** Tool search with deferred loading and a core set (Claude); local tool index (Gemini) · S5 · C · read the `claude-api` skill first
- [ ] **S5.2** Skills: `SKILL.md` folders, `load_skill`, the "Teach JARVIS" approval flow · S5 · C
- [ ] **W2** Wave check

## Wave 3 — reach and home (S8, S12)

- [ ] **S8.1** Channels package: `Channel` protocol, `InboundMessage`, gateway to the conversation and to Signals · S8 · C · needs S7.1, S15.1
- [ ] **S8.2** Telegram channel, pairing code, approval buttons, remote-approval classes, Preferences · S8a · C · O (bot token, pairing)
- [ ] **S8.3** WhatsApp sidecar: bridge, encrypted auth through the core, built-in MCP server `wa` · S8b · C · D (Baileys)
- [ ] **S8.4** WhatsApp channel: rules, caps, typing delay, consent screen, QR screen, kill switch · S8b · C · needs S8.3 · O (consent, QR)
- [ ] **S8.5** WhatsApp calls: incoming card, busy mode, disclosed message-taking chat · S8c · C · needs S8.4
- [ ] **S12.1** Home Assistant WebSocket events, live tiles, home Signals · S12 · C · needs S7.1
- [ ] **S12.2** Home as its own destination; sensors, scenes, camera tiles · S12 · M
- [ ] **S12.3** Homelab framework and the generic adapters (ping, tcp, http_json, prometheus, ssh, wol) · S12 · C
- [ ] **S12.4** Presets, the "Add a system" flow, the Systems page, named actions with approval · S12 · C · needs S12.3 · O (addresses, keys)
- [ ] **S12.5** Frigate events to an overlay card (built with fakes; off until configured) · S12 · M · needs S7.2
- [ ] **W3** Wave check

## Wave 4 — voice and hands (S10, S11)

- [ ] **S10.1** "Only my voice": guided recording and the custom verifier (roadmap M10 V1) · S10c · C · O (the owner records samples)
- [ ] **S10.2** Echo cancellation and natural barge-in · S10b · H · D (audio-processing wheel; else blocked)
- [ ] **S10.3** Direct speech pipeline behind `voice.pipeline`, default unchanged · S10a · H
- [ ] **S10.4** Female voice list with preview in Preferences (Kore default) · S10e · L
- [ ] **S10.5** OpenAI-compatible endpoint for room satellites, off by default · S10f · C · O (firewall, Home Assistant setup)
- [ ] **S11.1** Computer use v1 through a Windows control MCP server, every action on ask · S11 · C · D
- [ ] **S11.2** Computer use v2: native loop, input layer, banner, Esc stop, deny-list, recorder · S11 · H · D (`mss`) · read the `claude-api` skill first
- [ ] **W4** Wave check

## Wave 5 — calls, work, the Stage (S9, S14, S13b)

- [ ] **S9.1** `CallTransport` seam; wrap the Twilio path with no behaviour change (all telephony tests stay green) · S9 · H
- [ ] **S9.2** Modem transport with a fake serial port, port discovery, Preferences · S9a · H · D (`pyserial`) · O (hardware, driver, first call)
- [ ] **S14.1** MCP Streamable HTTP and OAuth; presets (GitHub, Notion, Linear, Spotify); per-tool policy editor · S14 · H
- [ ] **S14.2** Gmail triage into the briefing; never sends · S14 · C · O (OAuth re-consent)
- [ ] **S14.3** Files knowledge: chosen folders, index, `files_search` · S14 · C · D (`markitdown`; fallback text and Markdown only)
- [ ] **S14.4** Meeting notes with a visible recording indicator · S14 · C
- [ ] **S14.5** Design to render through `workers/blender_scene.py` · S14 · M · needs S3.2
- [ ] **S14.6** Web tasks through a Playwright MCP sidecar · S14 · C · D
- [ ] **S13b.1** One page header, the icon rail, Home and World full-bleed, no page inside a page · S13b · C
- [ ] **S13b.2** Stage-first Assistant: hero core, large captions, transcript rail · S13b · H · needs S13a
- [ ] **S13b.3** Panel registry and `stage_show`; move Live design and the World tour onto it · S13b · H · needs S13b.2
- [ ] **S13b.4** Ambient mode (off by default) and proactive overlay cards · S13b · C · needs S13b.2, S7.2
- [ ] **W5** Wave check; captures for every changed screen

## Wave 6 — measure and release (S16, M5)

- [ ] **S16.1** Eval scripts and the Latency block (no paid runs without the owner's OK) · S16 · M
- [ ] **S6.5** Vector search for memory and files · S6 v2 · C · D (else stay on FTS5)
- [ ] **M5.1** SQLite work off the event loop · roadmap M5 · H
- [ ] **M5.2** Core port resilience and a clear message when 8000 cannot bind · roadmap M5 · C
- [ ] **M5.3** Harnesses use a throwaway Electron profile · roadmap M5 · M
- [ ] **M5.4** Vite 8 and ESLint 10 migration · roadmap M5 · C
- [ ] **M5.5** README, licence flags (wake-word models, God's Eye View data, Open-Meteo), clear `.runtime` residue · roadmap M5 · L
- [ ] **FINAL** Full verification, `docs/IMPLEMENTATION_STATUS.md`, memory note, the final report (`RUNBOOK.md` section 10)

Deferred, not part of this run: K2–K4 printing (no printer yet), local offline model
(S10d, owner's RAM decision), signed installer and auto-update (certificate decision),
Android companion acceptance (no SDK on this PC), the Bluetooth hands-free node (S9c).

---

## Launch approvals (14 Nov 2026, run session 1)

The owner approved every item, with these measured versions and sizes. Approvals are for
this session only (`RUNBOOK.md` step 2.4); a resumed session asks again.
- npm (registry.npmjs.org): motion 14.14.0 + @fontsource-variable/saira 5.3.0 (5 pkgs,
  4.9 MB); uplot 1.6.32 (0.2 MB); @react-three/postprocessing 2.19.1 (4 pkgs, 1.4 MB);
  @whiskeysockets/baileys 7.0.0-rc14 (71 pkgs, 17.5 MB, own sidecar folder);
  @playwright/mcp 0.0.85 + playwright-core (3 pkgs, 4.2 MB, uses the installed Edge, no
  Chromium download).
- pip (pypi.org): pyserial 3.5 (0.1 MB); livekit 1.2.1 (11 MB new); mss 10.2.0 (0.1 MB);
  markitdown[docx,pdf,pptx,xlsx] (36 pkgs, up to 82 MB); sqlite-vec 0.1.9 + fastembed
  (31 pkgs, 47 MB); windows-mcp 0.8.5 (not measured: network errors; measure at Wave 4,
  install only if under 50 MB).
- Not yet asked: the fastembed embedding model (ask at S6.5 with its size). Dropped:
  sherpa-onnx (S10d is owner-deferred) and Playwright's Chromium (Edge is used instead).

## Deviations (write one line whenever reality differs from the spec)

- S1.6: web search and fetch are added only to Claude requests that already carry client
  tools, so phone chat and the camera look stay tool-free. A history that holds server
  blocks keeps the tools declared even with the setting off. Open: `pricing.py` has Sonnet
  5.5 cache reads at $0.20/MTok while the claude-api skill says $0.10 — check in S16.
- S1.6: CAD planning (`create_text_provider()` in conversation.py, no settings) gets web
  search by default; pass `web_search=False` there in S1.7.
- S3.2: the spec's sample tree does not build as written: OpenCascade cannot shell a body
  after its fillets and chamfers, and a 1 mm chamfer uses up a 2 mm wall. Order shells
  first in examples and tool descriptions; the kernel reports the failure plainly.
- S2.2: the shared SegmentedControl draws its option labels at 11 px (0.6875rem), below
  the 12 px minimum; S13a.1 raises it for every segmented control at once.
- S14.6: Playwright MCP runs with the installed Microsoft Edge (`--browser msedge`), so no
  Chromium download is needed.

## Owner checklist (the run appends to this; nothing here can be done by the agent)

- [x] Approve the download list at the start of the run (14 Nov 2026, all items).
- [ ] Start JARVIS from the Desktop shortcut and run the live checklist the final report gives.
- [ ] Preferences > AI: set "Home town"; press "Run a check".
- [ ] Telegram: create a bot with BotFather, paste the token, send the pairing code.
- [ ] WhatsApp: read the consent screen, scan the QR code.
- [ ] Calls: plug in the modem, install its driver, make one test call; or stay on Twilio.
- [ ] Home Assistant token; Google OAuth client with the Calendar and Gmail read scopes.
- [ ] Systems: add homelab hosts (address and key or token for each).
- [ ] "Only my voice": record the samples in Preferences > Voice.
- [ ] Copy the wake-word models into the real `%LOCALAPPDATA%\JARVIS\models\wake-word`.
- [ ] Review the captures of the new screens and say what to change.
