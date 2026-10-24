"""Stage and verify unsigned Node-free desktop pilots with optional isolated Python."""

import argparse
import importlib.util
import json
from pathlib import Path, PurePosixPath
import shutil

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "pilot_release_tools", ROOT / "scripts/release-tools.py"
)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
RUNTIME_REQUIRED = {
    "electron.exe",
    "icudtl.dat",
    "resources.pak",
    "LICENSE",
    "LICENSES.chromium.html",
    "version",
    "snapshot_blob.bin",
    "v8_context_snapshot.bin",
    "locales/en-US.pak",
}


def read_json(path, limit=4_194_304):
    if path.resolve() != path.absolute() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError("Missing, linked or excessive package metadata")
    return json.loads(path.read_text(encoding="utf-8"))


def files_in(directory):
    if directory.resolve() != directory.absolute() or not directory.is_dir():
        raise ValueError("Missing or linked payload tree")
    paths = []
    for path in directory.rglob("*"):
        if path.is_symlink() or path.is_junction() or path.resolve() != path.absolute():
            raise ValueError("Linked payload entry")
        if path.is_file():
            paths.append(path)
        if len(paths) > 20000:
            raise ValueError("Payload inventory exceeds its bound")
    return paths


def bundle_files(directory, root):
    directory = directory.absolute()
    if directory.parent != root / ".runtime/desktop-bundles":
        raise ValueError("Use a built direct child of .runtime/desktop-bundles")
    value = read_json(directory / "bundle-manifest.json")
    expected_version = read_json(root / "package.json")["devDependencies"]["electron"]
    if (
        value.get("format") != 1
        or value.get("kind") != "native-workspace-bundle"
        or value.get("node_runtime_required") is not False
        or value.get("electron_version") != expected_version
    ):
        raise ValueError("Unsupported or mismatched native bundle")
    if not 1 <= len(value.get("inputs", [])) <= 2048:
        raise ValueError("Bundle input provenance is missing")
    for item in value["inputs"]:
        relative = PurePosixPath(item["path"])
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or "\\" in str(relative)
            or ":" in str(relative)
        ):
            raise ValueError("Unsafe bundle input")
        path = root.joinpath(*relative.parts)
        if path.resolve() != path or release.sha256(path) != item["sha256"]:
            raise ValueError("Bundle inputs changed; rebuild the native bundle")
    records = value.get("files", [])
    if len(records) != 2 or {entry["path"] for entry in records} != {
        "native-main.cjs",
        "preload.js",
    }:
        raise ValueError("Unexpected bundle outputs")
    for entry in records:
        path = directory / entry["path"]
        if (
            path.resolve() != path
            or not path.is_file()
            or path.stat().st_size != entry["bytes"]
            or release.sha256(path) != entry["sha256"]
        ):
            raise ValueError("Native bundle changed")
    return value


