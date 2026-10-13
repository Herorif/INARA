"""One bounded offline build. Input arrives through stdin; output stays in staging."""

import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from creative.geometry import build, validate, stl, glb  # noqa: E402


def main():
    data = json.loads(sys.stdin.buffer.read(4097))
    folder, recipe = Path(data["staging"]), data["recipe"]

    def progress(phase):
        temporary = folder / "progress.tmp"
        temporary.write_text(json.dumps({"phase": phase}), encoding="utf-8")
        temporary.replace(folder / "progress.json")

    progress("building")
    vertices, faces = build(recipe)
    progress("validating")
    stats = validate(vertices, faces)
    progress("saving")
    formats = {
        "stl": stl(vertices, faces),
        "glb": glb(vertices, faces, recipe["name"]),
        "json": json.dumps(recipe, indent=2).encode(),
    }
    artifacts = {}
    for extension, payload in formats.items():
        (folder / f"model.{extension}").write_bytes(payload)
        artifacts[extension] = {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    (folder / "result.json").write_text(
        json.dumps({"stats": stats, "artifacts": artifacts}), encoding="utf-8"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(1)
