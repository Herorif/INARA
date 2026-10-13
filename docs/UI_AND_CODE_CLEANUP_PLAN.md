# INARA code cleanup and JARVIS interface plan

Updated 13 October 2026. This extends the [system architecture](INARA_REVAMP_PLAN.md) and translates the [project findings](PROJECT_REVIEW.md) into implementation work. Make the application easier to maintain and give it a responsive JARVIS-style interface while meeting the laptop resource budgets.

The cleanup and interface changes should ship in reviewable increments. Preserve existing user data and working integrations, establish shared contracts, then move features behind those contracts. The interface should reveal actual assistant state and make creative work easy to inspect and revise.

## Code organization

Use four clear boundaries: interface, assistant services, adapters and workers. Interface code presents state and sends requests. Services own tasks, conversations, permissions and persistence. Adapters integrate applications and devices. Workers own expensive computation and their dependency environments.

| Current area | Target responsibility | Concrete changes |
| --- | --- | --- |
| `backend/server.py` | Transport and lifecycle entry point | Move orchestration and tool implementations into services; retain thin validated routes and startup/shutdown hooks. |
| `backend/inara.py` | Voice adapter | Extract audio-device handling, session lifecycle and transcript processing; move conversation and tool dispatch to the independent core. |
| `backend/core/server.py` | Archived migration reference | Compare behavior and contracts, port useful pieces individually, then archive with a clear boundary; do not maintain two supported servers. |
| `backend/tools.py`, `backend/llm/tools.py`, `backend/core/tool_registry.py` | One authoritative tool contract | Deduplicate declarations; generate provider-specific tool schemas and client types from the same definitions. |
| `backend/llm/` and model literals elsewhere | Provider adapters and model profiles | Remove import-time client creation and scattered model IDs; validate credentials and capabilities lazily. |
| Legacy and newer CAD/web agent implementations | One implementation per capability | Keep adapters thin, port validated behavior and remove duplicates only once parity checks pass. |
| `backend/project_manager.py` and reminder storage | Project and persistence services | Add non-destructive migration, unique revision paths, transactional reminder transitions and explicit retention. |
| Telephony and phone agent | Call adapter and restricted call service | Keep codec handling at adapter boundaries; callers never inherit the owner's permissions. |
| `src/App.jsx` | Application shell | Extract navigation, workspace layout, window controls and status; feature components own their local view behavior. |
| `src/services/socketSubscriptions.js` | Typed transport adapter | Replace status-string parsing with structured events; preserve a compatibility bridge during migration. |
| `src/store/` | Feature state with narrow subscriptions | Separate persistent domain state from temporary UI state and frame/audio buffers; avoid whole-app updates for high-frequency signals. |
| `src/hooks/useVideoCapture.js`, `useHandTracking.js` | Shared capture and tracking clients | Load on activation, bundle matched runtime assets and release resources on disable/unmount. |
| Components with repeated window markup | Shared presentation primitives | Reuse panel, toolbar, status badge, progress, empty state, error boundary, modal and confirmation components. |
| Root test/debug scripts and `trace.txt` | Manual diagnostics and generated output | Move purposeful scripts into `scripts/`; exclude generated logs and experiments from release artifacts. |

Within the desktop app, organize by feature rather than one growing components directory:

```text
src/
  app/                     Shell navigation routes and bootstrap
  features/
    assistant/             Chat voice and activation views
    studio/                Workspace layout and project controls
    cad/                   Modeling forms viewer and revisions
    images/                Generation editing and gallery
    vision/                Camera tracking and watch controls
    inbox/                 Notification summaries and owner actions
    devices/               Smart devices and printers
    jobs/                  Progress history and cancellation
    settings/              Privacy performance and integrations
  shared/
    ui/                    Reusable accessible components
    design/                Tokens typography and motion
    transport/             Typed requests and event adapter
    hooks/                 Truly shared hooks
```