def runtime_tool():
    spec = importlib.util.spec_from_file_location(
        "python_core_runtime", ROOT / "scripts/python-runtime.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def renderer_tool():
    spec = importlib.util.spec_from_file_location(
        "renderer_provenance", ROOT / "scripts/renderer-provenance.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stage(destination, bundle, root=ROOT, runtime_directory=None):
    root = root.resolve()
    destination = destination.absolute()
    if (
        destination.parent != root / ".runtime/releases"
        or destination.exists()
        or destination.resolve() != destination
        or destination.is_symlink()
        or destination.is_junction()
    ):
        raise ValueError("Choose a NEW direct child of .runtime/releases")
    bundle = bundle.absolute()
    info = bundle_files(bundle, root)
    renderer = renderer_tool().verify(root / "dist", root)
    runtime = root / "node_modules/electron/dist"
    runtime_files = files_in(runtime)
    names = {path.relative_to(runtime).as_posix() for path in runtime_files}
    if not RUNTIME_REQUIRED.issubset(names):
        raise ValueError("Installed Electron runtime is incomplete")
    if (runtime / "version").read_text().strip() != info["electron_version"]:
        raise ValueError("Electron runtime version mismatch")
    allowed = {
        ".exe",
        ".dll",
        ".pak",
        ".bin",
        ".dat",
        ".json",
        ".asar",
        ".html",
        ".txt",
        ".manifest",
    }
    if any(
        path.suffix.lower() not in allowed and path.name not in {"LICENSE", "version"}
        for path in runtime_files
    ):
        raise ValueError("Unexpected Electron runtime file")
    mapping = [
        (path, name)
        for path, name in release.payload(root)
        if not name.startswith("electron/") and name != "scripts/start.ps1"
    ]
    mapping += [
        (bundle / name, "electron/" + name)
        for name in ("native-main.cjs", "preload.js", "bundle-manifest.json")
    ]
    mapping += [
        (root / "scripts" / name, "scripts/" + name)
        for name in (
            "desktop-package.py",
            "desktop-install.py",
            "desktop-backup.py",
            "desktop-recovery.py",
            "desktop-control.py",
            "renderer-provenance.py",
            "setup-ui.ps1",
            "pilot-start.ps1",
        )
    ]
    mapping += [(root / name, name) for name in ("INARA Setup.cmd", "INARA Setup.ps1", "native/setup/Setup.xaml")]
    mapping += [(root / name, name) for name in ("dist/renderer-provenance.json", "docs/ASSET_OWNERSHIP.json")]
    mapping += [
        (path, "runtime/electron/" + path.relative_to(runtime).as_posix()) for path in runtime_files
    ]
    if runtime_directory is not None:
        runtime_directory = runtime_directory.absolute()
        if runtime_directory.parent != root / ".runtime/python-runtimes":
            raise ValueError("Use an assembled direct child of .runtime/python-runtimes")
        runtime_tool().verify(runtime_directory, root / "requirements-core.lock")
        mapping += [
            (path, "runtime/python/" + path.relative_to(runtime_directory).as_posix())
            for path in files_in(runtime_directory)
        ]
        mapping.append((root / "scripts/python-runtime.py", "scripts/python-runtime.py"))
    if len(mapping) > 20000 or sum(path.stat().st_size for path, _ in mapping) > 2_147_483_648:
        raise ValueError("Desktop pilot exceeded its payload budget")
    for source, name in mapping:
        release.safe_relative(name)
        if source.resolve() != source or not source.is_file():
            raise ValueError("Missing or linked package input")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir()
    records = []
    for source, name in mapping:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        records.append(
            {"path": name, "bytes": target.stat().st_size, "sha256": release.sha256(target)}
        )
    manifest = {
        "format": 1,
        "kind": "desktop-core-pilot" if runtime_directory else "desktop-workspace-pilot",
        "self_contained": runtime_directory is not None,
        "signed": False,
        "node_runtime_required": False,
        "external_python_required": runtime_directory is None,
        "python_version": "3.12",
        "electron_version": info["electron_version"],
        "renderer_provenance_sha256": renderer["manifest_sha256"],
        "files": records,
    }
    (destination / "desktop-pilot.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return verify(destination)


def verify(directory):
    directory = directory.absolute()
    if directory.resolve() != directory or directory.is_junction():
        raise ValueError("Linked pilot directory")
    manifest = read_json(directory / "desktop-pilot.json")
    bundled = manifest.get("kind") == "desktop-core-pilot"
    if (
        manifest.get("format") != 1
        or manifest.get("kind") not in {"desktop-workspace-pilot", "desktop-core-pilot"}
        or manifest.get("self_contained") is not bundled
        or manifest.get("signed") is not False
        or manifest.get("node_runtime_required") is not False
        or manifest.get("external_python_required") is not (not bundled)
        or manifest.get("python_version") != "3.12"
    ):
        raise ValueError("Unsupported desktop pilot manifest")
    records = manifest.get("files", [])
    if not isinstance(records, list) or not 1 <= len(records) <= 20000:
        raise ValueError("Missing or excessive pilot inventory")
    expected = {"desktop-pilot.json"}
    folded = {"desktop-pilot.json"}
    for entry in records:
        relative = release.safe_relative(entry["path"])
        name = relative.as_posix()
        if (
            name.casefold() in folded
            or type(entry["bytes"]) is not int
            or not 0 <= entry["bytes"] <= 536_870_912
        ):
            raise ValueError("Duplicate or excessive pilot file")
        expected.add(name)
        folded.add(name.casefold())
        path = directory.joinpath(*relative.parts)
        if (
            path.resolve() != path
            or not path.is_file()
            or path.stat().st_size != entry["bytes"]
            or release.sha256(path) != entry["sha256"]
        ):
            raise ValueError("Pilot file changed")
    required = {
        "backend/resident_main.py",
        "backend/resident/layout.py",
        "electron/native-main.cjs",
        "electron/preload.js",
        "electron/bundle-manifest.json",
        "dist/index.html",
        "requirements-core.lock",
        "scripts/pilot-start.ps1",
        "scripts/desktop-package.py",
    }
    required |= {"runtime/electron/" + name for name in RUNTIME_REQUIRED}
    if not required.issubset(expected):
        raise ValueError("Pilot runtime/entrypoints are incomplete")
    actual = {path.relative_to(directory).as_posix() for path in files_in(directory)}
    if actual != expected:
        raise ValueError("Unexpected pilot payload")
    if (directory / "runtime/electron/version").read_text().strip() != manifest.get(
        "electron_version"
    ):
        raise ValueError("Pilot runtime version changed")
    if bundled:
        runtime_tool().verify(directory / "runtime/python", directory / "requirements-core.lock")
    renderer_digest = manifest.get("renderer_provenance_sha256")
    renderer = None
    if renderer_digest is not None:
        tool = renderer_tool()
        renderer = tool.verify(directory / "dist")
        if renderer["manifest_sha256"] != renderer_digest:
            raise ValueError("Renderer provenance binding changed")
        value = read_json(directory / "dist/renderer-provenance.json", 8_388_608)
        for entry in value["inputs"]:
            if entry["path"].startswith(("public/", "assets/")) or entry["path"] in {"package.json", "package-lock.json", "docs/ASSET_OWNERSHIP.json"}:
                tool.check(directory, entry)
        if read_json(directory / "docs/ASSET_OWNERSHIP.json") != value["ownership_registry"]:
            raise ValueError("Packaged ownership snapshot differs")
    elif (directory / "dist/renderer-provenance.json").exists():
        raise ValueError("Renderer evidence lacks an explicit package binding")
    return {
        "integrity": "passed",
        "kind": manifest["kind"],
        "files": len(records),
        "self_contained": bundled,
        "signed": False,
        "node_runtime_required": False,
        "external_python_required": not bundled,
        "installed": False,
        "renderer_provenance": "verified" if renderer else "legacy-unrecorded",
        "note": "File integrity only, not authenticity or clean-machine runtime acceptance. No profile is included.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("stage", "verify"))
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--python-runtime", type=Path)
    args = parser.parse_args()
    if args.command == "stage" and args.bundle is None:
        parser.error("stage requires --bundle from build-desktop-bundle.cjs")
    try:
        result = (
            stage(args.directory, args.bundle, runtime_directory=args.python_runtime)
            if args.command == "stage"
            else verify(args.directory)
        )
    except (OSError, ValueError, KeyError, TypeError):
        parser.exit(
            1,
            "Desktop pilot validation failed. Preserve existing pilots/profile and rebuild from reviewed inputs.\n",
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
