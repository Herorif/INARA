# Device and printer adapters / Connections readiness

Implemented 19 October 2026. This source milestone separates optional network integrations from retained printer profile/slicing orchestration and adds local readiness to Connections. Physical devices, real network discovery/control, provider configuration and dependency installation were not used for acceptance.

## Connections workspace

The Connections page now shows Smart home and Print workshop readiness before their action panels. A dedicated Connections readiness panel is also available from the command palette. It is responsive at desktop and 390px widths, supports explicit refresh and stays available in gaming mode.

`connections_state` requires an unlocked authenticated owner renderer and an empty strict request. The generated `ConnectionsState` response contains only local dependency booleans, loaded-instance booleans, saved-target counts, cached-observation counts, printer observation activity and whether an already-loaded printer adapter found a slicer. Endpoints, device names, profile paths, API keys and status payloads are excluded. State is missing dependency, setup later, unverified or cached observations; it never claims physical verification. Dependency presence does not prove SDK compatibility, authentication, network availability or hardware support.

Opening/refreshing readiness uses package metadata and existing in-memory caches. It does not load Kasa/printer adapters, locate a slicer through a new adapter, run discovery, contact devices, obtain cameras, start polling, invoke providers or install anything. The panel owns its RPC requests, drops late responses and clears on disconnect. No new resident timer or worker is introduced. Existing Kasa/printer discovery spinners now finish on server events/errors/disconnect instead of an invented five-second completion timer; offline/unverified Kasa controls are disabled.

## Separation

| Component | Responsibility |
| --- | --- |
| `devices/kasa.py` | Lazy SDK discovery/control, validation, cached observations, operation serialization, deadlines and disconnect cleanup |
| `kasa_agent.py` | Compatibility import of the controller; no eager SDK import |
| `devices/printer_models.py` | Printer/status data without network dependencies; public printer dictionaries omit API keys |
| `devices/printer_discovery.py` | Explicit mDNS collection and browser/Zeroconf lifetime; advertised protocols only |
| `devices/printer_protocols.py` | Injected, bounded OctoPrint/Moonraker status, upload and separate start requests |
| `printer_agent.py` | Compatibility facade, endpoint registry, cached status/backoff and existing slicer/profile logic |
| `services/device_printers.py` | Existing shared authorization, settings persistence, adapter activation and observation ownership |
| `services/connections.py` / transport / UI | Local whitelisted readiness inspection and presentation |

The existing optional dependencies remain optional. No locks/model versions/provider keys were changed, and no downloads were performed. Kasa device capability properties and HTTP protocol behavior are verified with fixtures, not an installed SDK connected to real hardware.

## Kasa boundaries

The controller constructor imports no SDK and performs no I/O. Saved targets are initially offline/unverified. Explicit discovery keeps up to 64 cached observations, preserves missing saved entries and marks failed/missing observations offline. Alias/model strings are bounded and HSV is normalized for the UI. Unknown targets cannot trigger an implicit discovery during a control operation, and ambiguous aliases are rejected instead of choosing an arbitrary device. Brightness/HSV are validated before SDK calls.

Initialization/discovery has a 20 second cooperative operation deadline; SDK discovery requests five seconds, individual update requests three seconds and controls eight seconds. SDK disconnect is attempted after updates/control and on cancellation/close. Disconnects have two second per-device limits and grouped discovery/close cleanup has a three second cooperative limit with concurrency bounded to eight. Adapter close participates in the existing five second service cleanup envelope. Cached handles may be reused by the SDK; cleanup is not an OS process sandbox or a guarantee for non-cooperative vendor code. Authentication/firmware compatibility and actual device behavior remain unverified. Existing shared permissions continue to authorize discovery/control; no implicit retry or automatic physical action was added.

## Printer boundaries

Discovery owns each mDNS browser and the Zeroconf instance, cancelling/closing them on success, cancellation or partial setup failure. Collection accepts a positive interval up to eight seconds and keeps at most 64 advertised records; SDK setup/cleanup remains synchronous/cooperative. Only validated private/link-local IPv4 advertisement addresses are accepted; external DNS, public, loopback and special addresses are rejected without probing. IPv6/public-address devices require a future explicit supported endpoint workflow. Generic HTTP advertisements remain unknown. No HTTP protocol guessing, root-page probing, camera stream probing or implicit camera acquisition remains in discovery. Discovery never replaces an already configured host's endpoint, protocol, credentials or camera URL.

