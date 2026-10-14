"""One bounded offline build. Input arrives through stdin; output stays in staging."""

import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from creative.scene import assemble  # noqa: E402


def main():
    data = json.loads(sys.stdin.buffer.read(32769))
    folder, recipe = Path(data["staging"]), data["recipe"]

    def progress(phase):
        temporary = folder / "progress.tmp"
        temporary.write_text(json.dumps({"phase": phase}), encoding="utf-8")
        temporary.replace(folder / "progress.json")

    progress("building")
    stats, mesh_stl, mesh_glb = assemble(recipe)
    progress("validating")
    progress("saving")
    formats = {
        "stl": mesh_stl,
        "glb": mesh_glb,
        "json": json.dumps(recipe, indent=2).encode(),
    }
    if recipe.get("engine") == "blender":
        import subprocess

        progress("blender")
        # Descendants remain in the atomic parent Job Object; no breakaway flags.
        for extension, payload in formats.items():
            (folder / f"model.{extension}").write_bytes(payload)
        subprocess.run(
            [
                data["blender"],
                "--background",
                "--factory-startup",
                "--disable-autoexec",
                "--threads",
                "2",
                "--python-exit-code",
                "1",
                "--python",
                str(Path(__file__).with_name("blender_scene.py")),
                "--",
                str(folder),
            ],
            check=True,
            timeout=110,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        for extension, name in (
            ("blend", "model.blend"),
            ("png", "model.png"),
            ("glb", "blender.glb"),
        ):
            path = folder / name
            if not 0 < path.stat().st_size <= 16_777_216:
                raise ValueError("Blender artifact limit")
            payload = path.read_bytes()
            signatures = {"blend": b"BLENDER", "png": b"\x89PNG\r\n\x1a\n", "glb": b"glTF"}
            if not payload.startswith(signatures[extension]):
                raise ValueError("Invalid Blender artifact")
            formats[extension] = payload
        (folder / "blender.glb").unlink()
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
