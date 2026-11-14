# 9NovWork — checkpoint and handover index

Saved 14 Nov 2026. To resume, the owner says **"continue 9NovWork"**. To build
everything that is left in one unattended run, the owner says **"continue finishing
jarvis"**: follow `docs/handover/RUNBOOK.md` and tick tasks off in
`docs/handover/PROGRESS.md`.

**How to resume without wasting tokens.** Read this file only. Then open just the one
spec section you are about to build in `9NovWork-specs.md` (sections are self-contained).
Read `9NovWork-audit.md` only for UI work or when asked "why".

| File | What it holds | Read when |
|---|---|---|
| `docs/handover/9NovWork.md` | State, in-flight work, decisions, build order, owner actions | Always, first |
| `docs/handover/RUNBOOK.md` | How to run the whole build unattended: start-up, approvals, the task loop, stop rules | Before the run |
| `docs/handover/PROGRESS.md` | The ordered task ledger with acceptance checks; the run ticks it off | Every session |
| `docs/handover/9NovWork-specs.md` | Build specs S1–S16: libraries, file layout, tools, settings, tests | Before building that item |
| `docs/handover/9NovWork-audit.md` | Critical design audit, technical audit, comparison with public projects, sources | UI work, or to justify a decision |
| `C:\Users\nojiq\.claude\plans\for-this-whole-project-vectorized-fountain.md` | Full roadmap history M1–M10 | Only for history |

Confidence tags used in all three files: **[repo]** checked in the code this session,
**[web]** from web search in Nov 2026 (mostly secondary sources), **[recall]** from model
memory and not re-checked — verify before relying on it.

---

## 1. Where it stopped

- Branch `main`, last feature commit `a6233db` (M6 World view). This checkpoint is the
  next commit (docs + `.gitignore`). Nothing is pushed; the owner pushes at the end.
- Full pytest at the last full run: 3301 passed.
- Done: M1 identity, M2 Blender look, M3 live-run fixes, M4 everyday features, M6 World
  view. Next in the roadmap: M7 Maker (K1 only; no printer yet), M8, M9, M10, M5.
- The owner added Anthropic credit. Voice works. Tasks that go through the brain still
  stall on simple questions (see 2.1).

## 2. In-flight work (do these first, in this order)

### 2.1 The stalled weather question — diagnosed in code, not yet confirmed in the log

Owner's transcript: "What's the weather today?" → "One moment while I check the
conditions." → "One moment, retrieving the weather details" → "I am experiencing a slight
delay…" and no answer.

What the code shows **[repo]**:
- `backend/services/voice.py:1029` `ask_brain` awaits `conversation.reply(...)` with no
  deadline and no progress feed. The "slight delay" lines are the Gemini Live model
  filling silence by itself; they are not real status.
- `backend/services/world_tools.py:109-117` tells the brain to answer weather questions
  with the God's Eye View tools (`mcp__gev__...`). This GEV build exposes 30 tools and
  none answers a weather question (it has weather map layers only). So the brain starts
  the World sidecar cold and chains map tools.
- There is no weather tool and no web search tool anywhere in the brain's tool list.
- The Claude request itself is correct (`backend/llm/claude.py`: adaptive thinking,
  `output_config.effort`, default effort `medium`, caching, refusal fallback). The router
  picks Claude in Auto when an Anthropic key exists (`backend/llm/router.py`).

Deeper cause found on 14 Nov **[repo]**: a brain turn has no overall time limit (5 steps
× 45 s of model time, globe tools up to 135–240 s each), so a wrong tool choice can
legally take minutes. S1 now fixes this by construction and does not need the log.

Optional, if the owner ever wants the log read (my shell cannot read their real AppData):

```powershell
Get-Content "$env:LOCALAPPDATA\JARVIS\logs\jarvis.log" -Tail 300 | Set-Content C:\Users\nojiq\code\INARA\.runtime\live-logs\jarvis-latest.log
```

Look for `provider`, `timing`, `gev`, `ask_brain`, `credit`. Fix = spec **S1**.

### 2.2 Model and effort picker — requested, not designed yet

Owner's words: choose Haiku 5.5 or Sonnet 5.5, default medium effort, effort changeable,
and Gemini selectable too. Spec **S2** has the API facts, settings keys and UI. In the
unattended run, build it to the spec and save captures (`RUNBOOK.md` section 7).

