# 9NovWork — critical audit (design, technical, comparison)

Written 14 Nov 2026 from the real captures in `.runtime/ui-qa/` (Assistant with voice
stage, Studio, World tour, Home, splash), `src/app/tokens.css`, the CSS and the backend.
Tags: **[repo]** checked this session, **[web]** web search Nov 2026, **[recall]** unverified.

---

## A. Design critique

### Overall impression

It is a clean, competent dark dashboard. It does not feel like JARVIS. It looks like a
well-made admin console with a small spinning logo: a sidebar, cards, a chat log, and a
lot of black. JARVIS in the films is a presence that owns the room: light, depth, motion,
sound and data that never stops moving. Today the only living thing on screen is an 80 px
core inside a bordered box, and nothing moves at all unless voice is active.

The biggest opportunity: make the core and the voice the centre of the product, and let
everything else appear around it when needed, instead of living on pages you navigate to.

### Measured facts behind that verdict [repo]

- 9 CSS keyframes in the whole renderer; 18 shadow/blur declarations in 6,077 lines of CSS.
- No sound files and no UI sound code. Only the generated wake chime exists.
- One accent colour (`--accent #70e0ed`) carries navigation, links, status, chips and the core.
- Surfaces are three near-identical blacks (`#05080c`, `#0a1017`, `#0f1720`) separated by
  1 px lines. Shadows are reserved for dialogs. There is no depth.
- The Context inspector shows "Resource mode: Lightweight", "Workspace memory: Not
  measured", "No reminders today". The most valuable column on screen holds empty states.

### Usability

| Finding | Severity | Recommendation |
|---|---|---|
| A simple spoken question can hang forever while the voice invents "slight delay" lines. | Critical | S1: real tools for everyday answers, real progress lines, deadlines. Nothing in the UI matters until this works. |
| The Assistant page is a chat app with a widget on top. The voice stage is a boxed strip; the transcript takes the rest; half the page is empty. | Critical | Stage-first layout (S13b): core large and centred, captions as large type under it, transcript as a side rail. |
| Information architecture is tool-shaped: Studio, Inbox, Calls, Tasks, Connections. Home lives under "Connections". World is a tab inside Studio. | Moderate | Destinations by life area: Assistant, Home, World, Make (CAD/images/print), People (calls/messages), Work, Systems. Give Home and World their own entries. |
| World view has three stacked header rows (tabs, "EXPLORE World" with a close button, "WORLD God's Eye View" bar) before the globe: about 240 px of chrome. | Moderate | One 48 px bar; globe full-bleed to the window edge; tour bar floats over it (already good). |
| Pages inside pages: a docked "feature workspace" with its own header and a close X inside a page. It is unclear what closing does. | Moderate | A destination is a page. Only panels on the Stage close. |
| Studio is a card launcher with two thirds of the page black. Cards differ in height and title baseline because only some have a status chip (3D studio title at y≈298, Images at y≈296 in the capture). | Moderate | Make cards live previews (last model, last image, camera state); reserve the chip row on every card. |
| Kasa block shows a raw IP address and "CACHED OBSERVATION". | Minor | Device name and "Last seen 2 min ago"; technical details behind a disclosure. |
| "Workspace memory / Not measured" wraps into two lines on each side. | Minor | Short label ("Memory") and a value or a dash. |
| Approvals are solid (in-panel cards, exact facts). | Keep | This is the product's real advantage over every public project. |

### Visual hierarchy

- **What draws the eye first:** the cyan selection bar in the sidebar and the caption text.
  The core should win, and it does not: it is 80 px, left-aligned, in a box.
- **Reading flow:** title bar chips → sidebar → page title → content. That is the flow of
  a settings app. For JARVIS it should be: core → what it is saying or showing → controls.
- **Emphasis:** every control is a thin outlined rectangle, so "Stop talking", "Refresh",
  "Open in browser" and "Quick assistant" all weigh the same. Uppercase mono labels with
  wide tracking appear on nearly every block, which flattens them into texture.

### Consistency