Service domain code must not import FastAPI routes, Socket.IO or React assumptions. Providers must not select global projects or decide permissions. Workers must not reach directly into the owner's core database. Use explicit constructor dependencies instead of mutable module globals or monkey-patching private methods. Keep public interfaces small and document side effects.

## Cleanup sequence and quality gates

1. Establish a source-control checkpoint and a safe backup/export of existing projects, memory and settings. Separate secret configuration from shareable configuration. Inventory recoverable data before running code that currently initializes or clears temporary projects.
2. Create a reproducible development environment: locked Python dependency groups, a supported Node baseline, the frontend lockfile, documented start commands and separate optional worker installs.
3. Add formatting and static checks: Ruff for Python, TypeScript plus ESLint/formatting for the frontend. Apply formatting once per migrated area, separately from logic changes where practical, so behavior changes remain reviewable.
4. Capture the existing request/event contracts, then introduce typed request, result, error, event and capability models. Move one capability through the new dispatcher at a time.
5. Fix functional issues while extracting their owning service: permission enforcement, canonical paths, reminder state, recoverable sessions and independent typed conversations. Do not preserve an identified bug merely to achieve superficial parity.
6. Consolidate configuration and tool definitions. Add structured logs carrying request/job IDs, redact credentials and keep debugging output outside product conversations.
7. Retire duplicated code after its supported behavior is covered. Remove unused imports, dead branches and abandoned files only after checking references and installation paths.
8. Add Windows CI for the supported build and deterministic tests, with opt-in integration runs for paid APIs and real devices. Record intentional compatibility exceptions rather than blanket-disabling checks.

Tests should prove useful behavior: authorization cannot be bypassed through a direct UI route, a typed request works with no microphone, a due reminder emits once, cancelled work releases its lease, and a failed generation preserves the previous valid revision. Avoid tests that only mirror method names or accept an exception as success.

Measure module complexity and dependency direction. A growing file with multiple responsibilities should be split by ownership rather than an arbitrary line limit. Add concise architecture and contribution guidance so future implementations do not recreate the global audio-loop coupling.

## JARVIS visual direction

Use a deep graphite background, restrained cyan instrument lines, clear white body text and subtle depth. Build a recognizable voice core from concentric rings and waveform motion. Use angular panel details and small telemetry labels around useful content, with the model or artifact as the focus in Studio.

Proposed tokens:

| Token | Starting value or rule |
| --- | --- |
| Background | `#080D14` |
| Main surface | `#101B28` |
| Raised surface | `#162536` |
| Primary text | `#EAF4FF` |
| Secondary text | `#A6BDCF` |
| Primary accent | `#56DAF5` |
| Success | `#6DE2B5` |
| Attention | `#FFC670` |
| Error | `#FF8585` |
| Spacing | 4 px base scale, with consistent 8/12/16/24/32 px steps |
| Typography | Readable sans-serif body; locally bundled Share Tech Mono for selected HUD labels and telemetry |
| Motion | Short 120–220 ms interaction transitions; low-frequency ambient motion only while visible |

These colors are starting values, not a completed contrast audit. Verify actual text/surface combinations and focus states before release. Reserve glow for active state and selection. Use explicit labels as well as color. Bundle fonts locally to avoid startup network requests.

The visual state machine should represent `idle`, `listening`, `processing`, `waiting_for_owner`, `working`, `speaking`, `offline` and `error`. Listening expands the core and displays a live waveform; working puts progress in the relevant task panel; owner input pauses with a clear action card. Display real progress or an honest indeterminate state. Decorative telemetry must not imply work or measurements that are not happening.

## Responsive layouts

| Surface | Layout behavior |
| --- | --- |
| Resident | Tray status and notifications; no continuously rendered HUD |
| Quick panel | Compact voice core, transcript, composer and current action; expand only when the result needs space |
| Studio at wide widths | Navigation rail, resizable conversation/task pane, primary artifact canvas and optional inspector |
| Smaller laptop window | Collapse secondary panes into tabs or drawers; preserve the primary task and composer |
| Fold8 cover screen | One primary pane with bottom navigation and touch-sized actions |
| Fold8 unfolded | Adaptive list/detail panes, with conversation or job context beside the preview |