### 2.3 M7 K1 real CAD engine — engine installed, worker not briefed yet

- `.venv-cad/` exists at the repo root (gitignored) with `build123d==0.13.0` (57 packages,
  226.7 MB, owner-approved). Check passed: `Box(20,20,10) - Cylinder(3,10)` volume 3717.3.
- Build spec **S3**. K2–K4 (slicer, printer, print by voice) wait for a printer.

## 3. Decisions made in this pass (the owner asked me to decide)

| Topic | Decision | Why (short) |
|---|---|---|
| North star | JARVIS wins on **presence, trust and craft**: a voice that answers fast, approvals you can trust, and a UI that feels alive. Do not copy OpenClaw's "do anything, ask nobody" model. | OpenClaw is the most-starred assistant (373k, May 2026 **[web]**) and also the best-documented security failure. |
| Everyday answers | Add Claude's server web search/fetch tools plus a free Open-Meteo weather tool. | Fixes the stall; three small changes. S1. |
| Model picker | One "Brain" choice (Auto, Sonnet 5.5, Haiku 5.5, Gemini + model) and an Effort control (Low/Medium/High, default Medium, Claude only). | S2. |
| CAD kernel input | A declarative feature tree run by a build123d worker, not model-written Python. | Deterministic, validates, no code execution risk. S3. |
| Tool growth | Claude tool search with deferred loading; skills as `SKILL.md` folders written or approved by the owner. No marketplace. | 60+ tools already; MCP will add hundreds. S5. |
| Memory | Native SQLite store: FTS5 first, `sqlite-vec` later; Haiku extracts facts; an editable "What JARVIS knows" page. Not mem0, Letta or Graphiti. | No new service, no download to start, owner can see and fix it. S6. |
| Proactive | One event bus → salience scoring → delivery by presence; a heartbeat that only spends tokens when signals are pending; owner-defined routines. | S7. |
| Phone reach | **Telegram bot** as the remote channel (official API, safe), with approval buttons. | Fastest route to "everyday life" away from the PC. S8. |
| WhatsApp messages | Linked-device bridge: **Baileys** in a Node 24 sidecar behind the existing MCP connector, auth encrypted by the core, strict send rules, owner consent screen. | No WhatsApp Business. Unofficial, so ban risk is real and the owner must accept it. S8. |
| WhatsApp calls | Cannot be answered by any library. Detect the call, optionally reject it and take a message by text with AI disclosure. Real voice answering only via a Bluetooth hands-free node (stretch). | whatsmeow/Baileys expose call offers and reject only **[web]**. S8/S9. |
| Phone calls | Make the call transport pluggable. Recommended for Malaysia: a **USB GSM modem with a local prepaid SIM** on the PC. Twilio stays supported. Windows Bluetooth hands-free API rejected. | No Twilio regulatory bundle, local caller ID, no per-minute cloud fee. Needs a hardware spike first. S9. |
| Voice quality | Add echo cancellation for natural barge-in, speaker verification, and a "direct" speech pipeline to stop double generation. Measure before switching the default. | S10. |
| Computer use | v1 through a Windows MCP server with "ask" on every action; v2 native with Claude's computer toolset, banner, Esc stop, deny-list. | S11. |
| Home and homelab | Home Assistant realtime events, a read-only homelab pack (Proxmox, Docker, uptime, NAS, UPS), cameras via Frigate, JARVIS as the conversation agent for room satellites. | S12. |
| UI direction | Keep the calm console as the base and add a **JARVIS layer**: depth, light, motion, sound, live telemetry, a Stage where panels materialise, and an Ambient wallboard mode. Do not adopt Arwes. | S13 and the audit. |
| Security | Taint rule: after reading untrusted content, every outward action asks. Sidecars get no inherited secrets. | S15. |

## 4. Build order

The task-level order to follow is `PROGRESS.md`. It moves the taint rule (S15) ahead of
the channels. This table is the overview.

