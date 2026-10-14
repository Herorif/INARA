"""Verification fixture, never a production backend or generated artwork."""

import hashlib
import json
from pathlib import Path
import struct
import sys
import time
import zlib


def main():
    data = json.loads(sys.stdin.buffer.read(32769))
    folder, recipe = Path(data["staging"]), data["recipe"]
    if recipe["prompt"] == "WAIT FOR CANCELLATION":
        (folder / "progress.json").write_text('{"phase":"generating"}')
        time.sleep(20)
    width, height = recipe["width"], recipe["height"]

    def chunk(kind, raw):
        return struct.pack(">I", len(raw)) + kind + raw + struct.pack(">I", zlib.crc32(kind + raw))

    rows = b"".join(
        b"\x00"
        + b"".join(
            bytes((26, 95, 112) if (x // 32 + y // 32) % 2 else (175, 217, 227))
            for x in range(width)
        )
        for y in range(height)
    )
    raw = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )
    stats = {
        "width": width,
        "height": height,
        "seed": recipe["seed"],
        "backend": "verification_fixture",
        "model": "VERIFICATION FIXTURE - NO MODEL RAN",
        "device": "fixture",
    }
    (folder / "model.png").write_bytes(raw)
    (folder / "model.json").write_text(json.dumps({"recipe": recipe, "provenance": stats}))
    artifacts = {}
    for extension in ["png", "json"]:
        raw = (folder / f"model.{extension}").read_bytes()
        artifacts[extension] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    (folder / "result.json").write_text(json.dumps({"stats": stats, "artifacts": artifacts}))


if __name__ == "__main__":
    main()
