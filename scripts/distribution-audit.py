"""Offline candidate-bound notice collection. No signing, downloads or license clearance."""

import argparse
from email.parser import Parser
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("audit_package", ROOT / "scripts/desktop-package.py")
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)
MAX_TEXT = 2_097_152
MAX_NOTICE = 33_554_432
MAX_EVIDENCE = 67_108_864


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def local(directory):
    value = Path(directory).absolute()
    if value.drive.startswith("\\\\") or value.resolve() != value or not value.is_dir():
        raise ValueError("Choose an existing unlinked local directory")
    return value


def relative(name):
    if not isinstance(name, str) or not name or len(name) > 1024:
        raise ValueError("Invalid evidence path")
    value = PurePosixPath(name)
    if (
        value.is_absolute()
        or value.as_posix() != name
        or any(part in {".", ".."} for part in value.parts)
        or "\\" in name
        or ":" in name
        or any(ord(c) < 32 for c in name)
    ):
        raise ValueError("Unsafe evidence path")
    return value


def read(base, name, limit=MAX_TEXT):
    path = base.joinpath(*relative(name).parts)
    if path.resolve() != path or not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError("Missing, linked or shared evidence file")
    if path.stat().st_size > limit:
        raise ValueError("Evidence file exceeds its bound")
    return path.read_bytes()


def label(value):
    if value is None:
        return "REVIEW_REQUIRED"
    if not isinstance(value, str) or len(value) > 512 or any(ord(c) < 32 for c in value):
        return "REVIEW_REQUIRED"
    return value.strip() or "REVIEW_REQUIRED"


def license_name(name):
    return bool(re.match(r"^(licen[cs]e|copying|notice|authors)([._-]|$)", name, re.I))


def npm_owner(name):
    """Return the innermost installed package path, including scoped/nested installs."""
    parts = relative(name).parts
    indices = [i for i, part in enumerate(parts) if part == "node_modules"]
    if not indices:
        return None
    index = indices[-1] + 1
    if index >= len(parts):
        raise ValueError("Incomplete npm input path")
    length = 2 if parts[index].startswith("@") else 1
    if len(parts) <= index + length:
        raise ValueError("Incomplete npm input path")
    return "/".join(parts[: index + length])