| Wave | Items | Notes |
|---|---|---|
| 0 | S1 everyday answers and progress, S2 model picker, S4 diagnostics export | Unblocks daily use. Then one live check with the owner. |
| 1 | S3 CAD engine ‖ S13a design language, sound, Systems rail | Separate files, can run in parallel. |
| 2 | S6 memory, S7 proactive engine and routines, S5 tool search and skills | S7 before any new signal source. |
| 3 | S8 Telegram, then WhatsApp ‖ S12 home realtime and homelab | WhatsApp only after the owner's consent. |
| 4 | S10 voice quality, S11 computer use | Both need Claude credit and live checks. |
| 5 | S9 modem calls (hardware), S14 work pack, S13b Stage and Ambient mode | |
| 6 | S15 hardening pass, S16 evals, then M5 release, K2–K4 printing | S15's taint rule should land with S8 at the latest. |

## 5. The owner's answers (14 Nov 2026) and what is left for them

| Question | Answer | Effect |
|---|---|---|
| Copy the log for the weather stall | "Just make a plan so there won't be a weather stall" | S1 was rewritten to remove every cause found in code and to bound every turn. It no longer needs the log. |
| Which homelab services | "It's planned, make it so it can run anything" | S12 homelab is generic: ping, TCP, HTTP-JSON, Prometheus, SSH and Wake-on-LAN adapters, presets on top, an "Add a system" flow. |
| WhatsApp linked device | Yes | S8b is in scope. Pairing (the QR code) is still the owner's step. |
| Telegram bot | Yes | S8a is in scope. Creating the bot and saving its token is the owner's step. |
| GSM modem or Twilio | "Whichever you suggest" | Build the transport seam and the modem transport; Twilio stays the default until a modem is plugged in. Suggested hardware in S9. |
| Voice | Keep a woman's voice | Kore stays. No male preset (S10e). |
| Wallboard | "Make it an option" | Ambient mode is built, off by default (S13b). |

Owner-only steps (the run cannot do these; it prepares everything up to them):
- Start the live JARVIS and run the live checklist at the end.
- Approve the download list once at the start of the run (`RUNBOOK.md`, step 2).
- Telegram: create a bot with BotFather, paste the token, send the pairing code.
- WhatsApp: accept the consent screen and scan the QR code.
- Calls: buy and plug in the modem, install its driver, make the first test call.
- Home Assistant token, Google OAuth client (with the Gmail read scope), homelab addresses and keys.
- Copy the wake-word models into the real `%LOCALAPPDATA%\JARVIS\models\wake-word`,
  run `scripts/install-shortcuts.ps1`, decide `NOMINATIM_URL` for place search.

## 6. Downloads that will need the owner's OK (state name, source, size first)

The launch list, with the fallback for each item, is in `RUNBOOK.md` section 6.

| For | What | Known facts |
|---|---|---|
| S8 WhatsApp | npm `@whiskeysockets/baileys` + its dependencies | Size unknown; measure with the lockfile method in `scratchpad npm_lock_sizes.py` (ranged GETs). |
| S6 v2 | pip `sqlite-vec`, `fastembed`, one embedding model | Model 120–470 MB depending on choice **[recall]**. |
| S9 | pip `pyserial`; modem USB driver (owner installs) | Tiny. |
| S10 | pip `sherpa-onnx` and models, or `livekit` for the audio processing module | Check a cp313 Windows wheel exists first. |
| S11 | Windows MCP server, pip `mss` | Small. |
| S13 | npm `motion`, optional `@react-three/postprocessing` | Small. |
| S14 | pip `markitdown` | Pulls several parsers. |

## 7. Standing rules (unchanged)

- Never push. Local commits only, one per accepted task, ending with the co-author line.
- JARVIS only, never INARA.
- Any download needs the owner's OK after stating file name, source and size.
- Keys only through the encrypted store; never argv, never logs, never echoed.
- Third-party outgoing calls need approval every time, with AI disclosure.
- Never change system settings; the owner does that.
- Tests never open real audio devices or the camera; nothing binds port 8000; harnesses
  run offscreen under the QA lock (`node .runtime/qa-tools/qa-lock.cjs acquire|release <name>`).
- Do not stop the owner's Vite dev server on 5173.
- The owner starts the live JARVIS. My shell sees a private, virtualised AppData.
- No in-app downloads of third-party code; fresh installs use owner-run pinned scripts.
- World view: no tracking of individuals, no face recognition, CCTV and plate-reader layers off.
- Design is shown as a mockup and approved by the owner before building, except in the
  unattended run, where `RUNBOOK.md` section 7 applies.
- The owner said bugs get fixed after the whole project is complete: keep building, live checks wait.
- WhatsApp sending was excluded until now. It stays off until the owner turns it on in the consent screen (S8).
