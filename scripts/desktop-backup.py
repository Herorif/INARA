"""Bounded original-Windows-account encrypted profile recovery; never activates data."""

import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import struct
import sys
import uuid
import zipfile

sys.dont_write_bytecode = True
from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("backup_install", ROOT / "scripts/desktop-install.py")
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)
MAGIC = b"INARA-PROFILE-1\x00"
MAX_TOTAL = 64 * 1024 * 1024
MAX_FILE = 32 * 1024 * 1024
MAX_ARCHIVE = 72 * 1024 * 1024
MAX_FILES = 4096
RECEIPT = ".inara-recovery.json"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def loads(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError("Nonfinite JSON value")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def path_name(name):
    if not isinstance(name, str) or not name or len(name) > 512:
        raise ValueError("Invalid recovery path")
    path = PurePosixPath(name)
    if not path.parts or path.is_absolute() or path.as_posix() != name:
        raise ValueError("Noncanonical recovery path")
    for part in path.parts:
        if (
            part in {".", ".."}
            or part.endswith((".", " "))
            or any(char in part for char in '\\:<>"|?*')
            or any(ord(char) < 32 for char in part)
            or re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9???]|LPT[1-9???]", part.split(".")[0], re.I)
        ):
            raise ValueError("Unsafe Windows recovery path")
    if path.parts[0].casefold() == RECEIPT:
        raise ValueError("Reserved recovery path")
    return path


def bounded_read(path, limit):
    with install.plain(path).open("rb") as stream:
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise ValueError("Recovery input exceeds its size limit")
    return value


def inventory(root, recovery=False):
    install.plain(root, True)
    files, directories = {}, []
    for folder, dirs, names in os.walk(root, followlinks=False):
        for name in dirs + names:
            path = install.plain(Path(folder) / name)
            relative_name = path.relative_to(root).as_posix()
            if recovery and relative_name == RECEIPT:
                continue
            relative = path_name(relative_name).as_posix()
            if path.is_dir():
                directories.append(relative)
            elif path.is_file() and path.stat().st_nlink == 1:
                if path.stat().st_size > MAX_FILE:
                    raise ValueError("Profile file exceeds recovery limit")
                files[relative] = path
            else:
                raise ValueError("Linked or unsupported profile entry")
            if len(files) + len(directories) > MAX_FILES:
                raise ValueError("Profile inventory exceeds recovery limit")
    if sum(path.stat().st_size for path in files.values()) > MAX_TOTAL:
        raise ValueError("Profile exceeds recovery size limit")
    return files, sorted(directories)


def schema(files, manifest):
    marker = loads(files[".inara-data.json"])
    if marker != {"format": 1, "installation": manifest["installation"], "slot": manifest["slot"]}:
        raise ValueError("Backup profile ownership does not match")
    identity = loads(files["desktop-profile/resident-identity.json"])
    owner = str(uuid.UUID(identity["id"]))
    if owner != manifest["owner"] or type(identity.get("gaming", False)) is not bool:
        raise ValueError("Backup resident owner does not match")
    if "settings.json" in files and not isinstance(loads(files["settings.json"]), dict):
        raise ValueError("Invalid profile settings")
    for name in files:
        if name in {
            "database/assistant.sqlite3" + suffix for suffix in ("-wal", "-shm", "-journal")
        }:
            raise ValueError("Stop the resident and close database writers before backup")
    with sqlite3.connect(":memory:") as db:
        raw = files["database/assistant.sqlite3"]
        if (
            len(raw) < 100
            or not raw.startswith(b"SQLite format 3\x00")
            or raw[18:20] not in (b"\x01\x01", b"\x02\x02")
        ):
            raise ValueError("Invalid database header")
        # SQLite deserialize cannot use WAL headers. Change only the validation copy;
        # archived/restored bytes remain identical, and pending sidecars are refused.
        db.deserialize(raw[:18] + b"\x01\x01" + raw[20:])
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("PRAGMA query_only=ON")
        if db.execute("PRAGMA user_version").fetchone() != (1,) or db.execute(
            "PRAGMA quick_check"
        ).fetchall() != [("ok",)]:
            raise ValueError("Unsupported or damaged profile database")
        required = {
            "documents": {"kind", "id", "payload"},
            "sessions": {"id", "owner", "project", "payload"},
            "requests": {"session", "id", "payload"},
            "migrations": {"id", "digest"},
        }
        for table, columns in required.items():
            if {row[1] for row in db.execute(f"PRAGMA table_info({table})")} != columns:
                raise ValueError("Incompatible profile database schema")


