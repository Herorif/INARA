"""Sterile local runtime smoke check: no model, device, profile or network access."""

import argparse
import asyncio
import importlib
import importlib.metadata as metadata
import json
from pathlib import Path
import sqlite3
import ssl
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    root = Path(sys.executable).resolve().parent
    manifest = json.loads((root / "runtime-manifest.json").read_text(encoding="utf-8"))
    assert sys.flags.isolated and sys.flags.ignore_environment and sys.flags.no_site
    assert Path(sys.prefix).resolve() == root and Path(sys.base_prefix).resolve() == root
    assert all(Path(path).resolve().is_relative_to(root) for path in sys.path)
    modules = [
        "_ctypes",
        "_cffi_backend",
        "_ssl",
        "_sqlite3",
        "pydantic_core",
        "fastapi",
        "uvicorn",
        "socketio",
        "dotenv",
        "cryptography.hazmat.primitives.ciphers.aead",
    ]
    for name in modules:
        module = importlib.import_module(name)
        assert Path(module.__file__).resolve().is_relative_to(root)
    for name, version in manifest["dependencies"].items():
        distribution = metadata.distribution(name)
        assert distribution.version == version
        assert Path(distribution.locate_file("")).resolve().is_relative_to(root)
    for name in ("pip", "pytest", "numpy", "torch", "sounddevice", "inara_contamination_probe"):
        try:
            importlib.import_module(name)
        except ModuleNotFoundError:
            continue
        raise AssertionError("Development/optional/environment import escaped isolation")
    with sqlite3.connect(":memory:") as database:
        assert database.execute("select 1").fetchone() == (1,)
    ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key, nonce = b"\x00" * 32, b"\x00" * 12
    assert (
        AESGCM(key).decrypt(nonce, AESGCM(key).encrypt(nonce, b"fixture", None), None) == b"fixture"
    )

    async def check_loop():
        await asyncio.sleep(0)

    asyncio.run(check_loop())
    report = {
        "passed": True,
        "python_version": sys.version.split()[0],
        "dependencies": len(manifest["dependencies"]),
        "isolated": True,
        "external_import_paths": 0,
        "binary_imports_passed": True,
        "sqlite_tls_crypto_passed": True,
        "optional_or_development_modules_loaded": 0,
        "network_used": False,
        "device_used": False,
    }
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