| Element | Issue | Recommendation |
|---|---|---|
| Colour | Cyan means selected, link, status, "JARVIS", and decoration at once. | Roles: cyan = JARVIS/system, amber = JARVIS acting or needs you, green = done/ok, red = danger only, white = the owner's words. |
| Headers | Three header styles (page title + meta, "CONNECT / Home" stacked with icon tile, "WORLD God's Eye View" inline). | One header component with an optional kicker. |
| Labels | Uppercase mono used for section names, statuses, chips, timestamps, footers. | Uppercase mono only for live status and data; sentence case elsewhere. |
| Core | Flat ring fallback under 64 px, 3D above; the offline state in the inspector reads as a broken image. | Offline = dim but intact; never an empty circle. |
| Tokens | `--deck-*` back-compat aliases still in use beside the new tokens. | Finish the migration, delete aliases. |

### Accessibility

- **Contrast:** `--text-3 #74849a` on `#05080c` is about 5.3:1 and on `#0a1017` about 5:1:
  passes AA for body text, but it is used at 11 px uppercase, which is hard to read. Raise
  `--text-xs` to 12 px and keep `--text-3` for 12 px and up.
- **Targets:** tile menu dots and the inspector close icon look under 24 px. Minimum 28 px
  hit area on desktop.
- **Motion:** reduced-motion, gaming mode and low-battery fallbacks already exist. Every
  new effect in S13 must sit behind the same switches.
- **Sound:** new UI sounds need a master switch and must never carry information alone.
- **Captions:** all speech is captioned. Keep that as a rule for every new voice surface.

### What works well

- The 3D core design and its state language (listening, speaking, working, offline).
- Approval cards with real facts; per-device access in Home ("JARVIS can control / Always asks / Off limits").
- The World tour bar and "JARVIS is driving" chip: this is the closest thing to the film today.
- Live design: parts appearing as JARVIS narrates. Generalise this pattern everywhere.
- Restraint. The base is calm and readable; the fix is to add life, not noise.

### Priority recommendations

1. **Make it answer** (S1). A beautiful shell around a stalled brain is still a stalled brain.
2. **Stage-first Assistant** (S13b): hero core, kinetic captions, panels that materialise.
3. **Life**: Systems rail with real telemetry, idle motion, glow and depth, sound identity (S13a).
4. **Ambient wallboard mode**: full-screen core, clock, weather, home, globe. This is the
   single most "JARVIS" thing that can be added for the effort.
5. **Fix the IA**: Home and World as destinations, one header style, no pages inside pages.

---

## B. The JARVIS design language (what "more JARVIS" means, concretely)

The film look is four things. Each maps to a small, buildable change.

| Quality | Today | Target |
|---|---|---|
| Light | Flat lines, no glow | Live elements emit light: soft outer glow on the core, on active chips and on the caption cursor. Static chrome stays matte. |
| Depth | Three flat blacks | Three layers: a void with a faint radial gradient and dot grid; translucent glass panels (blur 14 px); floating overlays. Slight parallax of the core against the grid on pointer move. |
| Motion | Nothing moves at rest | Slow idle drift (20–40 s loops), a 4 s breathing glow, counters that tick, panels that draw their border, then fill. Fast in (160–240 ms), faster out (120 ms). |
| Sound | Wake chime only | Eight short synthesized cues with one timbre family (see S13). |
| Data | Empty inspector | Always-true telemetry: time, weather, next event countdown, home summary, PC vitals, homelab dots, running jobs. |
| Voice-first | Chat log | Large captions under the core, revealed word by word with the audio; the owner's speech as a live waveform. |
| Frames | Rounded rectangles | HUD frames: chamfered corners, corner brackets, tick rulers, index numbers ("01 · WORLD"). Used on Stage panels only, not on forms. |

Rules that keep it tasteful:
- One hero per screen (the core). Glow only on things that are live right now.
- Forms, settings and tables stay plain. The JARVIS layer is for the Stage, overlays and the wallboard.
- No fake data. Every ticking number is real, or it is not shown.
- Do not use film assets, logos, the actor's voice, or "Stark" branding.

Typography: keep Inter for text and JetBrains Mono for data. Add one display face for
large numerals and panel titles (a geometric, slightly condensed sans such as Saira or
Oxanium, both OFL **[recall]**; bundle locally like the other fonts).

---

## C. Technical audit

### What is strong

