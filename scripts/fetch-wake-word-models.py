"""Fetch the pinned "Hey Jarvis" wake-word models into the JARVIS model folder.

The three openWakeWord v0.5.1 files listed in ``backend/services/wake_word.py``
(``MANIFEST``) are downloaded over HTTPS, verified against the Windows certificate
store through truststore (antivirus HTTPS scanning re-signs traffic with a root only
Windows trusts). Each file is written to a temporary file in the model folder, checked
by size and SHA-256, and only then renamed into place; on a mismatch the temporary file
is deleted and the script fails. Files already present and correct are left alone.

The folder is JARVIS_WAKE_WORD_DIR, else %LOCALAPPDATA%\\JARVIS\\models\\wake-word
(``--dir`` overrides both). ``--check`` only verifies the files already there.

The models are CC BY-NC-SA 4.0: personal, non-commercial use only. They are never
committed or packaged with JARVIS.

    .\\.venv\\Scripts\\python.exe scripts\\fetch-wake-word-models.py
    .\\.venv\\Scripts\\python.exe scripts\\fetch-wake-word-models.py --check
"""

import argparse
import hashlib
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services import wake_word  # noqa: E402  (stdlib-only module; needs backend on the path)

BLOCK = 1 << 16
TIMEOUT = 60


class FetchError(Exception):
    pass


def default_opener():
    """A urllib opener verifying HTTPS against the Windows certificate store."""
    import ssl
    import urllib.request

    import truststore

    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))


def verify(path, item):
    """True when ``path`` has the pinned size and SHA-256."""
    try:
        if path.stat().st_size != item.bytes:
            return False
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(BLOCK), b""):
                digest.update(block)
    except OSError:
        return False
    return digest.hexdigest() == item.sha256


def fetch_one(opener, item, folder):
    """Download ``item`` to a temporary file, check it, then rename it into place."""
    if not item.url.startswith("https://"):
        raise FetchError(f"{item.file}: refusing a non-HTTPS source.")
    handle, temporary = tempfile.mkstemp(prefix=f".{item.file}.", suffix=".part", dir=folder)
    temporary = Path(temporary)
    try:
        digest, size = hashlib.sha256(), 0
        with os.fdopen(handle, "wb") as output, opener.open(item.url, timeout=TIMEOUT) as response:
            while True:
                block = response.read(BLOCK)
                if not block:
                    break
                size += len(block)
                if size > item.bytes:
                    raise FetchError(f"{item.file}: larger than the pinned {item.bytes} bytes.")
                digest.update(block)
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
        if size != item.bytes:
            raise FetchError(f"{item.file}: {size} bytes, expected {item.bytes}.")
        if digest.hexdigest() != item.sha256:
            raise FetchError(f"{item.file}: SHA-256 does not match the pinned value.")
        os.replace(temporary, folder / item.file)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def run(folder, manifest=wake_word.MANIFEST, opener=None, check_only=False, out=print):
    """0 when every file is present and verified, 1 otherwise."""
    folder = Path(folder)
    out(wake_word.MODEL_LICENCE)
    out(f"Model folder: {folder}")
    if check_only:
        bad = [item.file for item in manifest if not verify(folder / item.file, item)]
        for item in manifest:
            out(f"  {item.file}: {'missing or changed' if item.file in bad else 'ok'}")
        return 1 if bad else 0
    folder.mkdir(parents=True, exist_ok=True)
    failed = False
    for item in manifest:
        if verify(folder / item.file, item):
            out(f"  {item.file}: already present and verified")
            continue
        if opener is None:
            opener = default_opener()
        try:
            fetch_one(opener, item, folder)
        except (FetchError, OSError) as exc:
            failed = True
            out(f"  {item.file}: FAILED ({exc})")
            continue
        out(f"  {item.file}: fetched and verified ({item.bytes} bytes)")
    return 1 if failed else 0


def main(argv=None, opener=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="only verify the files already there")
    parser.add_argument("--dir", type=Path, help="model folder (default: JARVIS_WAKE_WORD_DIR, "
                                                 "else %%LOCALAPPDATA%%\\JARVIS\\models\\wake-word)")
    args = parser.parse_args(argv)
    try:
        folder = args.dir if args.dir is not None else wake_word.model_directory()
    except wake_word.WakeWordError as exc:
        print(exc, file=sys.stderr)
        return 2
    return run(folder, opener=opener, check_only=args.check)


if __name__ == "__main__":
    sys.exit(main())
