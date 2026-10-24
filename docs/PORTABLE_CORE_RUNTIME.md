# Portable Python/core desktop pilot

Implemented 21 October 2026. This extends the [Node-free workspace pilot](DESKTOP_WORKSPACE_PACKAGE.md) with its own isolated Windows x64 Python/core runtime. It remains an unsigned local development pilot, with no installer, profile migration, signing or clean-machine acceptance.

## Assembly and launch

`scripts/python-runtime.py` assembles a new runtime from the installed base CPython and exactly 41 versions in `requirements-core.lock`. It does not copy or relabel the venv. Package files are selected from RECORD, checked against SHA-256/size and copied with licenses/metadata; old command shims, caches and private direct-URL metadata are omitted and RECORD is rewritten. Missing payload, changed versions, dependency-closure gaps, links, path injection and overlapping files reject. Standard library and native DLLs are copied separately; test/Tk/venv/bootstrap tools are excluded. No download or dependency installation occurs.

The retained local interpreter is CPython **3.12.10**, not a claim of the newest or security-reviewed release. Refreshing this baseline and license/redistribution review remain release requirements.

`python312._pth` pins imports to the runtime zip, DLLs, bundled site-packages and runtime directory, with no `import site`. Registry, environment and user paths are excluded. Trusted application entrypoints explicitly add their packaged backend path. Owned Python workers use `-B`: isolated mode ignores environment flags, so an environment-only bytecode setting is insufficient. [Python isolation rules](https://docs.python.org/3.12/library/sys_path_init.html), [installed package RECORD specification](https://packaging.python.org/en/latest/specifications/recording-installed-packages/).

```powershell
.venv/Scripts/python.exe scripts/python-runtime.py assemble --directory .runtime/python-runtimes/my-new-core
.venv/Scripts/python.exe scripts/desktop-package.py stage --directory .runtime/releases/my-new-core-pilot --bundle .runtime/desktop-bundles/513f562a-1b42-4e0a-8b4b-5fdafb63f0c2 --python-runtime .runtime/python-runtimes/my-new-core
```

Both destinations must be new direct children of their staging roots. Existing candidates remain intact on failure; incomplete directories are invalid. `desktop-core-pilot` resolves the fixed bundled Python and Electron paths. `pilot-start.ps1` rejects an external Python override for this kind and requires a new isolated data directory outside the package. Existing workspace-only pilots still require explicit external Python. No development-runtime fallback, production-profile adoption, startup setting or persistent execution-policy change is performed.

For a deliberately selected staged candidate:

```powershell
& .runtime/releases/my-new-core-pilot/runtime/python/python.exe -I -B .runtime/releases/my-new-core-pilot/runtime/python/runtime-probe.py --report .runtime/my-runtime-probe.json
powershell -NoProfile -ExecutionPolicy Bypass -File .runtime/releases/my-new-core-pilot/scripts/pilot-start.ps1 -PilotDataDirectory C:/path/to/new-isolated-pilot-data
```

The execution-policy argument applies only to that process. Hashes detect drift; unsigned manifests do not authenticate a publisher. Native Windows/OS dependencies still require clean-machine testing; self-contained here means the Python/core/Electron application runtimes, not every optional feature.

## Acceptance

The final local candidate is `.runtime/releases/desktop-core-20261021-v2`: 2,982 inventoried files, including the 2,651-file isolated runtime and all 41 locked dependencies. No external Python or npm is needed by the candidate.

- **58 focused Python checks** cover assembly, changed/missing files, lock drift, traversal, unsupported claims, curated metadata, package integrity and resident layout. Scoped Ruff and PowerShell parser checks pass. An actual PowerShell launcher check rejects an external Python override before creating data.
- The real packaged binary passes native extension imports, all dependency versions, SQLite, TLS context creation and AES-GCM. Pip, pytest, NumPy, Torch and sounddevice are absent. With conflicting PYTHONHOME/PYTHONPATH and a working-directory sentinel, all import paths remain inside the runtime, even without command-line `-I`. [Sanitized binary/isolation evidence](qa/portable-core-isolation.json).
- Native workspace acceptance runs the packaged core/Python/Electron, visits five destinations at 390/1440px and performs one owned offline CAD build. The CAD subprocess uses bundled Python and exits. Shutdown leaves the package unchanged. No model/device worker, media capture or external request starts. [Native acceptance](qa/portable-core-verification.json), [Studio](qa/portable-core-studio.png), [narrow Assistant](qa/portable-core-assistant-390.png).

## Next implementation

[Version slots and interrupted-install recovery](DESKTOP_VERSION_SLOTS.md) are now implemented with separate data ownership and explicit rollback. Next: original-account protected full-profile backup/restore and recovery validation. Preserve current pilots and real profiles. Then complete signing/license review, clean-machine install/uninstall and sustained Legion acceptance. No updater or production activation is claimed here.

Android compilation/toolchain provisioning remains pending. Actual Fold/Legion call-specific control and isolated duplex audio must still be proven separately for SIM and personal WhatsApp. Provider setup, actual Blender/image/speech/camera adapters and real-game benchmarking remain deferred; WhatsApp text/outgoing actions remain off.