- Safety model: `ToolSpec.always_ask` / `ask_when`, per-device access, approvals with
  review facts, encrypted secrets, consent per camera look, AI disclosure on calls.
- Test discipline: 3301 pytest, fakes for audio/camera/network, offscreen harnesses.
- Clear seams: services + transports, provider router, MCP connector, sidecar manager.
- The Claude provider follows the current API correctly (adaptive thinking, effort,
  caching, fallback, verbatim history).

### What is weak (ranked by harm)

1. **Nothing has been proven live end to end.** Calls, the briefing's spoken turn, the
   overlay on a real screen, World view control and wake word on real devices are all
   "not verified live". The agent cannot read the owner's logs (virtualised AppData).
   Fix: a one-click diagnostics export (S4) and a scripted live checklist.
2. **The voice path generates every answer twice.** Claude writes the answer, then the
   Gemini Live model re-speaks it "condensed". That adds latency, lets the voice drift
   from the persona, and is why it invents delays. Fix: two-phase `ask_brain` now (S1),
   a direct speech pipeline later (S10).
3. **No everyday tools.** No weather, web search, timers by voice beyond reminders,
   unit/currency, news. The brain reaches for a 3D globe to answer "weather". Fix: S1.
4. **Every tool schema is sent on every turn.** About 60 tools today, hundreds once MCP
   servers arrive. Cost and wrong-tool errors grow with it. Fix: tool search with
   deferred loading and skills (S5).
5. **No long-term memory of the owner.** Only per-project memory. JARVIS forgets
   preferences between conversations. Fix: S6.
6. **Reactive only.** No event bus consumers, no proactive engine, no routines. Fix: S7.
7. **Chained to the desk.** The Android companion was never built (no SDK here). There is
   no way to reach JARVIS, or approve something, from the phone. Fix: Telegram (S8).
8. **Half-duplex audio.** No echo cancellation, so barge-in needs the wake word, and any
   voice (or the TV) can wake it. Fix: S10.
9. **No offline mode.** Internet or provider down means no assistant, not even lights.
   Fix: local fallback (S10d), owner-deferred until the RAM decision.
10. **MCP client is stdio-only.** Most official servers (Notion, Linear, GitHub remote)
    are remote HTTP with OAuth. Fix: add Streamable HTTP + OAuth to `mcp_client.py` (S14).
11. **Prompt injection surface is about to grow** (web pages, messages, MCP results).
    Approvals exist but are per tool, not per context. Fix: taint rule (S15).
12. **No measurement.** No evals, no latency budget, no per-turn trace. Fix: S4, S16.
13. **Process weight.** Python core + resident host + Electron workspace + overlay
    Electron (about 270 MB while talking) + Node sidecar + CAD worker. Acceptable on this
    PC; revisit the overlay as a native layered window in M5 if memory matters.
14. **SQLite on the event loop**, port 8000 fixed, harnesses writing to the real Electron
    profile: already listed under M5.
15. **Windows-only.** Fine for a personal build; note it in the README.

### What can be made "extra" (impressive, and worth it)

- Ambient wallboard on a second screen or a tablet over Tailscale.
- JARVIS in every room: Home Assistant voice satellites using JARVIS as the conversation agent.
- "Show me" generative panels: any tool result can materialise as a Stage panel (chart,
  table, camera, map, model, document).
- Design to render: live design → build123d → Blender Cycles product render, narrated.
- Phone approvals: "Unlock the front door?" arrives on Telegram with buttons (door and
  alarm classes stay off by default for remote approval).
- Morning briefing on the globe: weather over KL, flights delayed, quakes nearby.
- Meeting notes with action items into reminders.
- A "What JARVIS did" flight recorder: every action, why, and an undo where possible.

---

## D. Comparison with public projects

### Lineage [repo]

This repo's first commits (4 Dec 2025: "start", "ada ai") show it began from
`nazirlouis/ada_v2` (A.D.A V2, Advanced Design Assistant: Gemini native audio, CAD,
printer agents, Kasa, face lock, hand tracking). It has since been rebuilt far past that
base. ADA's CAD approach (the model writes build123d scripts and retries on error) is the
thing not to copy: S3 uses a validated feature tree instead.

### The most famous one: OpenClaw [web]

