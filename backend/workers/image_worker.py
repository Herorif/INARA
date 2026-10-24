"""One owned local generation; no downloads, provider keys or remote service calls."""

import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from creative.image_backend import generate  # noqa: E402


def main():
    data = json.loads(sys.stdin.buffer.read(32769))
    folder, recipe = Path(data["staging"]), data["recipe"]

    def progress(phase):
        temporary = folder / "progress.tmp"
        temporary.write_text(json.dumps({"phase": phase}), encoding="utf-8")
        temporary.replace(folder / "progress.json")

    image, stats = generate(recipe, data["model_dir"], progress)
    progress("validating")
    if image.size != (recipe["width"], recipe["height"]):
        raise ValueError("Image dimensions")
    # Re-encode pixels without model/file metadata or external references.
    from PIL import Image

    clean = Image.new("RGB", image.size)
    clean.paste(image.convert("RGB"))
    progress("saving")
    clean.save(folder / "model.png", format="PNG")
    (folder / "model.json").write_text(
        json.dumps({"recipe": recipe, "provenance": stats}, indent=2), encoding="utf-8"
    )
    artifacts = {}
    for extension in ("png", "json"):
        path = folder / f"model.{extension}"
        if not 0 < path.stat().st_size <= 16_777_216:
            raise ValueError("Artifact limit")
        raw = path.read_bytes()
        artifacts[extension] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    (folder / "result.json").write_text(
        json.dumps({"stats": stats, "artifacts": artifacts}), encoding="utf-8"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(1)