def collect(candidate, source=ROOT):
    candidate, source = local(candidate), local(source)
    integrity = package.verify(candidate)
    if integrity["kind"] != "desktop-core-pilot":
        raise ValueError("Audit requires a bundled core candidate")
    inputs, blobs, evidence = {}, {}, {}

    def observe(base, scope, name, notice=False, limit=MAX_TEXT):
        raw = read(base, name, MAX_NOTICE if notice else limit)
        key = scope + ":" + name
        record = {"scope": scope, "path": name, "bytes": len(raw), "sha256": digest(raw)}
        inputs[key] = record
        if notice:
            raw.decode("utf-8-sig")  # Refuse unreadable evidence instead of losing bytes.
            target = "notices/" + digest(raw) + ".txt"
            blobs[target] = raw
            if sum(map(len, blobs.values())) > MAX_EVIDENCE:
                raise ValueError("Collected notices exceed their total bound")
            evidence[key] = {**record, "copy": target}
        return raw, key

    def json_input(base, scope, name, limit=4_194_304):
        return json.loads(observe(base, scope, name, limit=limit)[0])

    pilot = json_input(candidate, "candidate", "desktop-pilot.json")
    runtime = json_input(candidate, "candidate", "runtime/python/runtime-manifest.json")
    native = json_input(candidate, "candidate", "electron/bundle-manifest.json")
    lock = json_input(candidate, "candidate", "package-lock.json")
    if (
        not isinstance(native.get("inputs"), list)
        or not 1 <= len(native["inputs"]) <= 2048
        or not isinstance(lock.get("packages"), dict)
        or not 1 <= len(lock["packages"]) <= 4096
        or not isinstance(runtime.get("dependencies"), dict)
        or not 1 <= len(runtime["dependencies"]) <= 512
    ):
        raise ValueError("Missing or excessive dependency provenance")
    # Source metadata is used only when it matches the lock shipped in this candidate.
    if observe(source, "source", "package-lock.json", limit=4_194_304)[0] != read(
        candidate, "package-lock.json", 4_194_304
    ):
        raise ValueError("Source npm lock differs from the candidate")
    for name in ("requirements-core.lock", "package.json"):
        observe(candidate, "candidate", name)
    components = []

    def component(ecosystem, name, version, license_value, scope, notices, metadata=None):
        components.append(
            {
                "ecosystem": ecosystem,
                "name": label(name),
                "version": label(version),
                "declared_license": label(license_value),
                "scope": scope,
                "metadata": metadata,
                "notices": sorted(notices),
                "redistribution_decision": "pending_owner_review",
            }
        )

    def notice_files(base, scope, folder, recursive=False):
        directory = base / relative(folder)
        if directory.resolve() != directory or not directory.is_dir():
            raise ValueError("Missing or linked notice directory")
        result = []
        entries = list(directory.rglob("*") if recursive else directory.iterdir())
        if len(entries) > 20000:
            raise ValueError("Excessive notice inventory")
        for path in sorted(entries):
            if path.resolve() != path or path.is_symlink() or path.is_junction():
                raise ValueError("Linked notice entry")
            if path.is_file() and license_name(path.name):
                _, key = observe(base, scope, path.relative_to(base).as_posix(), notice=True)
                result.append(key)
        return result

    _, own = observe(candidate, "candidate", "LICENSE", notice=True)
    own_package = json.loads(read(candidate, "package.json"))
    component(
        "project",
        own_package["name"],
        own_package["version"],
        own_package.get("license"),
        "application",
        [own],
    )
    _, python_license = observe(candidate, "candidate", "runtime/python/LICENSE.txt", notice=True)
    component(
        "runtime",
        "CPython",
        runtime["python_version"],
        "SEE_LICENSE_EVIDENCE",
        "bundled-runtime",
        [python_license],
    )
    electron_notices = []
    for name in ("LICENSE", "LICENSES.chromium.html"):
        _, key = observe(candidate, "candidate", "runtime/electron/" + name, notice=True)
        electron_notices.append(key)
    component(
        "runtime",
        "Electron/Chromium",
        pilot["electron_version"],
        "SEE_LICENSE_EVIDENCE",
        "bundled-runtime",
        electron_notices,
    )

    site = "runtime/python/Lib/site-packages"
    found = {}
    for folder in sorted((candidate / site).glob("*.dist-info")):
        metadata_name = folder.relative_to(candidate).as_posix() + "/METADATA"
        raw, key = observe(candidate, "candidate", metadata_name)
        meta = Parser().parsestr(raw.decode("utf-8"))
        name = package.runtime_tool().canonical(meta["Name"] or "")
        if (
            name in found
            or name not in runtime["dependencies"]
            or meta["Version"] != runtime["dependencies"][name]
        ):
            raise ValueError("Duplicate, unknown or changed Python metadata")
        found[name] = meta["Version"]
        folder_name = folder.relative_to(candidate).as_posix()
        notices = notice_files(candidate, "candidate", folder_name, recursive=True)
        # PEP 639 paths are relative to dist-info/licenses and must actually exist.
        for declared in meta.get_all("License-File", []):
            relative(declared)
            options = [folder_name + "/licenses/" + declared, folder_name + "/" + declared]
            chosen = next((name for name in options if (candidate / name).is_file()), None)
            if chosen is None:
                raise ValueError("Declared Python license evidence is missing")
            _, notice_key = observe(candidate, "candidate", chosen, notice=True)
            notices.append(notice_key)
        component(
            "pypi",
            name,
            meta["Version"],
            meta.get("License-Expression") or meta.get("License"),
            "bundled-core",
            set(notices),
            key,
        )
    if found != runtime["dependencies"]:
        raise ValueError("Python metadata does not cover the pinned runtime")

    native_owners = set()
    for entry in native["inputs"]:
        raw, _ = observe(source, "source", entry["path"])
        if digest(raw) != entry["sha256"]:
            raise ValueError("Native bundle source inputs changed")
        owner = npm_owner(entry["path"])
        if owner:
            native_owners.add(owner)
    renderer = None
    renderer_owners, asset_reviews = set(), []
    if pilot.get("renderer_provenance_sha256") is not None:
        renderer = package.renderer_tool().verify(candidate / "dist", source)
        value = json_input(candidate, "candidate", "dist/renderer-provenance.json", 8_388_608)
        renderer_owners = set(renderer["renderer_packages"])
        for entry in value["inputs"]:
            observe(source, "source", entry["path"], limit=MAX_NOTICE)
        for entry in value["assets"]:
            asset_reviews.append(
                {
                    **entry,
                    "npm_package": npm_owner(entry["path"]),
                    "decision": "pending_owner_review",
                }
            )
    packages = lock["packages"]
    if not (native_owners | renderer_owners).issubset(packages):
        raise ValueError("Native bundle dependency is absent from the npm lock")
    for path, entry in sorted(packages.items()):
        if (
            not path
            or (renderer is not None and path not in native_owners | renderer_owners)
            or (renderer is None and entry.get("dev", False) and path not in native_owners)
        ):
            continue
        if not path.startswith("node_modules/") or entry.get("link"):
            raise ValueError("Unsupported linked npm lock entry")
        raw, key = observe(source, "source", path + "/package.json")
        meta = json.loads(raw)
        expected_name = path.rsplit("node_modules/", 1)[-1]
        if meta.get("name") != expected_name or meta.get("version") != entry.get("version"):
            raise ValueError("Installed npm metadata differs from the lock")
        notices = notice_files(source, "source", path)
        scope = (
            "native-and-renderer-bundled"
            if path in native_owners & renderer_owners
            else "native-bundled"
            if path in native_owners
            else "renderer-bundled"
            if renderer is not None
            else "renderer-conservative-superset"
        )
        component("npm", meta["name"], meta["version"], meta.get("license"), scope, notices, key)

    missing = [
        {key: c[key] for key in ("ecosystem", "name", "version", "metadata")}
        for c in components
        if not c["notices"]
    ]
    gaps = [
        "Renderer main/worker module and output graphs are recorded; dynamic runtime downloads, generated/vendor internals and build-environment reproducibility are not established."
        if renderer is not None
        else "Renderer dependency coverage is a conservative npm-lock superset, not an exact build module graph.",
        "Public/assets, vendored code, fonts, WASM, native subcomponents and model redistribution need explicit ownership review.",
        "Locally observed runtime versions are retained; supported/security-update baselines are not established by this offline audit.",
        "Notice collection and declared license metadata do not establish redistribution clearance.",
        "Publisher identity, certificate ownership, timestamping and independently verified signatures are not configured.",
        "Clean-machine install/uninstall/update/interruption and hardware acceptance remain pending.",
    ]
    report = {
        "format": 1,
        "kind": "inara-distribution-audit",
        "collector_sha256": digest(Path(__file__).read_bytes()),
        "candidate_manifest_sha256": digest(read(candidate, "desktop-pilot.json", 4_194_304)),
        "candidate_inventory_sha256": digest(canonical(pilot["files"]).encode()),
        "candidate_files": len(pilot["files"]),
        "integrity": "passed",
        "publisher_authenticated": False,
        "release_ready": False,
        "license_clearance": False,
        "network_accessed": False,
        "private_profile_read": False,
        "components": sorted(
            components, key=lambda c: (c["ecosystem"], c["name"], c["metadata"] or "")
        ),
        "inputs": sorted(inputs.values(), key=lambda x: (x["scope"], x["path"])),
        "license_evidence": sorted(evidence.values(), key=lambda x: (x["scope"], x["path"])),
        "missing_notice_components": sorted(missing, key=canonical),
        "review_gaps": gaps,
        "renderer_provenance": renderer,
        "asset_reviews": asset_reviews,
    }
    return report, blobs


