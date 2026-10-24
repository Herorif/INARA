# Renderer and copied-asset build provenance

Implemented 21 October 2026. Production Vite builds now write `dist/renderer-provenance.json`. New desktop package staging requires that evidence, rechecks the matching local inputs and binds the renderer manifest digest into `desktop-pilot.json`. The packaged verifier checks its output inventory, graph consistency, copied assets and retained ownership snapshot without Node or a development checkout.

## Observed build graph

`scripts/renderer-provenance.cjs` observes the installed Vite/Rollup production build and the separate Vite worker builds. It records physical raw-file hashes, normalized module identities/import edges, per-chunk module membership, build configuration/lock/collector inputs, copied public files and the final on-disk output inventory. Main and worker graph identities are distinct. Virtual module identities are hashed with the workstation root removed; absolute source paths are not published. This follows the build hooks described by [Rollup](https://rollupjs.org/plugin-development/) and [Vite 5](https://v5.vite.dev/guide/api-plugin).

The camera tracker's worker has its own graph, including the MediaPipe code and raw WASM/loader inputs. Byte-identical input/output mappings explicitly trace copied files, including JavaScript loaders that would otherwise resemble generated chunks. The public model is checked against the unchanged copied output. Icons retained outside `dist` are also inventoried and checked during packaging.

The manifest distinguishes all loaded graph modules from the module membership actually reported for generated chunks. Distribution auditing selects npm component records from recorded chunk membership and copied-asset origins, unioned with native Electron bundle inputs. It retains nested package paths/version identities. Tree-shaken/unused lock entries no longer automatically appear as renderer dependencies. This is evidence of the observed build, not proof that every vendored subcomponent has its own npm record or that output transformation is independently reproducible.

All application source files, local asset/public files and selected build controls are snapshotted before compilation. Loaded physical module files are observed at load time and rechecked before the manifest is written. Changed inputs, shared/linked files, public-copy collisions and stale manifest reuse refuse. A failed build does not mint a new manifest. The observer supports this project's local `dist`/`public` layout and one-shot client builds; SSR/watch/custom layouts need an explicit contract extension.

The manifest bounds file inventories and metadata size. The Python verifier rejects noncanonical/escaping paths, duplicate records, open/cross-target graphs, unknown chunk members, inconsistent or omitted byte-identical copy records, incomplete public-copy inventories, missing/extra/changed outputs and stale or unsupported ownership claims. Source verification also refuses added/deleted/changed files under `src`, `public` and `assets`. It does not archive source, dump environment variables, capture credentials or claim a hermetic build environment. Hidden plugin/tool dependencies, runtime downloads, generated/vendor internals, native subcomponents and all license obligations still need review.

## Ownership is explicit and pending

[ASSET_OWNERSHIP.json](ASSET_OWNERSHIP.json) starts with exact SHA-256 records for the two local INARA icons and `public/hand_landmarker.task`. Their origin is unverified, owner is unset, license evidence is empty and decision is pending. Existing file names and project MIT metadata do not establish their ownership. No model or replacement asset was downloaded or activated.

The actual build also inventories the MediaPipe WASM and loader under their exact installed npm package. That establishes an observed package path/version, not redistribution clearance. All **five asset inputs remain pending** in the audit. The current registry accepts only pending entries; a future owner-reviewed decision format must bind authoritative source/license evidence before approval can have any effect. Removing the pending label or editing a file cannot silently grant clearance.

## Package compatibility and commands

```powershell
.tools/node-v24.21.0-win-x64/node.exe node_modules/vite/bin/vite.js build
.venv/Scripts/python.exe scripts/renderer-provenance.py --directory dist --source .
.tools/node-v24.21.0-win-x64/node.exe scripts/build-desktop-bundle.cjs
# Use the NEW bundle directory printed above, and a NEW candidate destination.
.venv/Scripts/python.exe scripts/desktop-package.py stage --directory .runtime/releases/my-new-renderer-pilot --bundle .runtime/desktop-bundles/<new-id> --python-runtime .runtime/python-runtimes/core-20261021-v2
.venv/Scripts/python.exe scripts/desktop-package.py verify --directory .runtime/releases/my-new-renderer-pilot
.venv/Scripts/python.exe scripts/distribution-audit.py collect --candidate .runtime/releases/my-new-renderer-pilot --output .runtime/distribution-audits/my-new-renderer-audit
.venv/Scripts/python.exe scripts/distribution-audit.py verify --candidate .runtime/releases/my-new-renderer-pilot --output .runtime/distribution-audits/my-new-renderer-audit
```

The generated renderer manifest, ownership registry and Python validator are included in new candidates. Package staging refuses stale/missing evidence before creating its destination. Its own verification rechecks the manifest digest and packaged asset/public/lock/project/registry inputs. New evidence cannot silently lose its package binding. Older candidates remain readable and explicitly report `legacy-unrecorded`; they do not gain an exact renderer provenance claim retroactively. Old source-only release tooling does not constitute the new desktop evidence gate.

## Acceptance

The development-host candidate is `.runtime/releases/renderer-provenance-20261021`, with **2,993 inventoried files** and bundled Python/core/Electron. Its renderer manifest records **2,162 physical input records, 2,155 module records, 45 chunks, 67 outputs and one worker target**. The manifest itself is additional to those output records, avoiding a recursive self-hash. Renderer membership/copy origins identify **25 installed npm package paths**.

The matching audit is `.runtime/distribution-audits/renderer-provenance-20261021`: **75 component records and 82 notice evidence files**. Two observed bundled npm records still lack recognized local notice files: `@mediapipe/tasks-vision` 0.10.22-rc.20250304 and `@react-three/fiber` 8.18.0. The older six-record conservative audit remains historical; excluding unused records does not resolve their licenses or prove that vendored internals are cleared. No notice text was fetched or substituted.

**107 focused Python tests and six Node build-observer tests pass**, with scoped Ruff and an actual production build. They cover output/source drift, inventory/graph/copy closure, worker package origins, review-state preservation, package-stage refusal before mutation, removal of a package binding and exact audit selection. [Sanitized acceptance evidence](qa/renderer-provenance-verification.json) records actual package/audit verification and native acceptance separately.

Actual bundled-core/Electron acceptance passes twice consecutively: five destinations at 390/1440 pixels, one owned offline CAD worker, no external npm resolution, zero media/external requests, graceful shutdown and unchanged package bytes. [Studio](qa/renderer-provenance-studio.png), [narrow assistant](qa/renderer-provenance-assistant-390.png). The initial sandbox run could not create a tray icon; an early unsandboxed run failed before UI checks without a diagnostic location. Its cause was not established. The harness now records exception type/file/line; both subsequent fresh-profile runs pass. These attempts remain retained and are not clean-machine stability evidence.

The build retains the existing Vite CJS API, aged Browserslist data and large-chunk warnings. No dependency update or automatic database download was performed. These observations feed the next baseline review; successful compilation is not a security/support decision. All testing remains on the development machine with isolated synthetic data, not a clean Windows release acceptance.

## Next implementation

The [digest-bound distribution review ledger](DISTRIBUTION_REVIEW.md) is now implemented; all real decisions remain pending. Next is explicit publisher/reviewer identity and trust policy plus authenticated whole-payload packaging preparation, followed by actual signing, clean-machine installation/removal/recovery acceptance and signed opt-in updates. Gather authoritative evidence only within the owner's configuration/download constraints. Certificate provisioning and real clean-machine/device acceptance still require their own evidence.

Recovery compatibility beyond the existing typed adapters, Android build/device acceptance, physical SIM/personal WhatsApp control/duplex media and configured creative providers remain separate gates. WhatsApp text/outgoing actions stay off and the real-game benchmark remains deferred.
