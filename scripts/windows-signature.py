"""Read-only, cache-only Windows Authenticode checks with external leaf-certificate pins."""

import argparse
import ctypes as c
from ctypes import wintypes as w
import importlib.util
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "signature_package", ROOT / "scripts/signed-package.py"
)
signed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signed)


class Guid(c.Structure):
    _fields_ = [("a", w.DWORD), ("b", w.WORD), ("d", w.WORD), ("e", c.c_ubyte * 8)]


class FileInfo(c.Structure):
    _fields_ = [
        ("size", w.DWORD),
        ("path", w.LPCWSTR),
        ("handle", w.HANDLE),
        ("subject", c.c_void_p),
    ]


class TrustData(c.Structure):
    _fields_ = [
        ("size", w.DWORD),
        ("callback", c.c_void_p),
        ("sip", c.c_void_p),
        ("ui", w.DWORD),
        ("revocation", w.DWORD),
        ("choice", w.DWORD),
        ("file", c.POINTER(FileInfo)),
        ("action", w.DWORD),
        ("state", w.HANDLE),
        ("url", w.LPCWSTR),
        ("flags", w.DWORD),
        ("context", w.DWORD),
        ("settings", c.c_void_p),
    ]


class Certificate(c.Structure):
    _fields_ = [
        ("encoding", w.DWORD),
        ("encoded", c.c_void_p),
        ("bytes", w.DWORD),
        ("info", c.c_void_p),
        ("store", w.HANDLE),
    ]


class ProviderCertificate(c.Structure):
    # Only the prefix of the FIRST chain entry is accessed; never pointer-arithmetic
    # over this deliberately partial structure.
    _fields_ = [("size", w.DWORD), ("certificate", c.POINTER(Certificate))]


class Signer(c.Structure):
    _fields_ = [
        ("size", w.DWORD),
        ("as_of", w.FILETIME),
        ("certificates", w.DWORD),
        ("chain", c.POINTER(ProviderCertificate)),
        ("type", w.DWORD),
        ("info", c.c_void_p),
        ("error", w.DWORD),
        ("counters", w.DWORD),
        ("counter_array", c.c_void_p),
        ("chain_context", c.c_void_p),
    ]


def leaf(pointer):
    if not pointer:
        raise ValueError("Windows did not expose the verified signer")
    signer = pointer.contents
    if (
        signer.size < c.sizeof(Signer)
        or signer.error
        or not signer.certificates
        or not signer.chain
    ):
        raise ValueError("Windows signer chain is unavailable or invalid")
    context = signer.chain[0].certificate
    if not context or not context.contents.encoded or not 1 <= context.contents.bytes <= 1_048_576:
        raise ValueError("Missing or excessive native signer certificate")
    return signed.trust.sha(c.string_at(context.contents.encoded, context.contents.bytes))


def native_probe(path):
    if sys.platform != "win32":
        raise ValueError("Windows signature verification requires Windows")
    # LOAD_LIBRARY_SEARCH_SYSTEM32: do not search the package or current directory.
    library = c.WinDLL("wintrust.dll", winmode=0x800)
    verify = library.WinVerifyTrust
    verify.argtypes = [w.HWND, c.POINTER(Guid), c.POINTER(TrustData)]
    verify.restype = w.LONG
    provider = library.WTHelperProvDataFromStateData
    provider.argtypes, provider.restype = [w.HANDLE], c.c_void_p
    get_signer = library.WTHelperGetProvSignerFromChain
    get_signer.argtypes = [c.c_void_p, w.DWORD, w.BOOL, w.DWORD]
    get_signer.restype = c.POINTER(Signer)
    action = Guid.from_buffer_copy(uuid.UUID("00aac56b-cd44-11d0-8cc2-00c04fc295ee").bytes_le)
    file = FileInfo(c.sizeof(FileInfo), str(path), None, None)
    # UI_NONE, WHOLECHAIN, FILE, VERIFY; cache-only revocation excluding root,
    # MD2/MD4 disabled. No network retry and no certificate-store writes by us.
    data = TrustData(
        c.sizeof(TrustData),
        None,
        None,
        2,
        1,
        1,
        c.pointer(file),
        1,
        None,
        None,
        0x1000 | 0x80 | 0x2000,
        0,
        None,
    )
    result = {"status": None, "signer_sha256": None, "timestamp_sha256": None, "cache_only": True}
    try:
        status = verify(None, c.byref(action), c.byref(data)) & 0xFFFFFFFF
        result["status"] = f"0x{status:08x}"
        if status == 0:
            state = provider(data.state)
            if not state:
                raise ValueError("Windows verification state is unavailable")
            signer = get_signer(state, 0, False, 0)
            result["signer_sha256"] = leaf(signer)
            if signer.contents.counters:
                result["timestamp_sha256"] = leaf(get_signer(state, 0, True, 0))
        return result
    finally:
        data.action = 2  # CLOSE, even on failed VERIFY/extraction.
        verify(None, c.byref(action), c.byref(data))


