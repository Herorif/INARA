"""Private stdin control worker for the native setup UI. No HTTP, shell or provider."""

import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "setup_recovery", ROOT / "scripts/desktop-recovery.py"
)
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)
install, backup = recovery.install, recovery.backup
ERASE = "ERASE INARA DATA"
ACTIONS = {
    "install",
    "add_version",
    "select",
    "rollback",
    "uninstall",
    "erase_data",
    "resume",
    "backup",
    "prepare_recovery",
    "activate_recovery",
    "rollback_recovery",
    "launch",
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def path(value):
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise ValueError("Choose a valid local path")
    result = Path(value)
    if result.drive.startswith("\\\\"):
        raise ValueError("Choose a local drive, not a network path")
    if not result.is_absolute():
        raise ValueError("Choose an absolute path")
    return install.plain(result)


def snapshot(root):
    target = root / "installation.json"
    return install.package.release.sha256(target) if target.exists() else None


def owned_tree(root, target, kind, installation):
    root, target = install.plain(root, True), install.plain(target, True)
    relative = target.relative_to(root)
    expected = "versions" if kind == "software" else relative.parts[0]
    if len(relative.parts) != 2 or expected not in (
        {"versions"} if kind == "software" else {"data", "recovery-profiles"}
    ):
        raise ValueError("Removal target is outside its owned scope")
    if expected in {"versions", "data"}:
        install.identifier(relative.parts[1])
    else:
        recovery.profile_id(relative.parts[1])
    if kind == "data":
        marker = install.read(target / ".inara-data.json")
        if marker.get("installation") != installation or marker.get("format") != 1:
            raise ValueError("Data ownership is incompatible; preserve this directory")
        install.identifier(marker.get("slot"))
        if expected == "data" and marker["slot"] != relative.parts[1]:
            raise ValueError("Data slot ownership changed")
    result = []
    for folder, dirs, names in os.walk(target, followlinks=False):
        for name in dirs + names:
            item = install.plain(Path(folder) / name)
            if not item.is_relative_to(target):
                raise ValueError("Removal escaped its owned target")
            relative_name = backup.path_name(item.relative_to(root).as_posix()).as_posix()
            if item.is_file():
                if item.stat().st_nlink != 1:
                    raise ValueError("Linked removal payload")
                result.append(
                    {
                        "path": relative_name,
                        "bytes": item.stat().st_size,
                        "sha256": install.package.release.sha256(item),
                    }
                )
            elif item.is_dir():
                result.append({"path": relative_name, "directory": True})
            else:
                raise ValueError("Unsupported removal entry")
            if len(result) > 100000:
                raise ValueError("Removal inventory exceeds limit")
    result.append({"path": relative.as_posix(), "directory": True})
    return sorted(result, key=lambda value: value["path"])


def removal_plan(manager, state, kind):
    records = []
    if kind == "software":
        if not state["slots"]:
            raise ValueError("There is no installed software to remove")
        for slot in state["slots"]:
            manager.check(slot)
            records.extend(
                owned_tree(manager.root, manager.root / "versions" / slot, kind, state["id"])
            )
        # Do not abandon an unregistered/incomplete version during uninstall.
        if {item.name for item in (manager.root / "versions").iterdir()} != set(
            state["slots"]
        ) or any((manager.root / "transactions").iterdir()):
            raise ValueError("Resolve incomplete installs before removing software")
    else:
        if state["slots"] or state["current"] is not None:
            raise ValueError("Remove software before erasing retained data")
        for name in ("data", "recovery-profiles"):
            parent = install.plain(manager.root / name)
            if parent.exists():
                for item in parent.iterdir():
                    records.extend(owned_tree(manager.root, item, kind, state["id"]))
        if not records:
            raise ValueError("There is no retained profile data to erase")
    return records


def remove(manager, kind, expected_records=None):
    with manager.locked(allow_removal=True) as state:
        journal_path = install.plain(manager.root / "removal-pending.json")
        if journal_path.exists():
            journal = install.read(journal_path)
            if (
                set(journal)
                != {"format", "installation", "kind", "before", "after", "records", "id"}
                or journal["format"] != 1
                or journal["installation"] != state["id"]
                or journal["kind"] != kind
            ):
                raise ValueError("Removal journal is incompatible; preserve it")
            if state not in (journal["before"], journal["after"]):
                raise ValueError("Installation changed during interrupted removal")
        else:
            records = removal_plan(manager, state, kind)
            if records != expected_records:
                raise ValueError("Removal contents changed since review")
            after = json.loads(canonical(state))
            if kind == "software":
                after["current"], after["previous"], after["slots"] = None, None, {}
                if "recovery" in after:
                    after["recovery"]["slots"] = {}
            after["generation"] += 1
            journal = {
                "format": 1,
                "installation": state["id"],
                "kind": kind,
                "before": state,
                "after": after,
                "records": records,
                "id": uuid.uuid4().hex,
            }
            if len(canonical(journal).encode()) > 4_194_304:
                raise ValueError("Removal journal exceeds its safe limit")
            install.write(journal_path, journal)
        if (
            not re.fullmatch(r"[a-f0-9]{32}", journal["id"])
            or not isinstance(journal["records"], list)
            or len(journal["records"]) > 100000
        ):
            raise ValueError("Invalid removal inventory")
        expected_after = json.loads(canonical(journal["before"]))
        if kind == "software":
            expected_after["current"], expected_after["previous"], expected_after["slots"] = (
                None,
                None,
                {},
            )
            if "recovery" in expected_after:
                expected_after["recovery"]["slots"] = {}
        expected_after["generation"] += 1
        if journal["after"] != expected_after:
            raise ValueError("Removal commit metadata changed")
        # Preflight every remaining path before deleting anything. Journal paths cannot escape
        # the exact owned version/data roots, even after an interruption.
        paths = []
        for entry in journal["records"]:
            relative = backup.path_name(entry["path"])
            allowed = {"versions"} if kind == "software" else {"data", "recovery-profiles"}
            if len(relative.parts) < 2 or relative.parts[0] not in allowed:
                raise ValueError("Unsafe removal journal path")
            if relative.parts[0] == "recovery-profiles":
                recovery.profile_id(relative.parts[1])
            else:
                install.identifier(relative.parts[1])
            item = install.plain(manager.root.joinpath(*relative.parts))
            if not item.is_relative_to(manager.root / relative.parts[0]):
                raise ValueError("Removal target escaped installation")
            if item.exists():
                if entry.get("directory") is True:
                    if set(entry) != {"path", "directory"} or not item.is_dir():
                        raise ValueError("Removal directory changed")
                elif (
                    set(entry) != {"path", "bytes", "sha256"}
                    or not item.is_file()
                    or item.stat().st_nlink != 1
                    or item.stat().st_size != entry["bytes"]
                    or install.package.release.sha256(item) != entry["sha256"]
                ):
                    raise ValueError("Removal file changed; preserve it")
            paths.append((item, entry.get("directory") is True))
        allowed_names = {item.relative_to(manager.root).as_posix() for item, _ in paths}
        if len({value.casefold() for value in allowed_names}) != len(journal["records"]):
            raise ValueError("Duplicate removal journal entries")
        owned_roots = {Path(*Path(name).parts[:2]) for name in allowed_names}
        for relative_root in owned_roots:
            target = install.plain(manager.root / relative_root)
            if target.exists():
                for folder, dirs, names in os.walk(target, followlinks=False):
                    for name in dirs + names:
                        entry = install.plain(Path(folder) / name)
                        if entry.relative_to(manager.root).as_posix() not in allowed_names:
                            raise ValueError("Unknown file appeared during removal; preserve it")
        for item, directory in paths:
            if not directory and item.exists():
                install.plain(item)
                item.unlink()
        for item, directory in sorted(paths, key=lambda pair: len(pair[0].parts), reverse=True):
            if directory and item.exists():
                install.plain(item)
                item.rmdir()  # Unknown extras refuse; never recurse blindly.
        install.write(manager.root / "installation.json", journal["after"])
        receipts = install.plain(manager.root / "removal-receipts")
        receipts.mkdir(exist_ok=True)
        destination = receipts / (journal["id"] + ".json")
        receipt = {
            "format": 1,
            "id": journal["id"],
            "kind": kind,
            "installation": state["id"],
            "completed": True,
            "data_preserved": kind == "software",
            "files": sum("bytes" in record for record in journal["records"]),
            "generation": journal["after"]["generation"],
            "retained_profiles": journal["before"].get("recovery", {}).get("slots", {})
            if kind == "software"
            else {},
        }
        if destination.exists():
            if install.read(destination) != receipt:
                raise ValueError("Removal receipt changed; preserve journal")
        else:
            install.write(destination, receipt)
        journal_path.unlink()  # Only our bounded journal; no private filenames remain in receipts.
        return {
            "removed": kind,
            "data_preserved": kind == "software",
            "software_removed": kind == "software",
        }


class Control:
    def __init__(self, directory=ROOT, verify=True):
        self.directory = install.plain(directory, True)
        if verify:
            value = install.package.verify(self.directory)
            if value["kind"] != "desktop-core-pilot":
                raise ValueError("A bundled control candidate is required")
        self.pending = None

    def status(self, root):
        root = path(root)
        if not root.exists():
            return {"exists": False, "versions": [], "selected": None}
        manager = install.Installation(root)
        if (root / "removal-pending.json").exists():
            with manager.locked(allow_removal=True):
                journal = install.read(root / "removal-pending.json")
                return {
                    "exists": True,
                    "needs_resume": True,
                    "removal_kind": journal.get("kind"),
                    "versions": [],
                }
        value = manager.status()
        return {
            "exists": True,
            "versions": [
                {
                    "slot": item,
                    "label": "Build "
                    + item[:12]
                    + (" / Selected" if item == value["selected"] else ""),
                    "selected": item == value["selected"],
                }
                for item in value["slots"]
            ],
            "selected": value["selected"],
            "previous": value["previous"],
            "recovery_profiles": value["recovery_profiles"],
            "incomplete_installs": value["recovery_candidates"],
            "retained_data": any((root / "data").iterdir())
            or (
                (root / "recovery-profiles").exists()
                and any((root / "recovery-profiles").iterdir())
            ),
        }

    def retained(self, manager, slot):
        parent = install.plain(manager.root / "removal-receipts")
        if not parent.exists():
            return None
        receipts = list(parent.iterdir())
        if len(receipts) > 256:
            raise ValueError("Removal receipt inventory exceeds limit")
        values = [install.read(item) for item in receipts]
        values = [
            value
            for value in values
            if value.get("kind") == "software" and value.get("installation") == manager.load()["id"]
        ]
        if not values:
            return None
        latest = max(values, key=lambda value: value["generation"])
        record = latest.get("retained_profiles", {}).get(slot)
        if not record or record.get("current") is None:
            return None
        if not (manager.root / "data" / slot).exists():
            return None
        for profile in record.values():
            if profile is not None:
                manager.profile_data(manager.load(), slot, profile)
        return record

    def review(self, request):
        self.pending = None
        if set(request) - {"action", "root", "package", "slot", "file", "profile", "resident_only"}:
            raise ValueError("Unknown setup request fields")
        action = request.get("action")
        if action not in ACTIONS:
            raise ValueError("Unknown setup action")
        root = path(request.get("root"))
        if self.directory.is_relative_to(root) or root.is_relative_to(self.directory):
            raise ValueError("Keep the control candidate outside the installation")
        params = {**request, "root": str(root)}
        plan = {
            "action": action,
            "installation": str(root),
            "data_policy": "Keep existing profiles",
            "local_pilot": True,
        }
        manager = install.Installation(root) if root.exists() else None
        extra = {}
        if action in {"install", "add_version"}:
            candidate = path(request.get("package") or str(self.directory))
            result = install.package.verify(candidate)
            if result["kind"] != "desktop-core-pilot":
                raise ValueError("Use a bundled core candidate")
            if action == "install" and root.exists():
                raise ValueError("Choose a new installation folder")
            if action == "add_version" and manager is None:
                raise ValueError("Create an installation first")
            params["package"] = str(candidate)
            extra["candidate_sha256"] = install.package.release.sha256(
                candidate / "desktop-pilot.json"
            )
            if manager is not None:
                retained = self.retained(manager, extra["candidate_sha256"])
                if retained is not None:
                    extra["retained_selection"] = retained
                    plan["data_policy"] = (
                        "Reuse this build's retained selected recovery profile; keep the original profile too"
                    )
                elif (root / "data" / extra["candidate_sha256"]).exists():
                    plan["data_policy"] = "Reuse this build's retained original profile"
            plan.update(
                package=str(candidate),
                version=extra["candidate_sha256"][:12],
                result="Install software; select it separately",
            )
        elif manager is None:
            raise ValueError("Choose an existing managed installation")
        if manager is not None:
            with manager.locked(allow_removal=action == "resume") as state:
                if action in {
                    "select",
                    "backup",
                    "prepare_recovery",
                    "activate_recovery",
                    "rollback_recovery",
                }:
                    slot = install.identifier(request.get("slot"))
                    manager.check(slot)
                    plan["version"] = slot[:12]
                if action == "select":
                    manager.data(state, params["slot"])
                    plan["result"] = "Use this version and its own data; launch separately"
                elif action == "rollback":
                    if state["previous"] is None:
                        raise ValueError("No previous version is available")
                    manager.check(state["previous"])
                    plan["result"] = "Return to previous version and its separate data"
                elif action in {"uninstall", "erase_data"}:
                    kind = "software" if action == "uninstall" else "data"
                    extra["records"] = removal_plan(manager, state, kind)
                    plan.update(
                        files=sum("bytes" in item for item in extra["records"]),
                        bytes=sum(item.get("bytes", 0) for item in extra["records"]),
                        result="Remove software; retain profiles and recovery copies"
                        if kind == "software"
                        else "Permanently erase retained profiles and recovery copies",
                        data_policy="Keep existing profiles"
                        if kind == "software"
                        else "Permanent erasure",
                        confirmation_required=action == "erase_data",
                    )
                elif action == "resume":
                    journal = install.read(root / "removal-pending.json")
                    extra["kind"] = journal["kind"]
                    plan.update(
                        result="Finish the previously approved removal",
                        confirmation_required=journal["kind"] == "data",
                    )
                elif action == "backup":
                    output = path(request.get("file"))
                    params["file"] = str(output)
                    if output.exists() or output.is_relative_to(root):
                        raise ValueError("Choose a new backup file outside the installation")
                    manager.data(state, request["slot"])
                    plan.update(
                        result="Create an original-Windows-account encrypted backup",
                        destination=str(output),
                    )
                elif action == "activate_recovery":
                    profile = recovery.profile_id(request.get("profile"))
                    target = manager.profile_data(state, params["slot"], profile)
                    receipt = install.read(target / backup.RECEIPT)
                    extra["recovery_review"] = receipt["review_sha256"]
                    plan.update(
                        result="Activate the prepared recovery copy",
                        profile=profile,
                        owner_fingerprint=backup.digest(receipt["owner"].encode()),
                        installation_format=2,
                    )
                elif action == "rollback_recovery":
                    plan["result"] = "Return to the previous recovery/original profile; keep both"
                elif action == "launch":
                    if state["current"] is None:
                        raise ValueError("Select an installed version first")
                    manager.check(state["current"])
                    manager.data(state, state["current"])
                    if type(request.get("resident_only", True)) is not bool:
                        raise ValueError("Invalid workspace preference")
                    plan.update(
                        result="Start INARA in the tray"
                        if request.get("resident_only", True)
                        else "Start INARA and open the workspace",
                        version=state["current"][:12],
                    )
        if action == "prepare_recovery":
            params["file"] = str(path(request.get("file")))
            params["profile"] = uuid.uuid4().hex
            preview = recovery.Activation(manager).preview(
                params["slot"], Path(params["file"]), params["profile"]
            )
            extra["recovery_review"] = preview["review_sha256"]
            plan.update(
                result="Prepare a compatible recovery copy; activate separately", recovery=preview
            )
        token = uuid.uuid4().hex
        self.pending = {
            "token": token,
            "expires": time.monotonic() + 300,
            "params": params,
            "state": snapshot(root),
            "extra": extra,
        }
        return {"token": token, "plan": plan}

    def apply(self, token, confirmation=""):
        pending, self.pending = self.pending, None  # Single-use, including ambiguous failures.
        if pending is None or token != pending["token"] or time.monotonic() > pending["expires"]:
            raise ValueError("Review expired; review this action again")
        request, extra = pending["params"], pending["extra"]
        root, action = path(request["root"]), request["action"]
        if snapshot(root) != pending["state"]:
            raise ValueError("Installation changed; review again")
        if action == "erase_data" or (action == "resume" and extra["kind"] == "data"):
            if confirmation != ERASE:
                raise ValueError("Type the exact data-erasure confirmation")
        manager = install.Installation(root) if root.exists() else None
        if action in {"install", "add_version"}:
            candidate = path(request["package"])
            if (
                install.package.release.sha256(candidate / "desktop-pilot.json")
                != extra["candidate_sha256"]
            ):
                raise ValueError("Candidate changed; review again")
            if action == "install":
                manager = install.Installation.create(root)
            return manager.install(candidate, recovery_selection=extra.get("retained_selection"))
        if action == "select":
            return manager.activate(request["slot"])
        if action == "rollback":
            return manager.activate(rollback=True)
        if action in {"uninstall", "erase_data"}:
            return remove(
                manager, "software" if action == "uninstall" else "data", extra["records"]
            )
        if action == "resume":
            return remove(manager, extra["kind"])
        if action == "backup":
            return backup.Recovery(manager).backup(request["slot"], Path(request["file"]))
        if action == "prepare_recovery":
            return recovery.Activation(manager).prepare(
                request["slot"], Path(request["file"]), request["profile"], extra["recovery_review"]
            )
        if action == "activate_recovery":
            return recovery.Activation(manager).activate(
                request["slot"], request["profile"], extra["recovery_review"]
            )
        if action == "rollback_recovery":
            return recovery.Activation(manager).rollback(request["slot"])
        if action == "launch":
            with manager.locked() as state:
                directory = manager.check(state["current"])
                manager.data(state, state["current"])
                executable = directory / "runtime/python/python.exe"
            process = subprocess.Popen(
                [
                    str(executable),
                    "-I",
                    "-B",
                    "-X",
                    "utf8",
                    str(self.directory / "scripts/desktop-control.py"),
                    "--resident",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
                close_fds=True,
            )
            process.stdin.write(
                (
                    canonical(
                        {"root": str(root), "resident_only": request.get("resident_only", True)}
                    )
                    + "\n"
                ).encode()
            )
            process.stdin.close()
            return {
                "launch_requested": True,
                "pid": process.pid,
                "message": "Starting INARA. Check its tray icon; this request is not a readiness confirmation.",
            }
        raise ValueError("Unsupported action")


def main():
    if sys.argv[1:] == ["--resident"]:
        raw = sys.stdin.buffer.readline(65537)
        request = json.loads(raw)
        if set(request) != {"root", "resident_only"} or type(request["resident_only"]) is not bool:
            raise ValueError("Invalid resident bootstrap")
        install.Installation(path(request["root"])).launch(request["resident_only"])
        return
    if sys.argv[1:]:
        raise ValueError("Unsupported control arguments")
    control = Control()
    print(json.dumps({"ready": True, "local_pilot": True}), flush=True)
    while True:
        raw = sys.stdin.buffer.readline(65537)
        if not raw:
            return
        if len(raw) > 65536:
            raise ValueError("Control request exceeds limit")
        try:
            request = json.loads(raw)
            if request.get("op") == "status" and set(request) == {"op", "root"}:
                result = control.status(request["root"])
            elif request.get("op") == "review" and set(request) == {"op", "request"}:
                result = control.review(request["request"])
            elif request.get("op") == "apply" and set(request) <= {"op", "token", "confirmation"}:
                result = control.apply(request["token"], request.get("confirmation", ""))
            else:
                raise ValueError("Unknown control operation")
            response = {"ok": True, "result": result}
        except Exception as exc:
            response = {
                "ok": False,
                "error": str(exc)
                if isinstance(exc, ValueError)
                else "Operation did not complete. Refresh status before retrying; preserve data and incomplete copies.",
            }
        print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
