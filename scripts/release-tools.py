"""Offline support inventory and source-pilot staging. Never reads private profile contents."""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "package.json",
    "package-lock.json",
    "requirements-core.in",
    "requirements-core.lock",
    "requirements-mobile.txt",
    "README.md",
    "LICENSE",
    ".env.example",
    "docs/RELEASE_GATES.json",
    "docs/RELEASE_READINESS.md",
)
TREES = ("backend", "electron", "dist", "assets", "public")
SCRIPTS = ("start.ps1", "launch-native.cjs", "release-tools.py")
BLOCKED = {
    ".env",
    "projects",
    ".runtime",
    ".venv",
    ".git",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def diagnostics(root=ROOT):
    """Whitelist only. No env dump, IPs, file listings, logs, usernames, IDs or secrets."""
    return {
        "format": 1,
        "platform": platform.system(),
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "python_supported": sys.version_info[:2] == (3, 12),
        "built_ui_present": (root / "dist/index.html").is_file(),
        "electron_present": (root / "node_modules/electron/dist/electron.exe").is_file(),
        "core_lock_present": (root / "requirements-core.lock").is_file(),
        "android_tools_present": {
            name: shutil.which(name) is not None for name in ("java", "javac", "gradle", "adb")
        },
        "android_sdk_configured": bool(os.getenv("ANDROID_HOME") or os.getenv("ANDROID_SDK_ROOT")),
        "private_content_included": False,
        "network_accessed": False,
        "limits": "Presence checks only; no provider, model, Android build or device acceptance implied.",
    }


def readiness(root=ROOT):
    value = json.loads((root / "docs/RELEASE_GATES.json").read_text(encoding="utf-8"))
    if value.get("format") != 1 or not isinstance(value.get("gates"), list) or not value["gates"]:
        raise ValueError("Invalid gate inventory")
    ids = set()
    for gate in value["gates"]:
        if (
            not isinstance(gate.get("id"), str)
            or gate["id"] in ids
            or gate.get("status") not in {"accepted", "pending", "blocked", "deferred", "excluded"}
            or type(gate.get("required")) is not bool
            or not gate.get("evidence")
        ):
            raise ValueError("Invalid release gate")
        ids.add(gate["id"])
    remaining = [
        gate for gate in value["gates"] if gate["required"] and gate["status"] != "accepted"
    ]
    return {
        "format": 1,
        "release_ready": not remaining,
        "required_remaining": remaining,
        "backlog": [gate for gate in value["gates"] if not gate["required"]],
        "note": "Recorded evidence inventory, not a substitute for executing acceptance checks.",
    }


def inventory(root=ROOT):
    packages = []
    for dist in importlib.metadata.distributions():
        meta = dist.metadata
        # Avoid metadata paths/direct URLs, which can contain user paths and credentials.
        packages.append(
            {
                "ecosystem": "python-installed",
                "name": meta.get("Name", "unknown"),
                "version": dist.version,
                "license": meta.get("License-Expression") or "REVIEW_REQUIRED",
            }
        )
    lock = json.loads((root / "package-lock.json").read_text(encoding="utf-8"))
    for path, value in lock.get("packages", {}).items():
        if not path or "node_modules/" not in path:
            continue
        packages.append(
            {
                "ecosystem": "npm-locked",
                "name": value.get("name") or path.rsplit("node_modules/", 1)[-1],
                "version": value.get("version", "unknown"),
                "license": value.get("license") or "REVIEW_REQUIRED",
                "integrity_recorded": bool(value.get("integrity")),
            }
        )
    return {
        "format": 1,
        "scope": "Installed Python environment (may include dev/optional packages) and npm lock; not an Android/model license audit",
        "packages": sorted(packages, key=lambda item: (item["ecosystem"], item["name"].lower())),
        "license_clearance": "REVIEW_REQUIRED; metadata inventory is not redistribution approval",
    }


def safe_relative(name):
    value = PurePosixPath(name)
    if (
        not name
        or value.is_absolute()
        or "\\" in name
        or ":" in name
        or any(part in (".", "..", *BLOCKED) for part in value.parts)
    ):
        raise ValueError("Unsafe release path")
    if value.as_posix() != name:
        raise ValueError("Non-canonical release path")
    return value


def payload(root):
    paths = [root / name for name in FILES] + [root / "scripts" / name for name in SCRIPTS]
    for tree in TREES:
        allowed = {
            "backend": {".py"},
            "electron": {".js", ".cjs"},
            "assets": {".png", ".ico", ".svg"},
            "public": {".task"},
            "dist": {".html", ".js", ".css", ".svg", ".png", ".ico", ".woff2", ".wasm", ".task"},
        }
        paths.extend(
            path
            for path in (root / tree).rglob("*")
            if path.is_file()
            and path.suffix.lower() in allowed[tree]
            and not set(path.relative_to(root).parts) & BLOCKED
        )
    if not (root / "dist/index.html").is_file():
        raise ValueError("Build the UI before staging a source pilot")
    for path in sorted(set(paths)):
        if (
            path.is_symlink()
            or path.resolve() != root.resolve() / path.relative_to(root)
            or not path.is_file()
        ):
            raise ValueError("Missing file or linked release payload")
        name = path.relative_to(root).as_posix()
        safe_relative(name)
        if path.suffix.lower() in (".sqlite3", ".db", ".enc", ".pem", ".key", ".pyc"):
            raise ValueError("Private/generated file in release payload")
        yield path, name


def stage(destination, root=ROOT):
    if destination.is_symlink() or destination.is_junction():
        raise ValueError("Linked staging destination")
    destination = destination.resolve()
    staging_root = root.resolve() / ".runtime/releases"
    if staging_root.resolve() != staging_root:
        raise ValueError("Linked staging parent")
    # Reversible staging only, never install outside the checkout or overwrite an old pilot.
    if destination.parent != staging_root or destination.is_symlink() or destination.exists():
        raise ValueError("Choose a NEW direct child of .runtime/releases")
    files = list(payload(root))
    staging_root.mkdir(parents=True, exist_ok=True)
    destination.mkdir()
    records = []
    for source, name in files:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        records.append({"path": name, "bytes": target.stat().st_size, "sha256": sha256(target)})
    # Manifest is written last. Partial staging never becomes a valid release.
    manifest = {
        "format": 1,
        "kind": "source-pilot",
        "self_contained": False,
        "signed": False,
        "requirements": [
            "Windows original-account DPAPI profile",
            "Python 3.12 venv from requirements-core.lock",
            "Node 24 and installed Electron/npm dependencies",
            "Explicit optional mobile dependencies",
        ],
        "files": records,
    }
    (destination / "release-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return verify(destination)


def verify(directory):
    if directory.is_symlink() or directory.is_junction():
        raise ValueError("Linked release directory")
    directory = directory.resolve()
    manifest = json.loads((directory / "release-manifest.json").read_text(encoding="utf-8"))
    if (
        manifest.get("format") != 1
        or manifest.get("kind") != "source-pilot"
        or manifest.get("self_contained") is not False
    ):
        raise ValueError("Unsupported release manifest")
    expected = {"release-manifest.json"}
    for entry in manifest["files"]:
        relative = safe_relative(entry["path"])
        if str(relative) in expected:
            raise ValueError("Duplicate release path")
        expected.add(str(relative))
        path = directory.joinpath(*relative.parts)
        if (
            path.resolve() != path
            or path.is_symlink()
            or not path.is_file()
            or path.stat().st_size != entry["bytes"]
            or sha256(path) != entry["sha256"]
        ):
            raise ValueError("Release file missing, linked or modified")
    actual = {
        path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file()
    }
    if any(path.is_symlink() for path in directory.rglob("*")) or actual != expected:
        raise ValueError("Unexpected release payload")
    return {
        "integrity": "passed",
        "files": len(expected) - 1,
        "kind": "source-pilot",
        "self_contained": False,
        "signed": False,
        "installed": False,
        "note": "Hashes detect drift, not authenticity. Review and signing/distribution acceptance remain required.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("diagnostics", "inventory", "readiness", "stage", "verify")
    )
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()
    if args.command in ("stage", "verify") and args.directory is None:
        parser.error("--directory is required")
    try:
        result = {
            "diagnostics": diagnostics,
            "inventory": inventory,
            "readiness": readiness,
            "stage": lambda: stage(args.directory),
            "verify": lambda: verify(args.directory),
        }[args.command]()
    except (ValueError, OSError, KeyError, TypeError):
        parser.exit(
            1,
            "Release check failed. Preserve the existing profile/pilot and inspect the chosen source and manifest.\n",
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