def probe(path):
    path = signed.plain(path)
    before = signed.digest_file(path)
    result = native_probe(path)
    if signed.digest_file(path) != before:
        raise ValueError("Signature input changed during verification")
    return {**result, "file_sha256": before, "release_authorized": False}


def policy(path, pin):
    value, raw = signed.read(path, 262_144)
    signed.trust.digest(pin)
    if signed.trust.sha(raw) != pin:
        raise ValueError("Windows signer policy pin differs")
    signed.review.exact(value, {"format", "kind", "mode", "targets"})
    if (
        type(value["format"]) is not int
        or value["format"] != 1
        or value["kind"] != "inara-windows-signing-policy"
        or value["mode"] not in {"disabled", "production"}
        or not isinstance(value["targets"], list)
        or len(value["targets"]) > 4096
    ):
        raise ValueError("Unsupported Windows signer policy")
    seen = set()
    for entry in value["targets"]:
        signed.review.exact(entry, {"path", "signer_sha256", "timestamp_sha256"})
        name = signed.audit.relative(entry["path"]).as_posix()
        if name.casefold() in seen or Path(name).suffix.lower() not in {".exe", ".dll", ".pyd"}:
            raise ValueError("Duplicate or non-native Windows target")
        seen.add(name.casefold())
        signed.trust.digest(entry["signer_sha256"])
        signed.trust.digest(entry["timestamp_sha256"])
    if (value["mode"] == "disabled") != (not value["targets"]):
        raise ValueError("Disabled policy must have no certificate enrollment")
    return value


def check(directory, policy_path, pin, *, _probe=None):
    directory = signed.plain(directory, True)
    policy_path = signed.trust.outside(policy_path, [directory])
    value = policy(policy_path, pin)
    if value["mode"] != "production":
        raise ValueError("Owned Windows signer identity is not configured")
    targets = {entry["path"]: entry for entry in value["targets"]}
    actual = {
        p.relative_to(directory).as_posix()
        for p in signed.audit.package.files_in(directory)
        if p.suffix.lower() in {".exe", ".dll", ".pyd"}
    }
    if actual != set(targets):
        raise ValueError("Windows policy must cover the exact native file set")
    for name, entry in targets.items():
        result = (probe if _probe is None else _probe)(signed.plain(directory / name))
        if (
            result["status"] != "0x00000000"
            or result["cache_only"] is not True
            or result["signer_sha256"] != entry["signer_sha256"]
            or result["timestamp_sha256"] != entry["timestamp_sha256"]
        ):
            raise ValueError("Windows trust, enrolled signer or timestamp check failed")
    return {
        "authenticode_verified": True,
        "native_files": len(targets),
        "cache_only": True,
        "release_authorized": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("probe", "check"))
    parser.add_argument("--file", type=Path)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--expected-policy")
    args = parser.parse_args()
    if (args.command == "probe" and args.file is None) or (
        args.command == "check" and None in (args.directory, args.policy, args.expected_policy)
    ):
        parser.error("Supply the explicit file or directory and external policy/pin")
    try:
        result = (
            probe(args.file)
            if args.command == "probe"
            else check(args.directory, args.policy, args.expected_policy)
        )
    except (OSError, ValueError, KeyError, TypeError):
        parser.exit(
            1, "Windows signature check refused; preserve inputs and inspect external trust.\n"
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