- 373k GitHub stars as of May 2026 (third-party count), the fastest-growing agent project.
- Shape: one long-running Node gateway; channel adapters (it started as a WhatsApp
  relay, using Baileys); skills as Markdown/YAML folders with a public registry (ClawHub,
  3,000+ skills); memory as local Markdown files; a heartbeat every 30 minutes that reads
  a heartbeat file and either acts or stays silent.
- Documented failures: indirect prompt injection turning it into a persistent backdoor
  (Zenity Labs); 341 of 2,857 audited ClawHub skills flagged malicious (Koi Security);
  76 confirmed malicious payloads in 3,984 (Snyk); Baileys session keys stored as
  plaintext JSON (a community red-team write-up); CVE-2026-25253.

| OpenClaw idea | Take it? | How it lands here |
|---|---|---|
| Chat apps as the interface | Yes | Telegram first, WhatsApp bridge second (S8). |
| Heartbeat | Yes, cheaper | Only runs when signals are pending; owner-editable `HEARTBEAT.md` (S7). |
| Skills as folders | Yes, no marketplace | `SKILL.md` folders; JARVIS drafts, owner approves (S5). |
| Memory as readable files | Yes, as a mirror | SQLite is the store; a Markdown mirror and an edit page give the transparency (S6). |
| Device nodes (phone camera, location) | Later | Telegram covers messages and approvals now; the Android companion later. |
| Full shell access, auto-run skills | No | Approvals, taint rule, sandboxed sidecars (S15). |

Where JARVIS is already ahead: a real voice presence with wake word and overlay, a 3D
identity, approvals with facts, encrypted keys, phone-call screening, CAD, the globe.
Where it is behind: reach (channels), memory, proactivity, tool breadth, and proof that
it works live.

### Others worth knowing [web unless tagged]

| Project | What it is | What to take |
|---|---|---|
| Leon (`leon-ai/leon`, about 17.6k stars) | Long-running open personal assistant | Skill packaging ideas only. |
| `AnubhavChaturvedi-GitHub/jarvis-ai-assistant` (5–7k) | Voice-first agent that controls the computer | Confirms demand for computer use (S11). |
| `isair/jarvis` (about 1.2k) | Private, offline voice assistant | Offline mode as a selling point (S10d). |
| `ethanplusai/jarvis` | Voice layer over Claude Code on macOS | Nothing needed. |
| microsoft/UFO² | Windows desktop agent: UI Automation first, vision fallback, runs in a picture-in-picture desktop | The grounding approach and "don't steal the owner's mouse" (S11). |
| `ahujasid/mcp-for-blender` (MIT, about 32.7k stars, renamed Sept 2026) | Drive Blender from an LLM | Not adopted: it runs arbitrary Python in Blender. Extend our own `workers/blender_scene.py` instead (S14). |
| `homeassistant-ai/ha-mcp` and HA's built-in MCP server | Home Assistant over MCP | Not needed: the native integration has per-device approvals MCP would bypass. Use HA's WebSocket for events (S12). |
| Arwes (sci-fi UI framework) | Alpha; React 18 only; no strict mode; last push Feb 2025 | Not adopted. Borrow the ideas: frames, animator, bleeps (S13). |
| mem0, Letta, Graphiti | Memory layers | Not adopted; see S6. |
| GLaDOS (`dnhkng/GLaDOS`), OpenJarvis (Stanford), Pipecat, sherpa-onnx **[recall]** | Low-latency local voice; local-first agent framework; voice pipeline framework; ONNX speech toolkit | The direct pipeline pattern and sherpa-onnx as the one local speech runtime (S10). |

---

## E. What is lacking overall (one list)

1. Proof it works live, and a way for the builder to see the owner's logs.
2. Fast, reliable answers to ordinary questions.
3. A UI with life: motion, depth, sound, telemetry, a hero core.
4. Memory of the owner across conversations.
5. Proactivity and routines.
6. Reach from the phone, and remote approvals.
7. Messages (WhatsApp, Telegram, email triage).
8. Calls that work in Malaysia without a Twilio regulatory bundle.
9. Natural barge-in and "only my voice".
10. Real CAD features, then printing.
11. Homelab awareness and realtime home events.
12. Computer use beyond the browser.
13. Remote MCP servers (HTTP + OAuth).
14. Context-aware security (taint).
15. Evals, latency budget, a flight recorder.
16. Offline fallback.
17. Release work (M5): installer, updates, Android acceptance, CI.

