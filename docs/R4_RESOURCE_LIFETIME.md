# R4 capability diagnostics and creative-job ownership

Implemented as one milestone on 19 October 2026. The next milestone is R5 Creative Studio v2.

## Product behavior

Open **Capability center** from the command palette or the Command page system card. The lazy panel shares the existing JARVIS dialog, focus handling and responsive layout. It shows adapter/dependency detection, configuration presence, recent successful integration evidence, resource blocking and job duration separately. A detected key/model directory is not a verified provider/model. Placeholder API keys count as missing setup. Dependencies are inspected without importing their heavy modules. Diagnostics never start an adapter, model, device or download.

Hardware inspection reads logical CPU count and Windows physical-memory counters directly through the OS. Other platforms can use an already installed psutil; unsupported values remain unknown. GPU/VRAM detection remains unknown and no GPU probe imports Torch. Results cache for ten seconds and refresh only on demand/admission. No polling loop runs while the panel is closed. The panel is a snapshot: refresh after jobs/mode changes. This machine's counters are not confirmation of the user's Legion specifications.

Integration evidence is scoped to the authenticated owner's selected project and the most recent twelve jobs per adapter. Only a successful job tagged with the matching fixed profile counts. Verification fixtures cannot establish real image-model acceptance. Older jobs without resource provenance do not establish profile acceptance. Reported duration includes queue wait; it is not a peak-memory or FPS measurement. Text, voice and camera remain conservatively unverified until their acceptance work is implemented.

## Refactoring and profiles

`services/capability_profiles.py` owns fixed creative resource estimates, API-key placeholder handling and environment-backed model defaults. Active text/status/connection, voice, vision, browser and legacy CAD callers reference these defaults. Existing model names are preserved; they have not been validated against any provider. Archived server experiments are outside the supported composition root.

| Fixed profile | CPU threads estimate | RAM MB estimate | VRAM MB estimate | Execution |
| --- | ---: | ---: | ---: | --- |
| cad_offline | 2 | 512 | 0 | Owned offline geometry/scene worker |
| cad_blender | 2 | 2048 | 0 | Existing owned Blender bridge; installation required |
| image_cpu | 2 | 8192 | 0 | Owned local Diffusers worker; configuration required |
| verification_fixture | 1 | 256 | 0 | Injected test service only; never a production image backend |

The default creative budget is two CPU threads, 8192 MB RAM and zero GPU allocation. Admission also checks available physical memory with 1024 MB headroom and detected CPU count. Unknown counters fall back to this explicit budget, rather than invented hardware specifications. These values are scheduling estimates, **not OS-enforced CPU/RAM limits**. The existing Windows kill-on-close process ownership remains the lifetime boundary. Image generation no longer automatically selects CUDA: it uses the admitted CPU profile. A GPU profile requires later hardware/setup acceptance. There is no automatic CPU/GPU/cloud escalation.

## Queue and lifetime

`ResourceGovernor` is the single queue/reservation authority; its `creative_active` compatibility view points at reservations. `CreativeJobService` retains ownership of tasks, processes, captured owner/project context, durable job claims, validated artifacts and release. CAD and images share one FIFO queue: at most four admitted jobs, one worker at a time, three waiting. Jobs retain their fixed profile/resource estimates in encrypted history. The resource snapshot reports the running reservation separately from waiting-job count. Legacy/print ownership of the admission lock rejects new creative work immediately instead of creating an unbounded secondary wait queue.

Capacity and queue-full errors reject before creating a durable claim or worker. An accepted ID remains idempotent; an uncertain request never replays automatically. Waiting expires after 120 seconds. Capacity is rechecked on acquisition using the low-rate OS snapshot. Cancelling a waiter removes it without launching it, and the next admitted job proceeds in FIFO order. All cancellations are signalled before awaiting an owner's tasks, preventing queued jobs from starting during teardown. Print workflows reject when creative reservations exist; retained legacy CAD also respects the shared admission lock/reservation view.

