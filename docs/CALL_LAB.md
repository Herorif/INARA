# Supervised Call bridge lab

Update, 23 October 2026: [local-only setup](LOCAL_ONLY_SETUP.md) is authorized and the live CLI/worker now require local Vosk/Windows SAPI message-taking with no cloud fallback. The earlier Gemini-specific prototype is historical. Actual controlled calls remain deferred until the owner is available; the desktop lab still exposes offline diagnostics only.

Implemented 20 October 2026. Connections and command search now open **Call bridge lab**, with local setup metadata, an explicit isolated lifecycle check, Stop and protected synthetic transcript review. The panel is loaded on demand. Opening it starts no provider, device, media stream or worker. It exposes no live-answer route. Personal WhatsApp text actions remain excluded.

The actual Windows worker runs inside an owned kill-on-close job. Its private bootstrap travels over inherited stdin; credentials and transcripts are absent from command arguments and staging receipts. An external heartbeat/deadline watchdog can terminate a stuck synchronous audio driver and its descendants. Cooperative Stop first allows bounded session cleanup; a forced kill cannot establish whether the phone call actually ended. Inspect the client whenever a live CLI receipt is uncertain.

The standalone `scripts/call-bridge.py run --live` now uses this supervisor. Its existing explicit enrollment, isolated endpoints, one-call lease and live budget-cap refusal remain. This is still an experimental CLI route: live usage admission, enrollment expiry, standing availability policy and physical acceptance are pending. The desktop socket API accepts only offline diagnostics.

## Ownership and lifetime

Four strict routes provide state/check/stop/record. They require the authenticated unlocked owner renderer and current project. A run belongs to its originating workspace; another renderer cannot stop it. The shared resource governor reserves a fixed diagnostic profile in the FIFO queue. Stop, disconnect, project change, lock, resource restriction and core close release ownership. Panel close requests Stop without reconnect/replay. Startup never resumes checks; interrupted durable entries become uncertain.

Diagnostic metadata keeps 24 displayed runs and a 256-request non-replay ledger per owner/project. Synthetic records use a separate scoped DPAPI database with the existing seven-day-on-access retention. The UI cannot import the older unscoped CLI records. Both simulated identity verification and message confirmation remain false. Raw audio is never retained.

## Verification and limits

Focused Python acceptance: **103 passed** across call lifecycle, lab and route policy. Frontend: **98 passed**, including four new call-client checks. Types, generated contracts, lint and production build pass. Native job acceptance exercised real Windows child processes with synthetic controls/media/voice: normal completion, cooperative Stop and termination of a deliberately stalled worker plus descendant. Four observed process handles signaled exit. [Worker evidence](qa/call-lab-supervision.json).

The broad Python run could not collect the optional authenticator module because NumPy is absent. With that module excluded: **1,103 passed, 30 skipped, three failures** in archived CAD-agent construction requiring an unconfigured Gemini key. No dependencies or credentials were installed to make those legacy tests pass. These outcomes are separate from the passing call checks.

Native UI acceptance verifies actual scoped socket requests, readiness, Stop, completed record review and panel-close cancellation. The panel fits 390px; the shared shell retains five-destination navigation, keyboard/modal behavior, reduced motion and 200% zoom/text checks. [UI evidence](qa/call-lab-ui-verification.json), [desktop](qa/call-lab-desktop.png), [record](qa/call-lab-record-desktop.png), [narrow record](qa/call-lab-record-390.png). Three explicit synthetic check requests activated no device/provider/creative adapters or external network/media. Resource admission used deterministic hardware counters; this is not a host capacity benchmark. Short resident working set recovered from 65.72 MB before UI opening to 68.25 MB after exit; sustained load and real-game tests remain deferred.

Reproduce with:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_call_bridge.py tests/test_call_lab.py tests/test_route_policy.py -q
.tools/node-v24.21.0-win-x64/node.exe --test tests/*.mjs
.venv/Scripts/python.exe scripts/verify-call-lab.py
.venv/Scripts/python.exe scripts/verify-command.py
```

No real SIM/WhatsApp controls, audio devices, drivers, phones or paid providers were used. Physical call feasibility remains open for each channel. The next integration gate is controlled proof of call-specific controls and isolated duplex audio on the actual Fold/Legion; then add validated enrollment and core live usage admission before exposing live owner controls or syncing real receipts to Android. Software simulations cannot complete that gate.