def protection():
    spec = importlib.util.spec_from_file_location(
        "backup_storage", ROOT / "backend/services/storage.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.WindowsProtection()


def seal(raw, protector):
    key, nonce = os.urandom(32), os.urandom(12)
    wrapped = protector.protect(key)
    if not 1 <= len(wrapped) <= 16384:
        raise ValueError("Invalid Windows key envelope")
    header = MAGIC + struct.pack("<I", len(wrapped)) + wrapped + nonce
    return header + AESGCM(key).encrypt(nonce, raw, header)


def unseal(raw, protector):
    if not len(MAGIC) + 4 + 12 + 16 < len(raw) <= MAX_ARCHIVE or not raw.startswith(MAGIC):
        raise ValueError("Invalid encrypted backup")
    length = struct.unpack_from("<I", raw, len(MAGIC))[0]
    end = len(MAGIC) + 4 + length
    if not 1 <= length <= 16384 or end + 28 >= len(raw):
        raise ValueError("Invalid encrypted key envelope")
    key = protector.unprotect(raw[len(MAGIC) + 4 : end])
    if len(key) != 32:
        raise ValueError("Invalid recovered Windows key")
    return AESGCM(key).decrypt(raw[end : end + 12], raw[end + 12 :], raw[: end + 12])


def unpack(raw):
    if len(raw) > MAX_ARCHIVE:
        raise ValueError("Excessive recovery payload")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if (
            not 2 <= len(entries) <= MAX_FILES + 1
            or sum(entry.file_size for entry in entries) > MAX_TOTAL + 2 * 1024 * 1024
        ):
            raise ValueError("Excessive recovery inventory")
        names = [entry.filename for entry in entries]
        if len(set(names)) != len(names) or set(names).difference(
            {"manifest.json"} | {name for name in names if name.startswith("data/")}
        ):
            raise ValueError("Invalid recovery archive inventory")
        if any(
            entry.compress_type != zipfile.ZIP_STORED
            or entry.compress_size != entry.file_size
            or entry.flag_bits & 1
            or entry.file_size > MAX_FILE
            for entry in entries
        ):
            raise ValueError("Compressed/encrypted/oversized inner payload is not supported")
        if archive.getinfo("manifest.json").file_size > 2 * 1024 * 1024:
            raise ValueError("Excessive recovery manifest")
        manifest = loads(archive.read("manifest.json"))
        if (
            not isinstance(manifest, dict)
            or set(manifest)
            != (
                {"format", "kind", "installation", "slot", "owner", "files", "directories"}
                | ({"source_data"} if manifest.get("format") == 2 else set())
            )
            or type(manifest["format"]) is not int
            or manifest["format"] not in (1, 2)
            or (
                manifest["format"] == 2
                and (
                    not isinstance(manifest["source_data"], str)
                    or not 1 <= len(manifest["source_data"]) <= 4096
                )
            )
            or manifest["kind"] != "inara-profile-recovery"
            or not re.fullmatch(r"[a-f0-9]{32}", manifest["installation"])
            or not isinstance(manifest["files"], list)
            or not isinstance(manifest["directories"], list)
        ):
            raise ValueError("Unsupported recovery manifest")
        install.identifier(manifest["slot"])
        if str(uuid.UUID(manifest["owner"])) != manifest["owner"]:
            raise ValueError("Invalid resident owner")
        if len(manifest["files"]) + len(manifest["directories"]) > MAX_FILES:
            raise ValueError("Excessive manifest inventory")
        paths, files, total = {}, {}, 0
        for directory in manifest["directories"]:
            name = path_name(directory).as_posix()
            if name.casefold() in paths:
                raise ValueError("Duplicate recovery path")
            paths[name.casefold()] = "directory"
        for record in manifest["files"]:
            if (
                set(record) != {"path", "bytes", "sha256"}
                or type(record["bytes"]) is not int
                or not 0 <= record["bytes"] <= MAX_FILE
            ):
                raise ValueError("Invalid recovery file record")
            name = path_name(record["path"]).as_posix()
            if name.casefold() in paths:
                raise ValueError("Duplicate recovery path")
            paths[name.casefold()] = "file"
            value = archive.read("data/" + name)
            if len(value) != record["bytes"] or digest(value) != record["sha256"]:
                raise ValueError("Recovery payload integrity failed")
            files[name] = value
            total += len(value)
        if (
            len(paths) > MAX_FILES
            or total > MAX_TOTAL
            or set(names) != {"manifest.json"} | {"data/" + name for name in files}
        ):
            raise ValueError("Unexpected recovery payload")
        for name in paths:
            for parent in PurePosixPath(name).parents:
                if str(parent) != "." and paths.get(str(parent)) != "directory":
                    raise ValueError("Missing or conflicting recovery directory")
        schema(files, manifest)
        return manifest, files


class Recovery:
    def __init__(self, manager, protector=None):
        self.manager = manager
        self.protector = protector or protection()

    def source(self, state, slot):
        install.identifier(slot)
        if slot not in state["slots"]:
            raise ValueError("Backup requires a registered version")
        self.manager.check(slot)

    def backup(self, slot, output, *, expected_inventory=None):
        output = install.plain(output)
        if output.exists() or output.is_relative_to(self.manager.root):
            raise ValueError("Choose a NEW backup file outside the installation")
        install.plain(output.parent, True)
        with self.manager.locked() as state:
            self.source(state, slot)
            data = self.manager.data(state, slot)
            managed_recovery = data.parent == self.manager.root / "recovery-profiles"
            paths, directories = inventory(data, recovery=managed_recovery)
            files = {}
            total = 0
            for name, path in paths.items():
                files[name] = bounded_read(path, MAX_FILE)
                total += len(files[name])
                if total > MAX_TOTAL:
                    raise ValueError("Profile changed beyond recovery size limit")
            identity = loads(files["desktop-profile/resident-identity.json"])
            manifest = {
                "format": 2,
                "source_data": str(data.resolve()),
                "kind": "inara-profile-recovery",
                "installation": state["id"],
                "slot": slot,
                "owner": str(uuid.UUID(identity["id"])),
                "directories": directories,
                "files": [
                    {"path": name, "bytes": len(value), "sha256": digest(value)}
                    for name, value in sorted(files.items())
                ],
            }
            schema(files, manifest)
            if expected_inventory is not None and expected_inventory != {"directories": sorted(directories), "files": manifest["files"]}:
                raise ValueError("Backup source differs from the exact reviewed inventory")
            again, second_dirs = inventory(data, recovery=managed_recovery)
            if (
                directories != second_dirs
                or set(paths) != set(again)
                or any(
                    digest(bounded_read(again[name], MAX_FILE)) != digest(value)
                    for name, value in files.items()
                )
            ):
                raise ValueError(
                    "Profile changed during backup; preserve it and retry after stopping writers"
                )
            payload = io.BytesIO()
            with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest, allow_nan=False))
                for name, value in files.items():
                    archive.writestr("data/" + name, value)
            unpack(payload.getvalue())  # Refuse an archive this reader cannot recover.
            raw = seal(payload.getvalue(), self.protector)
            if len(raw) > MAX_ARCHIVE:
                raise ValueError("Encrypted recovery payload exceeds limit")
            # No plaintext archive or key is ever written to a temporary file.
            with output.open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            return {
                "backup_created": True,
                "sha256": digest(raw),
                "files": len(files),
                "bytes": sum(map(len, files.values())),
                "protection": "windows_original_account",
                "portable": False,
            }

    def validated(self, state, slot, backup):
        self.source(state, slot)
        path = install.plain(backup)
        if not path.is_file() or path.stat().st_size > MAX_ARCHIVE:
            raise ValueError("Missing or excessive encrypted backup")
        raw = bounded_read(path, MAX_ARCHIVE)
        manifest, files = unpack(unseal(raw, self.protector))
        if manifest["installation"] != state["id"] or manifest["slot"] != slot:
            raise ValueError("Backup belongs to another installation or package version")
        identity = self.manager.root / "data" / slot / "desktop-profile/resident-identity.json"
        if (
            identity.exists()
            and str(uuid.UUID(loads(bounded_read(identity, 16384))["id"])) != manifest["owner"]
        ):
            raise ValueError("Backup belongs to another resident owner")
        return digest(raw), manifest, files

    def preview(self, slot, backup):
        with self.manager.locked() as state:
            sha, manifest, files = self.validated(state, slot, backup)
            return {
                "valid": True,
                "sha256": sha,
                "files": len(files),
                "bytes": sum(map(len, files.values())),
                "database_schema": 1,
                "protection": "windows_original_account",
                "automatic_activation": False,
                "project_paths_rewritten": False,
            }

    def restore(self, slot, backup, destination, expected_sha256):
        destination = install.plain(destination)
        if (
            destination.exists()
            or destination.is_relative_to(self.manager.root)
            or self.manager.root.is_relative_to(destination)
        ):
            raise ValueError("Choose a NEW isolated recovery directory outside the installation")
        install.plain(destination.parent, True)
        with self.manager.locked() as state:
            sha, manifest, files = self.validated(state, slot, backup)
            if sha != expected_sha256:
                raise ValueError("Backup changed since preview")
            destination.mkdir()
            receipt = {
                "format": 1,
                "status": "incomplete",
                "backup_sha256": sha,
                "activated": False,
            }
            install.write(destination / RECEIPT, receipt)
            for name in manifest["directories"]:
                destination.joinpath(*path_name(name).parts).mkdir(parents=True, exist_ok=True)
            for name, value in files.items():
                target = destination.joinpath(*path_name(name).parts)
                with target.open("xb") as stream:
                    stream.write(value)
                    stream.flush()
                    os.fsync(stream.fileno())
            copied, directories = inventory(destination, recovery=True)
            if (
                set(copied) != set(files)
                or directories != sorted(manifest["directories"])
                or any(
                    digest(bounded_read(path, MAX_FILE)) != digest(files[name])
                    for name, path in copied.items()
                )
            ):
                raise ValueError("Restored payload changed; preserve the incomplete recovery")
            receipt["status"] = "complete"
            install.write(destination / RECEIPT, receipt)
            return {
                "restored": True,
                "files": len(files),
                "bytes": sum(map(len, files.values())),
                "activated": False,
                "existing_data_modified": False,
                "project_paths_rewritten": False,
            }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("backup", "preview", "restore"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--slot", required=True)
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--expected-sha256")
    args = parser.parse_args()
    if args.command == "restore" and (args.destination is None or not args.expected_sha256):
        parser.error("restore requires --destination and --expected-sha256 from preview")
    try:
        recovery = Recovery(install.Installation(args.root))
        if args.command == "backup":
            result = recovery.backup(args.slot, args.file)
        elif args.command == "preview":
            result = recovery.preview(args.slot, args.file)
        else:
            result = recovery.restore(args.slot, args.file, args.destination, args.expected_sha256)
    except Exception:
        parser.exit(
            1,
            "Encrypted recovery refused. Preserve backup and existing data; check original Windows account, stopped resident, version/ownership, limits and preview digest. No existing profile was replaced.\n",
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