def artifacts(report, blobs):
    lines, total = [], 0

    def append(*values):
        nonlocal total
        for value in values:
            total += len(value.encode("utf-8")) + 1
            if total > MAX_EVIDENCE:
                raise ValueError("Combined notices exceed their output bound")
            lines.append(value)

    append(
        "INARA THIRD-PARTY NOTICE EVIDENCE",
        "Collected verbatim from the bound candidate/local inputs; review pending.",
        "This inventory is not redistribution clearance or publisher authentication.",
        "",
    )
    evidence = {x["scope"] + ":" + x["path"]: x for x in report["license_evidence"]}
    for component in report["components"]:
        append(
            f"=== {component['ecosystem']} / {component['name']} / {component['version']} ===",
            f"Scope: {component['scope']}",
            f"Declared license: {component['declared_license']}",
        )
        if not component["notices"]:
            append("NOTICE EVIDENCE MISSING - REVIEW REQUIRED")
        for key in component["notices"]:
            entry = evidence[key]
            if total + len(blobs[entry["copy"]]) > MAX_EVIDENCE:
                raise ValueError("Combined notices exceed their output bound")
            append(
                "--- " + key + " / SHA-256 " + entry["sha256"],
                blobs[entry["copy"]].decode("utf-8-sig"),
            )
        append("")
    return {
        **blobs,
        "distribution-audit.json": (json.dumps(report, indent=2) + "\n").encode(),
        "THIRD_PARTY_NOTICES.txt": "\n".join(lines).encode("utf-8"),
    }


