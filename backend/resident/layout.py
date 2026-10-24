"""Fixed workspace runtime layouts. A partial pilot never falls back to npm."""

import json
from pathlib import Path


def workspace_executable(root):
    root = Path(root).resolve()
    manifest = root / "desktop-pilot.json"
    if manifest.exists():
        if manifest.is_symlink() or manifest.stat().st_size > 4_194_304:
            raise ValueError("Invalid desktop pilot marker")
        value = json.loads(manifest.read_text(encoding="utf-8"))
        bundled = value.get("kind") == "desktop-core-pilot"
        if (
            value.get("format") != 1
            or value.get("kind") not in {"desktop-workspace-pilot", "desktop-core-pilot"}
            or value.get("self_contained") is not bundled
        ):
            raise ValueError("Unsupported desktop pilot layout")
        relative = "runtime/electron/electron.exe"
    else:
        relative = "node_modules/electron/dist/electron.exe"
    target = root / relative
    if target.resolve() != target or not target.is_file():
        raise ValueError("Workspace runtime is missing or linked")
    return target
