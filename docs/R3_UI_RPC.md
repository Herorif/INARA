# R3a shared panel and RPC foundation

Implemented 19 October 2026. This is the first bounded R3 slice: Image atelier uses the new lifetime/contract boundary; the lazy workspace shell shares presentation. Other feature internals remain on their existing clients.

## Ownership and recovery

`src/transport/rpc.ts` owns a panel's Socket.IO acknowledgements, deadlines and removable subscriptions. Disconnect immediately rejects outstanding calls, late callbacks settle nothing, and dispose releases only this scope's listeners. New requests require a connected socket and an open scope. Requests are never replayed automatically. A reconnect subscriber explicitly refreshes history.

`RpcError` distinguishes a known rejection from an uncertain delivery/result (timeout, disconnect, invalid ACK or send failure). Image atelier keeps uncertain work out of the failed state and offers history refresh; the backend remains the owner of actual jobs, cancellation and approval. Closing the panel disposes local requests and sends the existing `image_close` event. Original wire names and backend grants do not change.

Image sessions are keyed by selected project. Async preview/download work retains a project generation guard and releases its Blob URLs. History refresh accepts only its latest response, merges monotonic job state and retains live revisions received while the snapshot was in flight. A stale submit acknowledgement cannot overwrite a completed job. Manual refresh during a normal active submission is disabled; uncertainty enables explicit history recovery.

## Contract boundary

| Area | Authority and verification |
| --- | --- |
| Image recipe/submit/artifact/job request and stats | Existing Pydantic models; `scripts/export-ui-contracts.py` exports TypeScript declarations plus JSON Schema, including constraints/defaults |
| Schema drift | `python scripts/export-ui-contracts.py --check` is a CI gate |
| ACKs and image result/event envelope | Handwritten TypeScript response types with minimal runtime shape checks; these are not claimed to be generated backend response models |
| Field constraints/authorization | Server validation and shared dispatcher remain authoritative; TypeScript does not enforce numeric ranges or permissions |
| Compiler scope | `tsconfig.ui.json` targets the new transport boundary and positive/negative request examples in `tests/types/image-contracts.ts` |

TypeScript was introduced at the boundary rather than converting the entire React application. [Official migration/type-checking guidance](https://www.typescriptlang.org/docs/handbook/type-checking-javascript-files.html) supports incremental checked areas.

**Semantic compiler verification remains pending.** No local TypeScript compiler was available. Normal npm registry access failed with `CERT_HAS_EXPIRED`; Python/system trust attempts also failed. Certificate verification was retained. No compiler dependency/version or lock entry was invented, and no successful `tsc` run is claimed. Vite successfully transpiles/bundles these modules and Node 24 runs the real TypeScript source in runtime tests. Install and pin a verified compiler, update the dependency lock and add `tsc -p tsconfig.ui.json` locally/CI before expanding the TypeScript migration.

## JARVIS panel presentation

`PanelHeader` provides the shared layered mark, restrained cyan instrument line, title and close control. Its on-demand label describes panel activation, not model health or activity. `PanelState` provides loading, offline, empty and recovery surfaces with an optional explicit action. Compact recovery cards stack at narrow widths. Loading animation respects reduced motion. Feature error boundaries reset when the selected feature changes; lazy feature loading and existing focus trapping/Escape behavior remain.

Image atelier uses these surfaces for history sync, lost connections and errors. Other panels share the shell/loading/error boundary but have not yet migrated their feature-specific states or RPC lifecycle.

## Verification and limits

- 34 Node checks pass (eight new RPC/history cases). They cover disconnect/no replay, stale ACKs, scope isolation/dispose, deadlines/offline behavior, strict ACKs, history races, event/export shape guards and synchronous transport failure.
- 104 focused Python route/image/application checks pass. Backend runtime behavior and route inventory are unchanged. Ruff, generated-contract drift and whitespace checks pass.
- Vite production build passes. Initial JS is approximately 244.82 KB; Image atelier is still lazy. Existing build/module-type notices remain.
- [Native image report](qa/r3a-image-verification.json): deliberately injected history error, explicit recovery, real keyboard Tab wrap/Escape, fixture revisions/downloads, reopen without regeneration, cancellation, no external asset requests and 1440/390/768 widths pass. All three fixture workers exited; warmed resident recovery 66.15 MB. No diffusion model ran.
- [CAD report](qa/r3a-cad-verification.json): the shared shell preserves model/scene rendering, GLB import/download, history restore and responsive widths. All four workers exited; warmed resident recovery 66.70 MB.
- Screenshots were visually inspected: [desktop recovery](qa/r3a-image-recovery-desktop.png) and [narrow recovery](qa/r3a-image-recovery-mobile.png). Controls/text fit without horizontal overflow.

The short resident samples are not game or sustained-load benchmarks. Actual image generation, physical audio/camera/printers, Blender, Android pairing and phone/SIM handling remain separate work. Configuration and the real-game benchmark remain deferred. WhatsApp drafting/sending remains excluded. Hosted CI was updated but has not run remotely.

## Next bounded R3 slice

1. Restore verified registry access and pin the TypeScript compiler; run the scoped semantic/negative checks and add their CI gate. Keep this limitation visible until it passes.
2. Migrate CAD RPC/planner/artifact lifecycle to the established scope and export its backend request contracts. Preserve scene revisions, artifact integrity checks, approvals, cancel/close and lazy Three.js loading.
3. Extract repeated creative history/status/toolbar presentation where the existing image/CAD behavior warrants a common component. Continue project/reconnect/deadline tests and desktop/narrow/DPI/reduced-motion review.
4. Move on to feature-specific event/store registration and remaining legacy panel interiors incrementally. The command palette and unified activity/artifact view remain later R3 slices; this checkpoint does not complete them.
