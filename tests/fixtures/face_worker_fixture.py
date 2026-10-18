"""Fixed process fixture: no model, image inference, camera or provider work."""
import json
from pathlib import Path
import sys
import time

data = json.load(sys.stdin)
root = Path(data["output"])
temporary = root / "state.tmp"
temporary.write_text(json.dumps({"authenticated": True, "fixture": "no physical camera"}))
temporary.replace(root / "state.json")
time.sleep(10)  # The owner must stop this process after consuming the result.
