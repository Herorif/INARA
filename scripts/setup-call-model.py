"""Explicit pinned local model setup. No service, startup entry or device access."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    pins = json.loads((ROOT / "config/local-call-model.json").read_text())
    base = ROOT / ".tools/call-model"
    base.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location("local_setup", ROOT / "scripts/setup-local-tools.py")
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    for kind in ("runtime", "model"):
        item = pins[kind]
        target = base / item["name"]
        if not target.exists():
            partial = target.with_suffix(target.suffix + ".part")
            total, digest = 0, hashlib.sha256()
            chunks = base / (item["sha256"][:12] + "-chunks")
            chunks.mkdir(exist_ok=True)
            size = 16_777_216

            def chunk(start):
                end = min(start + size, item["bytes"]) - 1
                destination = chunks / str(start)
                if not destination.exists():
                    request = urllib.request.Request(item["url"] + f"?download=true&inara_part={start}",
                                                     headers={"Range": f"bytes={start}-{end}"})
                    with urllib.request.urlopen(request, timeout=120) as response:
                        if response.status != 206 or response.headers.get("Content-Range") != f"bytes {start}-{end}/{item['bytes']}":
                            raise ValueError("Unexpected range response")
                        data = response.read(end - start + 2)
                    if len(data) != end - start + 1:
                        raise ValueError("Incomplete range")
                    with destination.open("xb") as output:
                        output.write(data)
                if destination.stat().st_size != end - start + 1:
                    raise ValueError("Existing chunk differs; preserve it")
                return destination

            if kind == "model":
                with ThreadPoolExecutor(max_workers=6) as pool:
                    parts = list(pool.map(chunk, range(0, item["bytes"], size)))
                with partial.open("xb") as output:
                    for part in parts:
                        with part.open("rb") as source:
                            while block := source.read(4_194_304):
                                output.write(block)
                                digest.update(block)
                                total += len(block)
            else:
                with urllib.request.urlopen(item["url"], timeout=120) as source, partial.open("xb") as output:
                    while block := source.read(4_194_304):
                        total += len(block)
                        if total > item["bytes"]:
                            raise ValueError("Download exceeds pinned size")
                        output.write(block)
                        digest.update(block)
            if total != item["bytes"] or digest.hexdigest() != item["sha256"]:
                raise ValueError("Download differs from upstream pin; preserve partial for inspection")
            partial.rename(target)
        if target.stat().st_size != item["bytes"] or setup.sha(target) != item["sha256"]:
            raise ValueError("Existing model/runtime differs from pin")
        # The verified full model supersedes only its own numbered transfer chunks.
        chunks = base / (item["sha256"][:12] + "-chunks")
        if chunks.exists():
            if chunks.resolve() != chunks.absolute() or chunks.parent.resolve() != base.resolve():
                raise ValueError("Linked transfer cache")
            for part in chunks.iterdir():
                if not part.name.isdecimal() or not part.is_file() or part.resolve() != part.absolute():
                    raise ValueError("Unexpected transfer-cache content; preserve it")
            for part in chunks.iterdir():
                part.unlink()
            chunks.rmdir()
    setup.extract(base / pins["runtime"]["name"], base / "runtime")
    inventory = {p.relative_to(base).as_posix(): setup.sha(p) for p in (base / "runtime").rglob("*") if p.is_file()}
    (base / "installation.json").write_text(json.dumps({"format": 1, "pins": pins, "runtime_files": inventory}, indent=2) + "\n")
    print(json.dumps({"installed": True, "model": pins["model"]["id"], "service_installed": False, "device_accessed": False}))


if __name__ == "__main__":
    main()
