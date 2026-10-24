"""Reviewed typed project rebind and activation of encrypted recovery profiles."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "activation_backup", ROOT / "scripts/desktop-backup.py"
)
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)
install = backup.install


def storage(protector):
    spec = importlib.util.spec_from_file_location(
        "recovery_storage", ROOT / "backend/services/storage.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    database = module.Database.__new__(module.Database)
    database.protection = protector
    return database


def profile_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ValueError("Choose a UUID hex recovery profile identifier")
    return value


def rebind(files, manifest, manager, destination, protector):
    owner = manifest["owner"]
    old = Path(manifest.get("source_data", manager.root / "data" / manifest["slot"]))
    old = old.resolve()
    destination = destination.resolve()
    relative = old.relative_to(manager.root.resolve())
    if (
        old != old.absolute()
        or len(relative.parts) != 2
        or relative.parts[0] not in {"data", "recovery-profiles"}
        or (relative.parts[0] == "data" and relative.parts[1] != manifest["slot"])
        or (
            relative.parts[0] == "recovery-profiles"
            and not re.fullmatch(r"[a-f0-9]{32}", relative.parts[1])
        )
    ):
        raise ValueError("Unsupported backup workspace origin")
    old_workspace, new_workspace = old / "projects", destination / "projects"
    projects = sorted(
        {
            Path(name).parts[2]
            for name in manifest["directories"]
            if name.startswith("projects/projects/") and len(Path(name).parts) >= 3
        }
    )
    mapping = {
        str(old_workspace / "projects" / name): str(new_workspace / "projects" / name)
        for name in projects
    }
    scoped = {backup.digest(path.encode()): (path, target) for path, target in mapping.items()}
    codec = storage(protector)
    counts = {"memory": 0, "conversations": 0, "creative_jobs": 0, "workspace": 0}
    raw = files["database/assistant.sqlite3"]
    with sqlite3.connect(":memory:") as db:
        db.row_factory = sqlite3.Row
        db.deserialize(raw[:18] + b"\x01\x01" + raw[20:])
        db.execute("PRAGMA trusted_schema=OFF")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if (
            tables != {"documents", "sessions", "requests", "migrations"}
            or db.execute(
                "SELECT count(*) FROM sqlite_master WHERE type NOT IN ('table','index') OR (type='index' AND sql IS NOT NULL)"
            ).fetchone()[0]
        ):
            raise ValueError("Unsupported database objects require a reviewed adapter")
        documents = []
        for row in db.execute("SELECT kind,id,payload FROM documents"):
            kind, key = row["kind"], row["id"]
            value = codec.decode(f"{kind}:{key}", row["payload"])
            target_kind, target_key = kind, key
            if kind == "workspace":
                if (
                    key != backup.digest(str(old_workspace).encode())
                    or set(value) != {"project"}
                    or str(old_workspace / "projects" / value["project"]) not in mapping
                ):
                    raise ValueError("Workspace selection scope is incompatible")
                target_key = backup.digest(str(new_workspace).encode())
                counts["workspace"] += 1
            elif kind == "project_memory_v1":
                if (
                    set(value) != {"owner", "project", "revision", "days", "clock", "items"}
                    or value["owner"] != owner
                    or value["project"] not in mapping
                    or key != backup.digest((owner + "\n" + value["project"]).encode())
                ):
                    raise ValueError("Project memory scope is incompatible")
                uuid.UUID(value["revision"])
                if not isinstance(value["items"], dict):
                    raise ValueError("Invalid memory collection")
                value["project"] = mapping[value["project"]]
                target_key = backup.digest((owner + "\n" + value["project"]).encode())
                counts["memory"] += 1
            elif kind.startswith(("cad_jobs:", "image_jobs:")):
                namespace = kind.split(":", 1)[0] + ":"
                match = [
                    (source, target)
                    for source, target in mapping.items()
                    if kind == namespace + backup.digest((owner + ":" + source).encode())
                ]
                if len(match) != 1:
                    raise ValueError("Creative job owner/project scope is incompatible")
                source, target = match[0]
                if (
                    value.get("project") != Path(source).name
                    or value.get("request_id") != key
                    or value.get("state") not in {"succeeded", "failed", "cancelled", "interrupted"}
                    or not isinstance(value.get("recipe"), dict)
                    or value.get("reference") is not None
                ):
                    raise ValueError("Active or unsupported creative job cannot be activated")
                uuid.UUID(key)
                if value["state"] == "succeeded":
                    directory = backup.path_name(value["directory"])
                    if directory.parts[:2] != (
                        ("cad" if namespace == "cad_jobs:" else "images"),
                        "designs",
                    ):
                        raise ValueError("Unsafe creative artifact directory")
                    if not isinstance(value.get("artifacts"), dict) or not value["artifacts"]:
                        raise ValueError("Missing creative artifacts")
                    for extension, metadata in value["artifacts"].items():
                        if extension not in (
                            {"stl", "obj", "glb", "blend"} if namespace == "cad_jobs:" else {"png"}
                        ):
                            raise ValueError("Unsupported artifact format")
                        name = (
                            "projects/projects/"
                            + Path(source).name
                            + "/"
                            + str(directory)
                            + "/model."
                            + extension
                        )
                        payload = files[name]
                        if (
                            set(metadata) != {"bytes", "sha256"}
                            or metadata["bytes"] != len(payload)
                            or metadata["sha256"] != backup.digest(payload)
                        ):
                            raise ValueError("Creative artifact failed integrity")
                target_kind = namespace + backup.digest((owner + ":" + target).encode())
                counts["creative_jobs"] += 1
            else:
                raise ValueError(
                    "Unsupported persisted record type; preserve the detached recovery"
                )
            documents.append(
                (target_kind, target_key, codec.encode(f"{target_kind}:{target_key}", value))
            )
        sessions = []
        for row in db.execute("SELECT * FROM sessions"):
            if row["owner"] != backup.digest(owner.encode()) or row["project"] not in scoped:
                raise ValueError("Conversation owner/project scope is incompatible")
            messages = codec.decode(
                f"session:{row['id']}:{row['owner']}:{row['project']}", row["payload"]
            )
            if not isinstance(messages, list):
                raise ValueError("Unsupported conversation history")
            target_hash = backup.digest(scoped[row["project"]][1].encode())
            sessions.append(
                (
                    row["id"],
                    row["owner"],
                    target_hash,
                    codec.encode(f"session:{row['id']}:{row['owner']}:{target_hash}", messages),
                )
            )
            counts["conversations"] += 1
        known_sessions = {row[0] for row in sessions}
        for row in db.execute("SELECT * FROM requests"):
            if row["session"] not in known_sessions:
                raise ValueError("Orphan conversation request")
            request = codec.decode(f"request:{row['session']}:{row['id']}", row["payload"])
            if request.get("state") not in {"running", "succeeded", "failed"}:
                raise ValueError("Unsupported request ledger state")
        if db.execute("SELECT count(*) FROM migrations").fetchone()[0]:
            raise ValueError("Legacy migration markers require a separate reviewed adapter")
        db.execute("DELETE FROM documents")
        db.executemany("INSERT INTO documents VALUES(?,?,?)", documents)
        db.execute("DELETE FROM sessions")
        db.executemany("INSERT INTO sessions VALUES(?,?,?,?)", sessions)
        db.commit()
        result = dict(files)
        result["database/assistant.sqlite3"] = db.serialize()
    return result, counts, mapping


class Activation:
    def __init__(self, manager, protector=None):
        self.manager = manager
        self.recovery = backup.Recovery(manager, protector)

    def plan(self, state, slot, archive, profile):
        profile_id(profile)
        sha, manifest, files = self.recovery.validated(state, slot, archive)
        destination = install.plain(self.manager.root / "recovery-profiles" / profile)
        if destination.exists():
            raise ValueError("Recovery profile already exists; preserve it")
        mapped, counts, mapping = rebind(
            files, manifest, self.manager, destination, self.recovery.protector
        )
        review = {
            "format": 1,
            "slot": slot,
            "profile": profile,
            "backup_sha256": sha,
            "generation": state["generation"],
            "installation_format_after_activation": 2,
            "older_controls_compatible": False,
            "selection": self.manager.selections(state),
            "owner_fingerprint": backup.digest(manifest["owner"].encode()),
            "counts": counts,
            "destination": str(destination),
            "projects": mapping,
        }
        token = backup.digest(json.dumps(review, sort_keys=True).encode())
        return review, token, manifest, mapped

    def preview(self, slot, archive, profile):
        with self.manager.locked() as state:
            review, token, _, _ = self.plan(state, slot, archive, profile)
            return {**review, "review_sha256": token, "activated": False}

    def prepare(self, slot, archive, profile, expected):
        with self.manager.locked() as state:
            review, token, manifest, files = self.plan(state, slot, archive, profile)
            if token != expected:
                raise ValueError("Recovery review is stale")
            parent = install.plain(self.manager.root / "recovery-profiles")
            parent.mkdir(exist_ok=True)
            destination = parent / profile
            destination.mkdir()
            receipt = {
                "format": 1,
                "status": "incomplete",
                "installation": state["id"],
                "slot": slot,
                "profile": profile,
                "owner": manifest["owner"],
                "review_sha256": token,
                "generation": state["generation"],
                "selection_sha256": backup.digest(
                    json.dumps(self.manager.selections(state), sort_keys=True).encode()
                ),
            }
            install.write(destination / backup.RECEIPT, receipt)
            for name in manifest["directories"]:
                destination.joinpath(*backup.path_name(name).parts).mkdir(
                    parents=True, exist_ok=True
                )
            for name, value in files.items():
                with destination.joinpath(*backup.path_name(name).parts).open("xb") as stream:
                    stream.write(value)
                    stream.flush()
                    os.fsync(stream.fileno())
            copied, dirs = backup.inventory(destination, recovery=True)
            if set(copied) != set(files) or dirs != sorted(manifest["directories"]):
                raise ValueError("Prepared inventory changed")
            receipt["inventory"] = {
                name: backup.digest(backup.bounded_read(path, backup.MAX_FILE))
                for name, path in copied.items()
            }
            if any(
                receipt["inventory"][name] != backup.digest(value) for name, value in files.items()
            ):
                raise ValueError("Prepared payload changed")
            receipt["directories"] = dirs
            receipt["status"] = "prepared"
            install.write(destination / backup.RECEIPT, receipt)
            return {
                "prepared": True,
                "profile": profile,
                "review_sha256": token,
                "activated": False,
            }

    def activate(self, slot, profile, expected):
        with self.manager.locked() as state:
            self.recovery.source(state, slot)
            path = self.manager.profile_data(state, slot, profile)
            receipt = install.read(path / backup.RECEIPT)
            if receipt.get("review_sha256") != expected:
                raise ValueError("Recovery approval changed")
            if receipt.get("generation") != state["generation"] or receipt.get(
                "selection_sha256"
            ) != backup.digest(json.dumps(self.manager.selections(state), sort_keys=True).encode()):
                raise ValueError("Installation selection changed since recovery review")
            current = self.manager.selections(state)["slots"].get(slot, {}).get("current")
            current_path = (
                self.manager.root / "data" / slot
                if current is None
                else self.manager.root / "recovery-profiles" / current
            )
            identity = install.plain(current_path / "desktop-profile/resident-identity.json")
            if identity.exists() and install.read(identity).get("id") != receipt["owner"]:
                raise ValueError("Current resident owner changed since review")
            files, directories = backup.inventory(path, recovery=True)
            if directories != receipt.get("directories") or {
                name: backup.digest(backup.bounded_read(value, backup.MAX_FILE))
                for name, value in files.items()
            } != receipt.get("inventory"):
                raise ValueError("Prepared recovery changed; review it again")
            selection = self.manager.selections(state)
            previous = selection["slots"].get(slot, {"current": None})["current"]
            if previous == profile:
                raise ValueError("Recovery is already active")
            selection["slots"][slot] = {"current": profile, "previous": previous}
            state["format"], state["recovery"] = 2, selection
            self.manager.save(state)
            return {"activated": True, "profile": profile, "original_data_preserved": True}

    def rollback(self, slot):
        with self.manager.locked() as state:
            self.recovery.source(state, slot)
            selection = self.manager.selections(state)
            record = selection["slots"].get(slot)
            if record is None:
                raise ValueError("No recovery activation is available")
            previous_path = self.manager.profile_data(state, slot, record["previous"])
            current_path = self.manager.profile_data(state, slot, record["current"])
            if install.read(previous_path / "desktop-profile/resident-identity.json").get(
                "id"
            ) != install.read(current_path / "desktop-profile/resident-identity.json").get("id"):
                raise ValueError("Rollback resident owner is incompatible")
            record["current"], record["previous"] = record["previous"], record["current"]
            state["format"], state["recovery"] = 2, selection
            self.manager.save(state)
            return {"rolled_back": True, "profile": record["current"], "data_deleted": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preview", "prepare", "activate", "rollback"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--slot", required=True)
    parser.add_argument("--file", type=Path)
    parser.add_argument("--profile")
    parser.add_argument("--expected-review")
    args = parser.parse_args()
    if args.command in {"preview", "prepare"} and (args.file is None or args.profile is None):
        parser.error("preview/prepare require --file and --profile")
    if args.command in {"prepare", "activate"} and (
        args.profile is None or args.expected_review is None
    ):
        parser.error("prepare/activate require --profile and --expected-review")
    try:
        service = Activation(install.Installation(args.root))
        if args.command == "preview":
            result = service.preview(args.slot, args.file, args.profile)
        elif args.command == "prepare":
            result = service.prepare(args.slot, args.file, args.profile, args.expected_review)
        elif args.command == "activate":
            result = service.activate(args.slot, args.profile, args.expected_review)
        else:
            result = service.rollback(args.slot)
    except Exception:
        parser.exit(
            1,
            "Recovery activation refused. Preserve source, live data and incomplete profiles; verify owner/version, supported record types, artifact integrity and current review.\n",
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
