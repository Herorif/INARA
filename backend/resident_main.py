"""Supported Windows native resident entry point; workspace is optional."""

import argparse
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resident-only", action="store_true")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("The native resident currently supports Windows only.")
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    os.environ.pop("ELECTRON_RUN_AS_NODE", None)
    # Isolated packaged Python intentionally omits script/CWD/user import paths.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    if (Path(__file__).resolve().parents[1] / "desktop-pilot.json").exists():
        sys.dont_write_bytecode = True
    profile = Path(os.getenv("INARA_DESKTOP_DATA_DIR") or (Path(os.environ["APPDATA"]) / "inara"))
    from resident.host import NativeHost

    try:
        NativeHost(
            Path(__file__).resolve().parent.parent, profile, resident_only=args.resident_only
        ).run()
    except Exception:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None,
            "INARA could not start. Preserve your profile and run scripts/bootstrap.ps1 to repair setup. If resident-identity.json is damaged, recover it before retrying.",
            "INARA startup",
            0x10,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