Use CSS Grid, flex layout and container queries within the desktop shell. Keep docked panels as the default; optional floating panels can preserve the old experience. Persist layout by viewport class and project. Clamp floating panels to usable bounds after resizing, display changes and DPI changes. Do not derive the complete interface from a set of absolute window coordinates.

The voice core must scale down when an artifact requires room. Keep typing, cancel, approval and export actions visible. Support normal window controls, keyboard navigation, a command palette, drag-and-drop reference files, local file previews and a visible way to return from full-screen views.

For creative work, provide parameter controls, object/feature selection, measurement tools, revision history and compare views. For long tasks, show stage, result location and cancel state. The phone should display a compressed preview and job status rather than attempt to run the laptop's creative stack.

## Rendering and interaction performance

Animate the voice core with a single controlled renderer and bounded work. Start with a 30 FPS decorative animation budget; use a higher rate only for visible interactions that benefit from it. Stop animation when hidden or minimized and respect reduced-motion preferences. Offer a low-motion setting that retains the same status information.

Render static CAD views on demand and cap pixel ratio on dense displays. Dispose of replaced Three.js geometry, materials, textures and listeners. Do not retain hidden viewers. Lazy-load the 3D, camera and image modules; preload only after the owner opens the feature or requests its capability.

Keep audio meters and landmark updates outside React's broad state subscriptions. Use references, narrowly subscribed state or a dedicated worker/canvas path, and send semantic events to React at a bounded rate. Capture one camera stream per chosen source, with subscriber-based start and stop. Reuse image buffers where practical and enforce backpressure on preview delivery.

Keep blur, shadows and transparent compositing bounded. Profile the interface while voice and a creative worker run, and while a game owns GPU capacity. Viewport size alone must not trigger repeated model loads, network sessions or scene reconstruction.

## Interface acceptance criteria

- At 1280×720, 1920×1080 and representative ultrawide sizes, no primary controls overlap or leave the usable viewport. Test Windows display scaling at 100%, 125%, 150% and 200%.
- At narrow widths and Fold8 posture changes, the conversation, draft input and active job survive the layout change.
- All main flows work by keyboard, focus is visible, text can scale to 200%, and screen readers receive meaningful status and action labels. Target at least 4.5:1 contrast for ordinary body text and at least 44×44 logical-pixel primary touch targets.
- The quick panel meets the architecture's activation budget on the actual Legion. Set interaction and frame-time thresholds from recorded hardware baselines; aim for immediate visible acknowledgement within 100 ms for local UI actions.
- Hidden/minimized UI performs no decorative rendering or unnecessary camera work. Closing the workspace preserves service-owned jobs and reminders.
- No artificial dashboard numbers, simulated completion percentages or permanently spinning indicators appear in production.
- Empty, disconnected, denied, loading, cancelled and error states are designed for each feature, including a visible recovery action.
- Browser/worker failures are contained by a feature error boundary so other assistant capabilities remain usable.
- Visual checks include real artifact previews, representative conversations, long filenames and localized text; fixture-only screenshots are insufficient for the final release.

## WhatsApp scope

Notification summaries can be included with owner-enabled access. Exclude reply drafting and sending from the initial implementation. If the owner later asks for those features, each use still requires a specific draft or send instruction. A draft instruction does not authorize sending. Automatic acknowledgements, schedules and notification-triggered replies are excluded.

Apply this rule in capability exposure and backend authorization, not only in a prompt or UI toggle. Add behavioral checks before exposing a future reply tool. The initial inbox should have summary, open original message and create reminder actions, with no send action.

## Implementation checkpoints

Complete the contract and service cleanup before connecting the phone. Establish the design tokens and shared UI primitives early, then rebuild the quick panel and workspace shell. Migrate one feature at a time into that shell and profile each new viewer. Finish each checkpoint with working behavior, meaningful checks, visual review and recorded resource measurements before expanding scope.