Closing a creative panel cancels its jobs by default. An active job exposes **Continue this job after closing this panel**, unchecked by default. The strict UUID/boolean lifetime request is owner/project scoped and persists the deliberate choice. Activity displays panel/background ownership and can reopen the exact revision. Background means panel-independent within the current workspace/core session: losing the last owner renderer, closing/crashing the workspace/core, or entering resident/gaming mode still cancels it. It does not authorize tray-only GPU work or restart replay. Pending approvals/planners are cancelled on panel close regardless of job lifetime.

Worker crash, timeout, cancellation, queue timeout and validation/storage failure release the reservation. A process-close failure latches a resource fault until core restart; switching resource modes cannot clear it. A monitoring gap longer than fifteen seconds interrupts queued/running work, closes the owned process and requires a new request. This covers a suspended/stalled core without silently treating an old job as newly accepted. Physical sleep/resume acceptance remains deferred. Existing durable history reports a missing active queued/running job as interrupted after core restart.

## Contracts and validation

Three owner-renderer routes are added: `capability_diagnostics`, `cad_lifetime`, `image_lifetime`. The inventory now contains 55 socket routes; dispatcher tools remain 53 and voice mappings remain 37. Lifetime requests are generated from Pydantic into both creative schema/type files; the additive UI contract remains version 1. The typed diagnostics client validates report envelopes and nullable counters. No configuration or provider-credential mutation endpoint was added.

Tests exercise bounded/FIFO cross-adapter admission, cancelled-waiter fairness, resource rejection, capacity recheck, queue timeout, interruption, process-close faults, missing configuration, placeholder keys, project/owner isolation, gaming, background cancellation and reconnect/no-replay. Native image acceptance uses explicitly labelled fixtures; actual Diffusers/Blender/provider behavior is not claimed.

690 Python tests pass with one Blender-dependent skip; all 46 Node checks pass. Semantic TypeScript checks, generated-contract drift checks, scoped Ruff, production build and whitespace checks pass. CI includes the new backend/frontend cases; hosted CI has not been run here. The existing Vite CJS/chunk-size/Browserslist and Node module-type notices remain.

Native acceptance ran serially in isolated profiles, without API configuration or physical media/device access:

| Acceptance | Evidence | Result |
| --- | --- | --- |
| Native image UI + explicit background controls | [Report](qa/r4-image-verification.json) | Four labelled fixture workers started/exited; background survives panel close and restores through Activity; default panel closure cancels; history recovery and real fixture exports pass. No image model ran. Post-worker resident recovered to 66.54 MB. |
| Offline CAD + scene UI | [Report](qa/r4-cad-verification.json) | Four real offline workers exited; solids/scenes/exports, approvals and selected-revision restore pass. No geometry module loaded in the resident. Recovery 66.79 MB. |
| Native host lifecycle + failure recovery | [Report](qa/r4-native-verification.json) | Busy-port retry, fresh owner registration, reconnect/settings policy, crash cleanup, reminders, gaming and reopen pass. Ten-second idle: mean 67.24 MB, peak 67.25 MB, 0.1562% of one CPU core, zero Electron processes. This is a short sample, not the ten-minute performance target or a gaming benchmark. |

Visually inspected [desktop diagnostics](qa/r4-capabilities-desktop.png), [390px diagnostics](qa/r4-capabilities-mobile.png) and [background Activity](qa/r4-background-activity.png). The broader image UI checks also cover 768px and 1440px layouts. Hardware counters in these screenshots describe the execution environment, not a confirmed Legion specification.

## Remaining acceptance and next milestone

API/provider setup, model installations, exact Legion/Fold specifications, CUDA profiles, actual image generation, Blender execution, physical camera/audio/printer acceptance and the real-game benchmark remain deferred. No new ten-minute resident performance claim is made from the short recovery samples. Legacy generated-code/browser adapters still have their previously documented isolation limits; this milestone does not extend their capabilities. Existing SIM/personal WhatsApp identity remains unchanged, and WhatsApp reply drafting/sending remains excluded.

R5 builds selected-revision editing, constrained change sets with stale-base rejection, undo/redo and comparisons, clearer artifact/recipe reuse, and richer typed creative adapters only where installation and validation permit. R6 voice, R7 Android pairing and R8 selected read-only notifications follow.