def output_path(output, candidate, source):
    output = Path(output).absolute()
    if output.drive.startswith("\\\\") or output.resolve() != output:
        raise ValueError("Choose an unlinked local audit output")
    if any(
        output == base or output.is_relative_to(base) or base.is_relative_to(output)
        for base in [candidate]
    ):
        raise ValueError("Keep audit output outside the immutable candidate")
    if output == source or source.is_relative_to(output):
        raise ValueError("Do not replace the source tree")
    return output


def create(candidate, output, source=ROOT):
    candidate, source = local(candidate), local(source)
    output = output_path(output, candidate, source)
    if output.exists():
        raise ValueError("Choose a NEW audit output; existing evidence is never overwritten")
    report, blobs = collect(candidate, source)
    files = artifacts(report, blobs)
    output.mkdir(parents=True)
    for name, raw in files.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(raw)
    return summary(report)


def verify(candidate, output, source=ROOT):
    candidate, source, output = local(candidate), local(source), local(output)
    output_path(output, candidate, source)
    report, blobs = collect(candidate, source)
    expected = artifacts(report, blobs)
    actual = {p.relative_to(output).as_posix() for p in package.files_in(output)}
    if actual != set(expected):
        raise ValueError("Missing or unexpected audit evidence")
    for name, raw in expected.items():
        if read(output, name, 67_108_864) != raw:
            raise ValueError("Audit differs from its candidate/source evidence")
    return summary(report)


def summary(report):
    return {
        "integrity": "passed",
        "candidate_manifest_sha256": report["candidate_manifest_sha256"],
        "components": len(report["components"]),
        "notice_files": len(report["license_evidence"]),
        "missing_notice_components": report["missing_notice_components"],
        "release_ready": False,
        "publisher_authenticated": False,
        "license_clearance": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("collect", "verify"))
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = (create if args.command == "collect" else verify)(args.candidate, args.output)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        parser.exit(
            1,
            "Distribution audit refused. Preserve the candidate and existing evidence; review local inputs.\n",
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
