"""A fake CAD kernel worker: the cad_kernel_worker JSON-lines protocol, no build123d.

The first feature's id picks the behaviour of a build:
- "slow": start a sleeping grandchild (its pid goes to grandchild.pid), then never answer;
- "crash": exit at once without answering;
- "fail": answer a fillet that doesn't fit (feature index 1, 3 mm in a 4 mm room);
- "noise": print junk lines first, then answer normally;
- anything else: write the requested files and answer ok.
Every reply carries the worker's pid and how many builds it has run.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path


def main():
    builds = 0
    for line in sys.stdin:
        request = json.loads(line)
        ident, command = request.get("id"), request.get("cmd")
        if command == "exit":
            return 0
        if command == "ping":
            reply = {"ok": True, "version": "fake-1"}
        else:
            builds += 1
            features = request["tree"]["features"]
            behaviour = features[0].get("id")
            if behaviour == "slow":
                child = subprocess.Popen(
                    [sys.executable, "-c", "import time; time.sleep(120)"],
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                Path("grandchild.pid").write_text(str(child.pid), encoding="utf-8")
                time.sleep(120)
            if behaviour == "crash":
                os._exit(7)
            if behaviour == "fail":
                reply = {"ok": False, "code": "kernel_failed", "message": "the fillet doesn't fit",
                         "feature": features[1].get("id"), "index": 1,
                         "detail": {"op": "fillet", "size": 3, "edges": "all", "room": 4}}
            else:
                if behaviour == "noise":
                    sys.stdout.write("Warning from OpenCascade\n{not json\n[1, 2]\n")
                    sys.stdout.write(json.dumps({"id": -5, "ok": True}) + "\n")
                folder = Path(request["folder"])
                folder.mkdir(exist_ok=True)
                files = {}
                for name in request["export"]:
                    path = folder / f"model.{name}"
                    path.write_bytes(b"glTF" if name == "glb" else b"solid")
                    files[name] = str(path.resolve())
                reply = {"ok": True, "facts": {"volume": 1.0, "bbox": [1, 1, 1], "faces": 6,
                                               "edges": 12, "valid": True},
                         "files": files, "warnings": [], "seconds": 0.01,
                         "quality": request["quality"]}
        reply.update(id=ident, pid=os.getpid(), builds=builds)
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