Saved API keys are retained during adapter activation and same-endpoint metadata updates, and omitted from public printer dictionaries/readiness. Multiple printers on the same host with different ports are retained independently. Bare-host selection becomes ambiguous and fails closed; an exact host:port or unique name selects a target. Status/backoff caches use host:port, and the durable print pipeline passes the captured host:port to upload/start instead of discarding the port. Per-stage endpoint/protocol validation and non-replayable print receipts remain intact.

The HTTP client validates the configured endpoint/protocol, sends credentials only to that endpoint and disables redirects and environment proxies. The retained transport is LAN HTTP; printer TLS/credential configuration is not introduced here. Requests do not try another protocol, alternate endpoint or automatic retry. Status reads use three second HTTP timeouts within an eight second cooperative operation limit; JSON is read incrementally with a 256 KiB bound. Malformed, unauthorized, redirected or out-of-range status is not marked online. Responses and sessions close on normal/error/cancel paths, and raw exception details are excluded from cached offline status. Existing polling/backoff remains in the facade/owned observation service.

Upload accepts only generated lowercase 32-hex `.gcode` filenames and nonempty files up to 128 MiB, with a 30 second request/operation limit. It sends one multipart upload to the configured protocol; no print/start/select form field is included. Moonraker failure no longer falls back to OctoPrint. Physical start remains a separate ten second request to the configured start endpoint, behind the existing separate dispatcher approval and durable print receipt. `upload_gcode(start_print=True)` now fails before network access; callers must use the independently approved stages. Timeout/cancellation may leave an uncertain remote effect, so failed mutations are not retried automatically.

Other printer protocols, full vendor feature parity, actual sliced-output quality and hardware behavior remain pending. Profile detection and the retained legacy slicer facade are not claimed as a new sandbox; supported slicing continues through the existing owned slicer worker.

## Acceptance

- Full supported regression: **1,053 Python passed / one installation-dependent Blender skip**. **121 final focused adapter/device/print tests passed** after tightening advertisement filters and saved-credential preservation. **94 Node passed**; type checks, generated-contract drift, Ruff, production build and whitespace checks passed. Existing Starlette/Vite/Browserslist/chunk notices remain.
- Injected tests cover exact protocol/port routing, separate upload/start, no redirects/fallback/retries, generated filename/size bounds, incremental JSON/status validation, cancellation cleanup, mDNS cleanup on partial setup/cancel, private IPv4 advertisement guards, ambiguous names, offline saved Kasa observations, SDK-handle cleanup, independent port backoff and saved credential preservation/redaction. No real network or physical-device test was run.
- `scripts/verify-connections.py` passed in the actual hidden renderer with isolated synthetic dependency/target metadata. Adapter activation was blocked before UI work and remained **zero**; no SDK discovery, devices, cameras, providers or mobile listener were activated. Navigation, refresh, command-palette access and private-endpoint exclusion passed. No hosted CI run is claimed.
- Screenshots were visually inspected at desktop and 390px. Native short resident samples were **65.31 MB before workspace / 66.49 MB after exit**. Heavy model/device SDK modules remained absent from the resident. These are short fixture samples, not a real-game benchmark or physical-device acceptance.

Evidence: [Connections page](qa/connections-desktop.png), [390px panel](qa/connections-390.png), [sanitized native report](qa/connections-verification.json).

Tests use injected SDK/session/mDNS factories and isolated project/profile data. Real hardware suites now require explicit `INARA_LIVE_HARDWARE_TESTS=1` opt-in and are not run for this milestone. Setting that variable alone is not hardware acceptance.

## Protocol references

The request separation follows the official [OctoPrint file API](https://docs.octoprint.org/en/main/api/files.html), [Moonraker file management](https://moonraker.readthedocs.io/en/latest/external_api/file_manager/) and [Moonraker printer API](https://moonraker.readthedocs.io/en/latest/external_api/printer/). Kasa discovery remains an optional integration with the [python-kasa discovery API](https://python-kasa.readthedocs.io/en/stable/guides/discover.html). These references establish protocol intent; they do not establish device compatibility or live acceptance.

## Next implementation

Extend optional AI blueprint proposals from single solids to typed multi-object scenes: bounded object count/dimensions/transforms/materials, preview-and-review before application, captured project/request scope, stale-proposal rejection, protected revisions and shared per-provider-call usage admission. Use injected provider proposals and the existing offline scene worker for acceptance; do not configure providers, download models, invoke Blender or run real image/camera/hardware tasks automatically. No arbitrary generated Python or shell execution. Interactive browser actions, Android build/device acceptance, real providers/hardware and signed distribution/update recovery remain separately gated. WhatsApp replies and call actions stay excluded.
