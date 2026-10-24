"""Offline unsigned pilot version slots. No downloads, migration or file deletion."""

import argparse
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import sys
import uuid

sys.dont_write_bytecode = True  # Imported slot tooling must never dirty its own package.
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "install_package", ROOT / "scripts/desktop-package.py"
)
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)
SLOT = re.compile(r"[a-f0-9]{64}")


def plain(path, directory=False):
    path = Path(path).absolute()
    if path.resolve() != path or path.is_symlink() or path.is_junction():
        raise ValueError("Linked or noncanonical installation path")
    if directory and not path.is_dir():
        raise ValueError("Missing installation directory")
    return path


def read(path):
    return package.read_json(plain(path))


def write(path, value):
    plain(path.parent, True)
    if path.exists():
        plain(path)
    temporary = path.parent / (".write-" + uuid.uuid4().hex)
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def identifier(value):
    if not isinstance(value, str) or not SLOT.fullmatch(value):
        raise ValueError("Invalid version slot")
    return value


class Installation:
    def __init__(self, root, *, authenticated=False, pending_update=False):
        self.root = plain(root, True)
        self.authenticated = authenticated
        self.pending_update = pending_update

    @classmethod
    def create(cls, root):
        root = plain(root)
        if root.exists():
            raise ValueError("Choose a NEW installation root; existing profiles are never adopted")
        root.mkdir(parents=True)
        for name in ("versions", "transactions", "data"):
            (root / name).mkdir()
        write(
            root / "installation.json",
            {
                "format": 1,
                "kind": "unsigned-pilot-slots",
                "id": uuid.uuid4().hex,
                "generation": 0,
                "current": None,
                "previous": None,
                "slots": {},
            },
        )
        return cls(root)

    @contextmanager
    def locked(self, allow_removal=False):
        # An OS byte lock releases on process death; no stale-lock deletion is needed.
        import msvcrt

        path = plain(self.root / ".manager.lock")
        with path.open("a+b") as stream:
            if path.stat().st_size == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ValueError(
                    "Installation is busy; stop its resident or other manager first"
                ) from exc
            try:
                yield self.load(allow_removal=allow_removal)
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)

    def load(self, allow_removal=False):
        for name in ("versions", "transactions", "data"):
            plain(self.root / name, True)
        if (self.root / "removal-pending.json").exists() and not allow_removal:
            raise ValueError("Removal was interrupted; resume it with the current setup controls")
        if (self.root / "update-pending.json").exists() and not self.pending_update:
            raise ValueError("Signed update is pending; use reviewed update recovery")
        value = read(self.root / "installation.json")
        managed = value.get("format") == 3
        if (
            set(value)
            != (
                {"format", "kind", "id", "generation", "current", "previous", "slots"}
                | ({"recovery"} if value.get("format") in (2, 3) else set())
                | ({"security"} if managed else set())
            )
            or type(value["format"]) is not int
            or value["format"] not in ((1, 2, 3) if self.authenticated else (1, 2))
            or value["kind"] != ("authenticated-pilot-slots" if managed else "unsigned-pilot-slots")
            or not isinstance(value["id"], str)
            or not re.fullmatch(r"[a-f0-9]{32}", value["id"])
            or type(value["generation"]) is not int
            or value["generation"] < 0
            or not isinstance(value["slots"], dict)
            or len(value["slots"]) > 16
        ):
            raise ValueError("Unsupported or damaged installation state; preserve it")
        if managed:
            security = value["security"]
            if (
                set(security) != {"format", "anchor", "id"}
                or type(security["format"]) is not int
                or security["format"] != 1
                or not isinstance(security["id"], str)
                or not re.fullmatch(r"[a-f0-9]{32}", security["id"])
                or not isinstance(security["anchor"], str)
                or str(plain(security["anchor"])) != security["anchor"]
            ):
                raise ValueError("Invalid managed trust binding")
        for slot, record in value["slots"].items():
            identifier(slot)
            if record != {"manifest_sha256": slot}:
                raise ValueError("Changed slot identity")
        for key in ("current", "previous"):
            if value[key] is not None and value[key] not in value["slots"]:
                raise ValueError("Selected slot is not registered")
        self.selections(value)
        return value

    def save(self, state):
        state["generation"] += 1
        write(self.root / "installation.json", state)

    def selections(self, state):
        value = state.get("recovery", {"format": 1, "installation": state["id"], "slots": {}})
        if (
            set(value) != {"format", "installation", "slots"}
            or value["format"] != 1
            or value["installation"] != state["id"]
            or not isinstance(value["slots"], dict)
        ):
            raise ValueError("Damaged recovery selection; preserve it")
        for slot, record in value["slots"].items():
            if slot not in state["slots"] or set(record) != {"current", "previous"}:
                raise ValueError("Unknown recovery slot")
            for profile in record.values():
                if profile is not None and (
                    not isinstance(profile, str) or not re.fullmatch(r"[a-f0-9]{32}", profile)
                ):
                    raise ValueError("Invalid recovery profile identity")
        return value

    def data(self, state, slot, create=False):
        selected = self.selections(state)["slots"].get(slot, {}).get("current")
        return self.profile_data(state, slot, selected, create)

    def profile_data(self, state, slot, profile=None, create=False):
        identifier(slot)
        if profile is None:
            path = plain(self.root / "data" / slot)
        else:
            if not isinstance(profile, str) or not re.fullmatch(r"[a-f0-9]{32}", profile):
                raise ValueError("Invalid recovery profile")
            path = plain(self.root / "recovery-profiles" / profile, True)
            receipt = read(path / ".inara-recovery.json")
            if (
                receipt.get("status") != "prepared"
                or receipt.get("installation") != state["id"]
                or receipt.get("slot") != slot
                or receipt.get("profile") != profile
            ):
                raise ValueError("Recovery profile is incomplete or incompatible")
            identity = read(path / "desktop-profile/resident-identity.json")
            if identity.get("id") != receipt.get("owner"):
                raise ValueError("Recovery resident owner changed")
        expected = {"format": 1, "installation": state["id"], "slot": slot}
        if create and not path.exists():
            path.mkdir()
            write(path / ".inara-data.json", expected)
        if not path.is_dir() or read(path / ".inara-data.json") != expected:
            raise ValueError(
                "Data ownership is missing or incompatible; no adoption/migration allowed"
            )
        # Reject links in the fixed paths passed to the resident, including settings.
        for name in ("database", "settings.json", "projects", "legacy", "desktop-profile"):
            plain(path / name)
        return path

    def check(self, slot, directory=None):
        slot = identifier(slot)
        directory = plain(directory or self.root / "versions" / slot, True)
        if package.release.sha256(plain(directory / "desktop-pilot.json")) != slot:
            raise ValueError("Slot manifest identity changed")
        result = package.verify(directory)
        if result["kind"] != "desktop-core-pilot" or not result["self_contained"]:
            raise ValueError("Only bundled core pilots can occupy installation slots")
        return directory

    def register(self, state, slot, recovery_selection=None):
        self.check(slot)
        self.data(state, slot, create=True)
        state["slots"][slot] = {"manifest_sha256": slot}
        if recovery_selection is not None:
            if set(recovery_selection) != {"current", "previous"}:
                raise ValueError("Invalid retained recovery selection")
            original = self.profile_data(state, slot)
            original_owner = read(original / "desktop-profile/resident-identity.json")["id"]
            for profile in recovery_selection.values():
                if profile is not None:
                    target = self.profile_data(state, slot, profile)
                    if (
                        read(target / "desktop-profile/resident-identity.json")["id"]
                        != original_owner
                    ):
                        raise ValueError("Retained recovery owner is incompatible")
            selection = self.selections(state)
            selection["slots"][slot] = recovery_selection
            state["format"], state["recovery"] = 2, selection
        self.save(state)

    def install(
        self,
        source,
        recovery_selection=None,
        admission=None,
        expected_state=None,
        before_register=None,
    ):
        source = plain(source, True)
        if source.is_relative_to(self.root) or self.root.is_relative_to(source):
            raise ValueError("Candidate and installation root must be separate")
        with self.locked() as state:
            if (
                expected_state is not None
                and package.release.sha256(self.root / "installation.json") != expected_state
            ):
                raise ValueError("Reviewed installation state changed")
            if admission is not None:
                admission(source)
            result = package.verify(source)
            if result["kind"] != "desktop-core-pilot" or not result["self_contained"]:
                raise ValueError("An isolated bundled core pilot is required")
            if len(state["slots"]) >= 16:
                raise ValueError("Pilot slot limit reached; preserve existing versions")
            slot = package.release.sha256(source / "desktop-pilot.json")
            pending = self.root / "transactions" / slot
            target = self.root / "versions" / slot
            if slot in state["slots"] or pending.exists() or target.exists():
                raise ValueError("Version already exists or needs explicit recovery")
            # Verify before and after copy; never execute candidate code to verify it.
            shutil.copytree(source, pending, symlinks=True)
            self.check(slot, pending)
            self.check(slot, source)
            if admission is not None:
                admission(pending)
                admission(source)
            os.rename(pending, target)
            if admission is not None:
                admission(target)
            if before_register is not None:
                before_register(state, slot, target)
            if recovery_selection is None:
                self.register(state, slot)
            else:
                self.register(state, slot, recovery_selection)
            return {"installed": True, "slot": slot, "activated": False, "signed": False}

    def activate(self, slot=None, rollback=False):
        with self.locked() as state:
            if rollback:
                slot = state["previous"]
            if slot is None:
                raise ValueError("No previous version is available")
            identifier(slot)
            if slot not in state["slots"]:
                raise ValueError("Version is not registered")
            self.check(slot)
            self.data(state, slot)
            if slot == state["current"]:
                raise ValueError("Version is already selected")
            state["previous"], state["current"] = state["current"], slot
            self.save(state)
            return {"selected": slot, "rolled_back": rollback, "data_migrated": False}

    def deactivate(self):
        with self.locked() as state:
            if state["current"] is not None:
                state["previous"], state["current"] = state["current"], None
                self.save(state)
            return {"selected": None, "packages_retained": True, "data_retained": True}

    def recover(self, slot, admission=None, expected_state=None, before_register=None):
        identifier(slot)
        with self.locked() as state:
            if (
                expected_state is not None
                and package.release.sha256(self.root / "installation.json") != expected_state
            ):
                raise ValueError("Reviewed installation state changed")
            if slot in state["slots"] or len(state["slots"]) >= 16:
                raise ValueError("Version is already registered or slot limit reached")
            pending = plain(self.root / "transactions" / slot)
            target = plain(self.root / "versions" / slot)
            if pending.exists() and target.exists():
                raise ValueError("Ambiguous recovery; preserve both copies")
            if pending.exists():
                self.check(slot, pending)
                if admission is not None:
                    admission(pending)
                os.rename(pending, target)
            if admission is not None:
                admission(target)
            if before_register is not None:
                before_register(state, slot, target)
            self.register(state, slot)
            return {"recovered": slot, "activated": False, "data_migrated": False}

    def status(self):
        with self.locked() as state:
            for slot in state["slots"]:
                self.check(slot)
                self.data(state, slot)
            pending = []
            for name in ("transactions", "versions"):
                for path in (self.root / name).iterdir():
                    plain(path, True)
                    identifier(path.name)
                    if name == "transactions" or path.name not in state["slots"]:
                        pending.append({"slot": path.name, "location": name})
            return {
                "recovery_profiles": self.selections(state)["slots"],
                "selected": state["current"],
                "previous": state["previous"],
                "slots": list(state["slots"]),
                "recovery_candidates": pending,
                "generation": state["generation"],
                "signed": False,
            }

    def launch(self, resident_only=False):
        with self.locked() as state:
            slot = state["current"]
            if slot is None:
                raise ValueError("Select a verified version before launch")
            directory = self.check(slot)
            data = self.data(state, slot)
            if Path(sys.executable).resolve() != directory / "runtime/python/python.exe":
                raise ValueError(
                    "Launch using the selected slot's bundled Python; no interpreter fallback"
                )
            # Run in this process: the OS manager lock spans the entire resident lifetime.
            # Existing resident job supervision owns its child processes.
            paths = {
                "INARA_DATA_DIR": data / "database",
                "INARA_SETTINGS_FILE": data / "settings.json",
                "INARA_PROJECT_ROOT": data / "projects",
                "INARA_LEGACY_DATA_DIR": data / "legacy",
                "INARA_DESKTOP_DATA_DIR": data / "desktop-profile",
            }
            keys = set(paths) | {"INARA_DEV_SERVER", "ELECTRON_RUN_AS_NODE"}
            previous = {key: os.environ.get(key) for key in keys}
            argv = sys.argv[:]
            try:
                os.environ.update({key: str(path) for key, path in paths.items()})
                for key in keys - set(paths):
                    os.environ.pop(key, None)
                entry = directory / "backend/resident_main.py"
                sys.argv = [str(entry)] + (["--resident-only"] if resident_only else [])
                sys.dont_write_bytecode = True
                runpy.run_path(str(entry), run_name="__main__")
            finally:
                sys.argv = argv
                for key, value in previous.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "init",
            "install",
            "status",
            "activate",
            "rollback",
            "recover",
            "deactivate",
            "launch",
        ),
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--slot")
    parser.add_argument("--resident-only", action="store_true")
    args = parser.parse_args()
    if args.command == "install" and args.package is None:
        parser.error("install requires --package")
    if args.command in {"activate", "recover"} and args.slot is None:
        parser.error("this command requires --slot")
    if sys.platform != "win32":
        parser.error("Pilot installation slots currently support Windows only")
    try:
        if args.command == "init":
            result = Installation.create(args.root).status()
        else:
            manager = Installation(args.root)
            if args.command == "install":
                result = manager.install(args.package)
            elif args.command == "activate":
                result = manager.activate(args.slot)
            elif args.command == "rollback":
                result = manager.activate(rollback=True)
            elif args.command == "recover":
                result = manager.recover(args.slot)
            elif args.command == "launch":
                manager.launch(args.resident_only)
                return
            else:
                result = getattr(manager, args.command)()
    except (OSError, ValueError, KeyError, TypeError):
        parser.exit(
            1,
            "Pilot slot operation refused. Preserve installation/data; inspect status or use explicit recovery. No package/data was deleted.\n",
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
