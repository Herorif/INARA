"""Explicitly export one encrypted migration backup on the original Windows account."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from services.storage import WindowsProtection  # noqa: E402
import json  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path)
    parser.add_argument("destination", type=Path, help="New file for the decrypted source; never overwrites")
    args = parser.parse_args()
    payload = json.loads(WindowsProtection().unprotect(args.backup.read_bytes()))
    if payload.get("context") != f"backup:{args.backup.stem}":
        parser.error("The backup context does not match this filename.")
    raw = bytes.fromhex(payload["value"]["bytes_hex"])
    # Exclusive creation prevents accidental replacement of a source or existing export.
    with args.destination.open("xb") as output:
        output.write(raw)
    print("Backup exported. This file contains private plaintext; keep it protected.")


if __name__ == "__main__":
    main()
