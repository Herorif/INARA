"""Verify observed renderer build provenance without running renderer or dependency code."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

NAME = "renderer-provenance.json"


def sha(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1_048_576), b""):
            value.update(chunk)
    return value.hexdigest()


def relative(name):
    if not isinstance(name, str) or not name or len(name) > 2048:
        raise ValueError("Invalid renderer path")
    value = PurePosixPath(name)
    if (
        value.is_absolute()
        or value.as_posix() != name
        or ".." in value.parts
        or "\\" in name
        or ":" in name
        or any(ord(c) < 32 for c in name)
    ):
        raise ValueError("Unsafe renderer path")
    return value


def plain(path, directory=False):
    path = Path(path).absolute()
    if (
        path.drive.startswith("\\\\")
        or path.resolve() != path
        or not (path.is_dir() if directory else path.is_file())
    ):
        raise ValueError("Missing or linked renderer entry")
    if not directory and path.stat().st_nlink != 1:
        raise ValueError("Shared renderer evidence")
    return path


def records(items):
    if not isinstance(items, list) or not 1 <= len(items) <= 20000:
        raise ValueError("Missing or excessive renderer inventory")
    result, folded = {}, set()
    for entry in items:
        name = relative(entry["path"]).as_posix()
        if (
            name.casefold() in folded
            or type(entry["bytes"]) is not int
            or not 0 <= entry["bytes"] <= 536_870_912
            or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
        ):
            raise ValueError("Duplicate or invalid renderer record")
        folded.add(name.casefold())
        result[name] = entry
    return result


def check(base, record):
    path = plain(base.joinpath(*relative(record["path"]).parts))
    if path.stat().st_size != record["bytes"] or sha(path) != record["sha256"]:
        raise ValueError("Renderer input/output changed")


def npm_owner(name):
    parts = relative(name).parts
    indices = [i for i, part in enumerate(parts) if part == "node_modules"]
    if not indices:
        return None
    index = indices[-1] + 1
    length = 2 if index < len(parts) and parts[index].startswith("@") else 1
    if len(parts) <= index + length:
        raise ValueError("Incomplete npm module path")
    return "/".join(parts[: index + length])


def verify(directory, source=None):
    directory = plain(directory, directory=True)
    manifest = plain(directory / NAME)
    if manifest.stat().st_size > 8_388_608:
        raise ValueError("Excessive renderer manifest")
    value = json.loads(manifest.read_text(encoding="utf-8"))
    if (
        value.get("format") != 1
        or value.get("kind") != "inara-renderer-build"
        or value.get("coverage") != "observed-rollup-graph"
        or value.get("redistribution_cleared") is not False
        or value.get("reproducible_build_claimed") is not False
    ):
        raise ValueError("Unsupported renderer provenance")
    inputs, outputs = records(value["inputs"]), records(value["outputs"])
    if NAME in outputs or "index.html" not in outputs:
        raise ValueError("Missing entry or recursive output manifest")
    actual = set()
    for path in directory.rglob("*"):
        plain(path, directory=path.is_dir())
        if path.is_file():
            actual.add(path.relative_to(directory).as_posix())
    if actual != set(outputs) | {NAME}:
        raise ValueError("Renderer output inventory differs")
    for entry in outputs.values():
        check(directory, entry)
    required_inputs = {
        "index.html",
        "package-lock.json",
        "package.json",
        "vite.config.js",
        "scripts/renderer-provenance.cjs",
        "docs/ASSET_OWNERSHIP.json",
    }
    if not required_inputs.issubset(inputs):
        raise ValueError("Missing renderer build/ownership inputs")
    if not isinstance(value["graph"], list) or not 1 <= len(value["graph"]) <= 20000:
        raise ValueError("Missing renderer module graph")
    graph = {}
    for module in value["graph"]:
        identity = module["id"]
        if (
            not isinstance(identity, str)
            or identity in graph
            or len(identity) > 4096
            or type(module["external"]) is not bool
        ):
            raise ValueError("Duplicate or invalid renderer module")
        target, separator, local_id = identity.partition("|")
        if (
            not separator
            or target != module["target"]
            or not re.fullmatch(r"main|worker-[1-9][0-9]*", target)
        ):
            raise ValueError("Invalid renderer graph target")
        if module["path"] is None:
            if not re.fullmatch(r"virtual:[0-9a-f]{64}", local_id):
                raise ValueError("Invalid virtual renderer identity")
        elif module["path"] not in inputs or local_id.split("?", 1)[0] != module["path"]:
            raise ValueError("Module lacks physical input provenance")
        graph[identity] = module
    for module in graph.values():
        if (
            not isinstance(module["imports"], list)
            or len(module["imports"]) > 20000
            or not set(module["imports"]).issubset(graph)
            or any(graph[key]["target"] != module["target"] for key in module["imports"])
        ):
            raise ValueError("Renderer module graph is not closed")
    chunks, owners = set(), set()
    for chunk in value["chunks"]:
        name = relative(chunk["path"]).as_posix()
        if (
            name in chunks
            or name not in outputs
            or not isinstance(chunk["modules"], list)
            or not set(chunk["modules"]).issubset(graph)
            or any(graph[key]["target"] != chunk["target"] for key in chunk["modules"])
        ):
            raise ValueError("Invalid chunk module provenance")
        chunks.add(name)
        for identity in chunk["modules"]:
            module = graph[identity]
            owner = npm_owner(module["path"]) if module["path"] else None
            if owner:
                owners.add(owner)
    if not chunks:
        raise ValueError("No renderer chunks recorded")
    copied = set()
    for entry in value["public_copies"]:
        name = relative(entry["output"]).as_posix()
        if (
            entry["input"] != "public/" + name
            or name in copied
            or entry["input"] not in inputs
            or name not in outputs
            or any(
                entry[key] != inputs[entry["input"]][key] or entry[key] != outputs[name][key]
                for key in ("bytes", "sha256")
            )
        ):
            raise ValueError("Copied public asset differs from its input/output")
        copied.add(name)
    if {"public/" + name for name in copied} != {
        name for name in inputs if name.startswith("public/")
    }:
        raise ValueError("Copied public asset inventory is incomplete")
    assets = records(value["assets"]) if value["assets"] else {}
    copied_inputs = set()
    copy_pairs = set()
    for entry in value["byte_identical_copies"]:
        if (
            entry["input"] not in inputs
            or entry["output"] not in outputs
            or any(
                entry[key] != inputs[entry["input"]][key]
                or entry[key] != outputs[entry["output"]][key]
                for key in ("bytes", "sha256")
            )
        ):
            raise ValueError("Byte-identical asset copy differs")
        copied_inputs.add(entry["input"])
        pair = (entry["input"], entry["output"])
        if pair in copy_pairs:
            raise ValueError("Duplicate byte-identical copy")
        copy_pairs.add(pair)
    expected_pairs = {(i, o) for i, source_entry in inputs.items() for o, output_entry in outputs.items() if (source_entry["bytes"], source_entry["sha256"]) == (output_entry["bytes"], output_entry["sha256"])}
    if copy_pairs != expected_pairs:
        raise ValueError("Byte-identical copy inventory is incomplete")
    expected_assets = {
        name
        for name in inputs
        if name in copied_inputs
        or re.search(
            r"\.(png|ico|svg|jpe?g|webp|wasm|task|woff2?|ttf|glb|gltf|stl|mp[34]|wav|bin)$",
            name,
            re.I,
        )
    }
    if set(assets) != expected_assets:
        raise ValueError("Asset provenance inventory is incomplete")
    for name, entry in assets.items():
        if inputs.get(name) != entry:
            raise ValueError("Asset lacks matching input provenance")
    registry = value["ownership_registry"]
    if registry.get("format") != 1 or not isinstance(registry.get("entries"), list):
        raise ValueError("Invalid asset ownership registry")
    reviewed = set()
    for entry in registry["entries"]:
        name = relative(entry["path"]).as_posix()
        if (
            name in reviewed
            or name not in assets
            or entry["sha256"] != assets[name]["sha256"]
            or entry["decision"] != "pending"
            or entry["owner"] is not None
            or entry["license_evidence"] != []
        ):
            raise ValueError("Stale, duplicate or unsupported ownership decision")
        reviewed.add(name)
    if source is not None:
        source = plain(source, directory=True)
        for entry in inputs.values():
            check(source, entry)
        original = json.loads((source / "docs/ASSET_OWNERSHIP.json").read_text(encoding="utf-8"))
        if original != registry:
            raise ValueError("Ownership snapshot differs from its hashed registry")
        # Catch added/deleted source/public/asset files, not just changed listed inputs.
        for folder in ("src", "public", "assets"):
            for path in (source / folder).rglob("*"):
                plain(path, directory=path.is_dir())
            actual_inputs = {
                p.relative_to(source).as_posix()
                for p in (source / folder).rglob("*")
                if p.is_file()
            }
            if actual_inputs != {name for name in inputs if name.startswith(folder + "/")}:
                raise ValueError("Source inventory changed after renderer build")
    # Asset-only npm sources also count; some loaders are copied as opaque JavaScript.
    for name in assets:
        owner = npm_owner(name)
        if owner:
            owners.add(owner)
    return {
        "integrity": "passed",
        "manifest_sha256": sha(manifest),
        "inputs": len(inputs),
        "modules": len(graph),
        "chunks": len(chunks),
        "outputs": len(outputs),
        "public_copies": len(copied),
        "asset_inputs": len(assets),
        "pending_asset_reviews": len(assets),
        "renderer_packages": sorted(owners),
        "worker_targets": len({m["target"] for m in graph.values()} - {"main"}),
        "source_revalidated": source is not None,
        "redistribution_cleared": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.directory, args.source)
    except (OSError, ValueError, KeyError, TypeError):
        parser.exit(
            1,
            "Renderer provenance refused. Preserve prior candidates and rebuild from reviewed inputs.\n",
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
