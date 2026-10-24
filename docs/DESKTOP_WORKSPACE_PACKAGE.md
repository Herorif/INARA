# Node-free desktop workspace pilot

Latest milestone: [portable Python/core desktop pilot](PORTABLE_CORE_RUNTIME.md) adds an isolated bundled runtime. The external-Python steps below describe the earlier workspace-only pilot. Installation/signing/clean-machine acceptance remain pending.

Implemented 21 October 2026. The native Electron workspace can now be staged and run without a separate Node/npm installation or `node_modules` tree. The pilot includes the installed Electron runtime, built renderer, bundled native main/preload and core Python source. **Python 3.12 and the configured core dependencies remain external.** This is an unsigned developer pilot, not a self-contained installer or production release.

## Build and stage

With the existing Node development toolchain and built UI, run:

```powershell
.tools/node-v24.21.0-win-x64/node.exe scripts/build-desktop-bundle.cjs
# Use the new bundle directory printed by that command:
.venv/Scripts/python.exe scripts/desktop-package.py stage --directory .runtime/releases/my-new-desktop-pilot --bundle .runtime/desktop-bundles/<id>
.venv/Scripts/python.exe scripts/desktop-package.py verify --directory .runtime/releases/my-new-desktop-pilot
```

No download, installation, startup registration, signing, profile migration or existing-pilot overwrite occurs. The bundler uses installed esbuild and the pinned installed Electron version; generated main code includes socket client dependencies and capture lifecycle logic. Only Electron/Node builtins and the WebSocket library's optional acceleration modules remain external. Pure JavaScript fallbacks were exercised with external package resolution disabled. Preload remains isolated and sandboxed. Renderer tools retain their existing lazy loading.

Build-input/output hashes bind the native bundle to the current inputs. Staging rejects stale bundle inputs, modified outputs, version mismatches, incomplete runtimes, linked paths and unexpected runtime file types. Known profile/settings/environment files are excluded using the existing reviewed source-pilot allowlists. Electron license and Chromium notice files are retained, as are legal comments in bundled code. This is not redistribution clearance: dependency/model notices and license review remain release gates. [Electron distribution guidance](https://www.electronjs.org/docs/latest/tutorial/application-distribution).

`desktop-pilot.json` records every included file's size/hash and explicitly sets `self_contained: false`, `signed: false`, `external_python_required: true`, `node_runtime_required: false`. The manifest is written last; incomplete stages do not become valid pilots. Verify rejects missing/modified/extra files, case-insensitive duplicates, traversal and unsupported manifest claims. Hashes detect drift; they do not prove authenticity or prevent an owner rewriting the manifest.

## Runtime and data boundaries

`resident/layout.py` selects the fixed `runtime/electron/electron.exe` layout when a valid pilot marker is present. Missing/malformed pilot runtime never falls back to source npm dependencies. The source checkout continues using its existing installed Electron layout. Pilot mode ignores development-server selection. The native host retains its owned kill-on-close process job and private stdin bootstrap. Python bytecode suppression can pass through the owned worker environment without admitting Python path/secret variables.

The pilot contains `scripts/pilot-start.ps1`, which requires an explicit external Python 3.12 executable and a **new data directory outside the pilot**:

```powershell
# Developer pilot only; the Python environment must already satisfy requirements-core.lock.
./scripts/pilot-start.ps1 -PythonExecutable C:/path/to/configured/python.exe -PilotDataDirectory C:/path/to/new-isolated-pilot-data
```

Run that launcher from the staged pilot. It verifies package integrity first, refuses an existing data directory or linked parent, and explicitly redirects settings, protected database, projects, legacy-import location and desktop identity/profile into the new isolated directory. It neither adopts nor migrates the owner's real profile. Process environment overrides restore after exit. It downloads no Python/dependencies and makes no global execution-policy changes. Normal Python imports still require an existing compatible core environment; this milestone does not make a copied venv portable.

The native acceptance harness launches through the same staged core/runtime layout with isolated data. The PowerShell launcher was syntax checked; full launcher failure/recovery and clean-machine installer acceptance are not implied. Optional physical/model/call routes are not accepted packaged capabilities in this milestone.

## Acceptance

**37 packaging/native/release Python checks pass**, plus Python lint, PowerShell parser and diff checks. Tests cover drift, extra/missing files, unsafe paths, misleading self-contained claims, case collisions, stale bundle inputs, incomplete/mismatched runtimes, preservation of existing stages and refusal to fall back to npm from a broken pilot.

An actual 329-file pilot was staged from existing local components at `.runtime/releases/desktop-pilot-20261021-v2`. The hidden native harness imported the **staged core**, launched the **staged Electron/bundled main**, disabled external npm resolution, navigated five destinations at 390/1440px and verified zero media/external-network requests. No model/device workers loaded. It stopped gracefully and passed a full package integrity check afterward. External Python was used explicitly. [Evidence](qa/desktop-package-verification.json), [staged Studio](qa/packaged-studio.png), [390px Assistant](qa/packaged-assistant-390.png).

## Next release work

1. Assemble and validate an isolated portable Python/core dependency runtime from reviewed, explicitly supplied local inputs. Do not relabel/copy a venv as portable or silently download models/toolchains. Exercise the packaged core without development Python paths.
2. Define the install/version-slot/data layout and recovery behavior; test clean Windows installation/uninstallation while preserving explicitly selected owner data. No automatic production activation or profile migration is implemented here.
3. Complete dependency/license review, owned signing identity, signed desktop/mobile artifacts and explicit interrupted-update rollback. Local hashes and Electron vendor binaries do not sign INARA's application package.
4. Android compilation remains blocked by missing toolchain/dependency records; actual phone/capability/call tests remain separate. [Android build tooling](ANDROID_BUILD_ACCEPTANCE.md), [call bridge gate](CALL_LAB.md), [release gates](RELEASE_GATES.json). The real-game benchmark remains deferred.
