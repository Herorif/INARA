"""Assemble a Windows CPython/core runtime from pinned, already-installed local files."""

import argparse
import base64
import csv
import hashlib
import importlib.metadata as metadata
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PTH = "python312.zip\nDLLs\nLib/site-packages\n.\n"
BASE_FILES = {
    "python.exe",
    "pythonw.exe",
    "python3.dll",
    "python312.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
    "LICENSE.txt",
}
SKIP_STDLIB = {
    "site-packages",
    "__pycache__",
    "test",
    "tests",
    "idlelib",
    "tkinter",
    "turtledemo",
    "ensurepip",
    "venv",
}


def sha(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            value.update(chunk)
    return value.hexdigest()


def safe(path):
    path = Path(path).absolute()
    if path.resolve() != path or not path.is_file():
        raise ValueError("Missing or linked runtime input")
    return path


def relative(name):
    value = PurePosixPath(name)
    if (
        not name
        or value.is_absolute()
        or value.as_posix() != name
        or any(part in {"..", ".", ""} for part in value.parts)
        or "\\" in name
        or ":" in name
    ):
        raise ValueError("Unsafe runtime path")
    return value


def canonical(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def locked(path):
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)", line)
        if not match or canonical(match[1]) in result:
            raise ValueError("Core lock needs unique exact versions")
        result[canonical(match[1])] = match[2]
    if not result:
        raise ValueError("Core lock is empty")
    return result


def pe64(path):
    with safe(path).open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise ValueError("Expected Windows executable")
        stream.seek(60)
        offset = struct.unpack("<I", stream.read(4))[0]
        if offset > 1048576:
            raise ValueError("Unexpected PE header")
        stream.seek(offset)
        if stream.read(6) != b"PE\x00\x00\x64\x86":
            raise ValueError("Only Windows x64 inputs are supported")


def distributions(site, pins):
    from packaging.requirements import Requirement

    candidates = {}
    for dist in metadata.distributions(path=[str(site)]):
        key = canonical(dist.metadata["Name"])
        if key in pins:
            if key in candidates or dist.version != pins[key] or not dist.read_text("RECORD"):
                raise ValueError("Pinned dependency is duplicate, changed or missing RECORD")
            candidates[key] = dist
    if set(candidates) != set(pins):
        raise ValueError("Installed core environment does not match the lock")
    for dist in candidates.values():
        for text in dist.requires or []:
            requirement = Requirement(text)
            if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
                continue
            name = canonical(requirement.name)
            if (
                requirement.url
                or name not in pins
                or not requirement.specifier.contains(pins[name], prereleases=True)
            ):
                raise ValueError("Core dependency closure is not locked")
    return candidates


def copy_recorded(dist, site, destination):
    records = []
    record_name = None
    # Read RECORD directly: metadata.files filters missing files on Python 3.12.
    # Missing payload must fail verification rather than silently disappear.
    for row in csv.reader(io.StringIO(dist.read_text("RECORD") or "")):
        if len(row) != 3 or not row[0]:
            raise ValueError("Malformed dependency RECORD")
        name, digest_text, size_text = row
        entry = metadata.PackagePath(name)
        entry.hash = metadata.FileHash(digest_text) if digest_text else None
        entry.size = int(size_text) if size_text else None
        if ".." in entry.parts:
            # Installed Windows command shims embed the old interpreter path.
            # They are not runtime imports and are deliberately not copied.
            if (
                len(entry.parts) == 4
                and entry.parts[:3] == ("..", "..", "Scripts")
                and name.endswith(".exe")
            ):
                continue
            raise ValueError("Dependency RECORD escapes site-packages")
        value = relative(name)
        if (
            "__pycache__" in value.parts
            or value.suffix == ".pyc"
            or value.name == "direct_url.json"
        ):
            continue
        if value.suffix in {".pth", ".egg-link"} or value.name == "pyvenv.cfg":
            raise ValueError("Executable/path injection metadata is not supported")
        if value.name == "RECORD" and value.parent.name.endswith(".dist-info"):
            record_name = name
            continue
        source = safe(site.joinpath(*value.parts))
        if not source.is_relative_to(site):
            raise ValueError("Dependency file is outside the selected environment")
        expected = entry.hash
        digest = sha(source)
        if expected and (
            expected.mode != "sha256"
            or base64.urlsafe_b64encode(bytes.fromhex(digest)).decode().rstrip("=")
            != expected.value
        ):
            raise ValueError("Installed dependency failed its RECORD hash")
        if entry.size is not None and source.stat().st_size != entry.size:
            raise ValueError("Installed dependency size changed")
        target = destination.joinpath(*value.parts)
        if target.exists():
            raise ValueError("Dependencies overlap installed files")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if sha(target) != digest:
            raise ValueError("Dependency changed while copying")
        records.append(
            (
                name,
                "sha256=" + base64.urlsafe_b64encode(bytes.fromhex(digest)).decode().rstrip("="),
                target.stat().st_size,
            )
        )
    if not record_name:
        raise ValueError("Dependency RECORD is missing")
    # Re-record the curated installation: omitted shims/cache/private URLs are absent.
    target = destination.joinpath(*relative(record_name).parts)
    output = io.StringIO(newline="")
    csv.writer(output).writerows([*records, (record_name, "", "")])
    target.write_text(output.getvalue(), encoding="utf-8", newline="")


def inventory(directory):
    result = []
    for path in directory.rglob("*"):
        if path.resolve() != path or path.is_symlink() or path.is_junction():
            raise ValueError("Linked runtime payload")
        if path.is_file():
            result.append(path)
        if len(result) > 15000:
            raise ValueError("Runtime inventory exceeded its bound")
    return result


def assemble(destination, root=ROOT, base=None, site=None):
    if sys.platform != "win32" or sys.version_info[:2] != (3, 12):
        raise ValueError("Build with the existing Windows Python 3.12 environment")
    base = Path(base or sys.base_prefix).resolve()
    site = Path(site or (Path(sys.prefix) / "Lib/site-packages")).resolve()
    destination = destination.absolute()
    if (
        destination.parent != root.resolve() / ".runtime/python-runtimes"
        or destination.exists()
        or destination.resolve() != destination
    ):
        raise ValueError("Choose a NEW direct child of .runtime/python-runtimes")
    if (base / "pyvenv.cfg").exists():
        raise ValueError("A venv cannot supply the base interpreter")
    pins = locked(root / "requirements-core.lock")
    selected = distributions(site, pins)
    for name in BASE_FILES:
        safe(base / name)
    pe64(base / "python.exe")
    pe64(base / "python312.dll")
    destination.mkdir(parents=True)
    for name in BASE_FILES:
        shutil.copyfile(base / name, destination / name)
    (destination / "DLLs").mkdir()
    for path in sorted((base / "DLLs").iterdir()):
        if path.suffix.lower() in {".dll", ".pyd"} and not path.stem.startswith(
            ("_test", "_ctypes_test", "_tkinter", "tcl", "tk")
        ):
            shutil.copyfile(safe(path), destination / "DLLs" / path.name)
    stdlib = []
    for folder, dirs, files in os.walk(base / "Lib", followlinks=False):
        dirs[:] = sorted(name for name in dirs if name not in SKIP_STDLIB)
        for name in sorted(files):
            path = Path(folder) / name
            if path.suffix in {".py", ".txt", ".pickle", ".json", ".cfg"} and name not in {
                "sitecustomize.py",
                "usercustomize.py",
            }:
                stdlib.append(safe(path))
    if not stdlib or len(stdlib) > 5000:
        raise ValueError("Unexpected standard library inventory")
    with zipfile.ZipFile(
        destination / "python312.zip", "w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for source in stdlib:
            info = zipfile.ZipInfo(
                source.relative_to(base / "Lib").as_posix(), date_time=(1980, 1, 1, 0, 0, 0)
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, source.read_bytes())
    target = destination / "Lib/site-packages"
    target.mkdir(parents=True)
    for name in sorted(selected):
        copy_recorded(selected[name], site, target)
    (destination / "python312._pth").write_text(PTH, encoding="ascii")
    shutil.copyfile(root / "scripts/python-runtime-probe.py", destination / "runtime-probe.py")
    records = [
        {
            "path": path.relative_to(destination).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha(path),
        }
        for path in sorted(inventory(destination))
    ]
    value = {
        "format": 1,
        "kind": "isolated-python-core",
        "python_version": sys.version.split()[0],
        "architecture": "win-x64",
        "isolated": True,
        "signed": False,
        "core_lock_sha256": sha(root / "requirements-core.lock"),
        "dependencies": pins,
        "files": records,
    }
    (destination / "runtime-manifest.json").write_text(
        json.dumps(value, indent=2), encoding="utf-8"
    )
    return verify(destination, root / "requirements-core.lock")


def verify(directory, lock=None):
    directory = directory.absolute()
    manifest = safe(directory / "runtime-manifest.json")
    if manifest.stat().st_size > 4_194_304:
        raise ValueError("Excessive runtime manifest")
    value = json.loads(manifest.read_text(encoding="utf-8"))
    if (
        value.get("format") != 1
        or value.get("kind") != "isolated-python-core"
        or value.get("architecture") != "win-x64"
        or value.get("isolated") is not True
        or value.get("signed") is not False
        or not value.get("python_version", "").startswith("3.12.")
    ):
        raise ValueError("Unsupported core runtime")
    if lock and (
        value.get("core_lock_sha256") != sha(lock) or value.get("dependencies") != locked(lock)
    ):
        raise ValueError("Runtime dependency lock changed")
    records = value.get("files", [])
    if not isinstance(records, list) or not 1 <= len(records) <= 15000:
        raise ValueError("Unexpected runtime file inventory")
    expected = {"runtime-manifest.json"}
    folded = {"runtime-manifest.json"}
    for record in records:
        name = relative(record["path"]).as_posix()
        if (
            name.casefold() in folded
            or type(record["bytes"]) is not int
            or not 0 <= record["bytes"] <= 536_870_912
        ):
            raise ValueError("Duplicate or excessive runtime file")
        folded.add(name.casefold())
        expected.add(name)
        path = safe(directory / name)
        if path.stat().st_size != record["bytes"] or sha(path) != record["sha256"]:
            raise ValueError("Runtime file changed")
    required = BASE_FILES | {
        "python312.zip",
        "python312._pth",
        "runtime-probe.py",
        "DLLs/_ctypes.pyd",
        "DLLs/_ssl.pyd",
        "DLLs/_sqlite3.pyd",
    }
    if (
        not required.issubset(expected)
        or (directory / "python312._pth").read_text(encoding="ascii") != PTH
    ):
        raise ValueError("Incomplete or unisolated Python runtime")
    actual = {path.relative_to(directory).as_posix() for path in inventory(directory)}
    if actual != expected or any(
        name.endswith((".pth", ".egg-link", "pyvenv.cfg", ".pyc"))
        or "__pycache__" in name.split("/")
        for name in actual
    ):
        raise ValueError("Unexpected development/path/cache payload")
    pins = value.get("dependencies")
    if not isinstance(pins, dict) or not pins:
        raise ValueError("Missing locked dependencies")
    site = directory / "Lib/site-packages"
    distributions(site, pins)
    installed = [
        canonical(dist.metadata["Name"]) for dist in metadata.distributions(path=[str(site)])
    ]
    if sorted(installed) != sorted(pins):
        raise ValueError("Unpinned dependency metadata in runtime")
    pe64(directory / "python.exe")
    pe64(directory / "python312.dll")
    return {
        "integrity": "passed",
        "kind": value["kind"],
        "files": len(records),
        "dependencies": len(value["dependencies"]),
        "python_version": value["python_version"],
        "isolated": True,
        "signed": False,
        "runtime_execution_verified": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("assemble", "verify"))
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = (
            assemble(args.directory)
            if args.command == "assemble"
            else verify(args.directory, ROOT / "requirements-core.lock")
        )
    except (OSError, ValueError, KeyError, TypeError):
        parser.exit(
            1,
            "Core runtime assembly/verification failed. Preserve existing runtimes and inspect local pinned inputs; nothing was downloaded.\n",
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