---

## Sources (web search, Nov 2026)

- OpenClaw architecture and stars: [DEV: lessons from OpenClaw's architecture](https://dev.to/ialijr/lessons-from-openclaws-architecture-for-agent-builders-1j93), [OpenClaw docs: architecture overview](https://clawdocs.org/architecture/overview), [All Things Open](https://allthingsopen.org/articles/openclaw-viral-open-source-ai-agent-architecture), [How OpenClaw works (insiderllm)](https://insiderllm.com/guides/how-openclaw-works/)
- OpenClaw security: [Zenity Labs: OpenClaw or OpenDoor?](https://labs.zenity.io/p/openclaw-or-opendoor-indirect-prompt-injection-makes-openclaw-vulnerable-to-backdoors-and-much-more), [Known vulnerabilities](https://clawdocs.org/security/known-vulnerabilities), [TechRadar](https://www.techradar.com/pro/here-are-the-openclaw-security-risks-you-should-know-about), [hoodini/openclaw red-team notes](https://github.com/hoodini/openclaw), [HiddenLayer](https://www.hiddenlayer.com/research/exploring-the-security-risks-of-ai-assistants-like-openclaw)
- JARVIS-like repos: [GitHub topic jarvis-ai](https://github.com/topics/jarvis-ai), [nazirlouis/ada_v2](https://github.com/nazirlouis/ada_v2)
- WhatsApp libraries: [whatsmeow-node comparison](https://nicastelo.github.io/whatsmeow-node/docs/comparison), [whatsmeow-node FAQ](https://nicastelo.github.io/whatsmeow-node/docs/faq), [Best open-source WhatsApp libraries in 2026](https://whatsapp.checkleaked.cc/blog/best-open-source-whatsapp-libraries)
- GSM modem voice: [Quectel forum: EC25 voice over USB](https://forums.quectel.com/t/ec25-voice-over-usb/4262), [EC25-E UAC not detected](https://forums.quectel.com/t/ec25-e-efar-usb-audio-uac-not-detected-and-no-call-audio-firmware-request/60487), [EC25 QPCMV uplink issue on VoLTE](https://forums.quectel.com/t/ec25-j-ec25jfar06a04m4g-dcm-qpcmv-uplink-audio-works-only-on-the-first-volte-call-after-reboot-request-latest-standard-firmware/61775), [Malaysia 3G shutdown background](https://soyacincau.com/2020/08/30/malaysia-switch-off-3g-2021-what-you-need-to-know/)
- Windows hands-free API: [PhoneLineTransportDevice (Microsoft Learn)](https://learn.microsoft.com/en-us/uwp/api/windows.applicationmodel.calls.phonelinetransportdevice), [BestOwl/MyPhone](https://github.com/BestOwl/MyPhone), [MyPhone issue: API no longer works on 22H2](https://lightrun.com/answers/bestowl-myphone--phonelinetransportdevice-api-no-longer-works-on-windows-22h2)
- Memory layers: [Agent memory compared (DEV)](https://dev.to/sebastian_chedal/agent-memory-038-knowledge-systems-compared-2026-guide-568p), [Eight agent memory systems](https://rickhigh.substack.com/p/eight-agent-memory-systems-none-of)
- Desktop agents: [UFO² overview](https://microsoft.github.io/UFO/ufo2/overview), [UFO2 paper](https://arxiv.org/abs/2504.14603v2)
- Home Assistant MCP: [HA MCP Server integration](https://www.home-assistant.io/integrations/mcp_server/), [homeassistant-ai/ha-mcp](https://github.com/homeassistant-ai/ha-mcp)
- Speech toolkit: [sherpa-onnx on PyPI](https://pypi.org/project/sherpa-onnx)
- UI: [Arwes docs](https://arwes.dev/docs), [Arwes on Hacker News](https://news.ycombinator.com/item?id=36446637)
- Blender MCP: [OSS Insight: ahujasid/blender-mcp](https://ossinsight.io/analyze/ahujasid/blender-mcp)
