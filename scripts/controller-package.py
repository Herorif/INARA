"""Offline trusted-controller assembly; final inventory is externally pinned before execution."""

import argparse
import importlib.util
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "controller_package_signed", ROOT / "scripts/signed-package.py"
)
signed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signed)
MANIFEST = "controller-manifest.json"
SCRIPTS = (
    "controller.py",
    "controller-package.py",
    "signed-package.py",
    "windows-signature.py",
    "admission.py",
    "windows-launch.py",
    "managed-update.py",
    "protected-state.py",
    "managed-ui.py",
    "managed-lifecycle.py",
    "desktop-backup.py",
    "desktop-recovery.py",
    "managed-ui.ps1",
    "open-trusted-controller.ps1",
    "release-trust.py",
    "distribution-review.py",
    "distribution-audit.py",
    "desktop-package.py",
    "desktop-install.py",
    "release-tools.py",
    "python-runtime.py",
    "renderer-provenance.py",
)
SOURCE = tuple("scripts/" + name for name in SCRIPTS) + (
    "requirements-core.lock",
    "docs/RELEASE_TRUST_POLICY.json",
    "docs/WINDOWS_SIGNING_POLICY.json",
    "LICENSE",
    "native/setup/Managed.xaml",
    "backend/services/storage.py",
)


def verify(directory, pin):
    directory = signed.plain(directory, True)
    manifest, raw = signed.read(directory / MANIFEST)
    signed.trust.digest(pin)
    if signed.trust.sha(raw) != pin:
        raise ValueError("Controller inventory pin differs")
    signed.review.exact(manifest, {"format", "kind", "files"})
    if (
        type(manifest["format"]) is not int
        or manifest["format"] != 1
        or manifest["kind"] != "inara-trusted-controller"
        or not isinstance(manifest["files"], list)
        or not 1 <= len(manifest["files"]) <= 15000
    ):
        raise ValueError("Unsupported controller inventory")
    expected, folded = {MANIFEST}, {MANIFEST.casefold()}
    total = 0
    for entry in manifest["files"]:
        signed.review.exact(entry, {"path", "bytes", "sha256"})
        name = signed.audit.relative(entry["path"]).as_posix()
        if name.casefold() in folded or not (name in SOURCE or name.startswith("runtime/")):
            raise ValueError("Unexpected or duplicate controller file")
        folded.add(name.casefold())
        expected.add(name)
        signed.trust.integer(entry["bytes"], 0, 536_870_912)
        signed.trust.digest(entry["sha256"])
        total += entry["bytes"]
        path = signed.plain(directory / name)
        if path.stat().st_size != entry["bytes"] or signed.digest_file(path) != entry["sha256"]:
            raise ValueError("Controller file differs from externally pinned inventory")
    if total > 2_147_483_648 or not set(SOURCE).issubset(expected):
        raise ValueError("Incomplete or excessive controller")
    actual = {p.relative_to(directory).as_posix() for p in signed.audit.package.files_in(directory)}
    if actual != expected:
        raise ValueError("Controller file closure differs")
    signed.audit.package.runtime_tool().verify(
        directory / "runtime", directory / "requirements-core.lock"
    )
    return {
        "integrity": "passed",
        "files": len(expected),
        "manifest_sha256": pin,
        "runtime_executed": False,
        "release_authorized": False,
    }


def stage(runtime, output):
    runtime, output = signed.plain(runtime, True), signed.plain(output)
    if output.exists() or output.is_relative_to(runtime) or runtime.is_relative_to(output):
        raise ValueError("Choose a NEW separate controller output")
    signed.audit.package.runtime_tool().verify(runtime, ROOT / "requirements-core.lock")
    inputs = [(ROOT / name, name) for name in SOURCE] + [
        (p, "runtime/" + p.relative_to(runtime).as_posix())
        for p in signed.audit.package.files_in(runtime)
    ]
    # Hash final supplied bytes before copying and recheck after. Signing must happen
    # BEFORE this stage; later Authenticode/timestamp writes invalidate this pin.
    records = [
        {
            "path": name,
            "bytes": signed.plain(path).stat().st_size,
            "sha256": signed.digest_file(path),
        }
        for path, name in inputs
    ]
    output.mkdir(parents=True)
    for (source, name), record in zip(inputs, records):
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as incoming, target.open("xb") as outgoing:
            shutil.copyfileobj(incoming, outgoing)
        if (
            signed.digest_file(target) != record["sha256"]
            or signed.digest_file(source) != record["sha256"]
        ):
            raise ValueError("Controller input changed during assembly")
    raw = signed.review.encoded(
        {
            "format": 1,
            "kind": "inara-trusted-controller",
            "files": sorted(records, key=lambda entry: entry["path"]),
        }
    )
    with (output / MANIFEST).open("xb") as stream:
        stream.write(raw)
    return verify(output, signed.trust.sha(raw))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("stage", "verify"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--expected-manifest")
    args = parser.parse_args()
    try:
        result = (
            stage(args.runtime, args.directory)
            if args.command == "stage"
            else verify(args.directory, args.expected_manifest)
        )
    except (OSError, ValueError, KeyError, TypeError):
        parser.exit(
            1,
            "Controller assembly/verification refused. Preserve inputs; nothing was downloaded.\n",
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
