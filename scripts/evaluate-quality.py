"""Run offline product-contract evaluations in a disposable isolated profile."""

import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from services.quality import run_offline_suite  # noqa: E402

if __name__ == "__main__":
    result = asyncio.run(run_offline_suite())
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["passed"] else 1)
