"""Pinned profile copies and separately signed profile/removal transitions. Offline only."""

import base64
from contextlib import contextmanager
from datetime import timedelta
import json
import os
from pathlib import Path

import importlib.util

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location("lifecycle_" + name, ROOT / "scripts" / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


managed, recovery = module("managed-update"), module("desktop-recovery")
signed, trust, review, backup = managed.signed, managed.trust, managed.review, recovery.backup
DOMAIN = b"INARA:managed-lifecycle:v1\n"
ACTIONS = {"activate-profile", "rollback-profile", "remove-software", "erase-data"}
ERASE = "ERASE INARA DATA"


def verify(envelope, before, after, now=None):
    review.exact(envelope, {"statement", "signatures_before", "signatures_after"})
    value = envelope["statement"]
    review.exact(value, managed.FIELDS | {"details"})
    if type(value["format"]) is not int or value["format"] != 1 or value["kind"] != "inara-managed-lifecycle" or value["action"] not in ACTIONS:
        raise ValueError("Unsupported lifecycle authorization")
    issued, expires, current = trust.stamp(value["issued_at"]), trust.stamp(value["expires_at"]), trust.utc(now)
    if not issued <= current < expires or not timedelta(0) < expires - issued <= timedelta(hours=1):
        raise ValueError("Lifecycle authorization expired")
    for key in ("number", "sequence", "before_floor"):
        trust.integer(value[key])
    for key in ("previous_checkpoint", "previous_head", "target", "policy_before", "policy_after", "windows_before", "windows_after", "source_policy", "grant_sha256", "installation_before", "authorization_before", "installation_after", "authorization_after", "archives_sha256"):
        trust.digest(value[key])
    review.exact(value["details"], {"slot", "profile", "inventory_sha256", "binding_sha256", "files", "bytes"})
    signed.manager.identifier(value["details"]["slot"])
    if value["details"]["profile"] is not None:
        recovery.profile_id(value["details"]["profile"])
    trust.digest(value["details"]["binding_sha256"])
    if value["action"] in {"remove-software", "erase-data"}:
        trust.digest(value["details"]["inventory_sha256"])
    elif value["details"]["inventory_sha256"] is not None:
        raise ValueError("Unexpected deletion inventory")
    trust.integer(value["details"]["files"], 0, 100000)
    trust.integer(value["details"]["bytes"], 0, 2_147_483_648)
    if before["mode"] != "production" or before != after or value["policy_before"] != value["policy_after"] or value["windows_before"] != value["windows_after"] or value["authorization_before"] != value["authorization_after"] or value["previous_head"] != value["grant_sha256"]:
        raise ValueError("Lifecycle cannot rotate trust or replace launch grants")
    managed.roles(envelope["signatures_before"], before, value, current, DOMAIN)
    managed.roles(envelope["signatures_after"], after, value, current, DOMAIN)
    return value


@contextmanager
def locked(root, anchor, expected):
    root, anchor = managed.separate(root, anchor)
    service = signed.manager.Installation(root, authenticated=True)
    with service.locked() as state, managed.anchor_lock(anchor):
        node = managed.read_node(root, anchor, expected)
        managed.context(service, state, anchor, expected, node["grant"])
        yield service, state, node


class Held:
    """Reuse typed copy adapters under the already held protected-state leases."""
    def __init__(self, service, state):
        self.service, self.state = service, state

    def __getattr__(self, key):
        if key == "save":
            raise ValueError("Profile selection needs signed lifecycle authorization")
        return getattr(self.service, key)

    @contextmanager
    def locked(self):
        yield self.state


def snapshot(directory, prepared=False):
    paths, dirs = backup.inventory(directory, recovery=prepared)
    files = [{"path": name, "bytes": path.stat().st_size, "sha256": backup.digest(backup.bounded_read(path, backup.MAX_FILE))} for name, path in sorted(paths.items())]
    return {"directories": dirs, "files": files}


def copies(root, anchor, expected, operation, slot, file, profile=None, expected_review=None, *, _protector=None):
    if operation not in {"backup", "prepare-profile"}:
        raise ValueError("Unsupported profile copy")
    file = managed.external(file, [root, anchor, ROOT])
    with locked(root, anchor, expected) as (service, state, node):
        adapter = recovery.Activation(Held(service, state), _protector)
        if operation == "backup":
            if file.exists():
                raise ValueError("Choose a NEW external backup file")
            signed.plain(file.parent, True)
            adapter.recovery.source(state, slot)
            data = service.data(state, slot)
            inventory = snapshot(data, data.parent.name == "recovery-profiles")
            detail = {"source_sha256": review.hashed(inventory), "files": len(inventory["files"]), "bytes": sum(x["bytes"] for x in inventory["files"])}
        else:
            detail, token, _, _ = adapter.plan(state, slot, file, profile)
            detail = {"typed_review_sha256": token, "owner_fingerprint": detail["owner_fingerprint"], "destination": detail["destination"], "counts": detail["counts"]}
        plan = {"checkpoint": expected, "operation": operation, "slot": slot, "file": str(file), "profile": profile, "selection_unchanged": True, "launch": False, **detail}
        digest = review.hashed(plan)
        if expected_review is None:
            return {"plan": plan, "review_sha256": digest}
        if expected_review != digest:
            raise ValueError("Profile copy review changed")
        result = adapter.recovery.backup(slot, file, expected_inventory=inventory) if operation == "backup" else adapter.prepare(slot, file, profile, detail["typed_review_sha256"])
        if signed.digest_file(service.root / "installation.json") != node["installation_sha256"]:
            raise ValueError("Protected metadata changed during copy")
        return {**result, "checkpoint": expected, "selection_unchanged": True, "launched": False}


def inventory(service, state, action):
    roots = []
    if action == "remove-software":
        if not state["slots"]:
            raise ValueError("No installed software to remove")
        if {p.name for p in (service.root / "versions").iterdir()} != set(state["slots"]) or any((service.root / "transactions").iterdir()):
            raise ValueError("Resolve unknown or incomplete versions before removal")
        for slot in state["slots"]:
            roots.append(service.check(slot))
    else:
        if state["slots"] or state["current"] is not None or any((service.root / "versions").iterdir()) or any((service.root / "transactions").iterdir()):
            raise ValueError("Remove software before separate profile erasure")
        for name in ("data", "recovery-profiles"):
            parent = signed.plain(service.root / name)
            if parent.exists():
                for path in parent.iterdir():
                    path = signed.plain(path, True)
                    marker = signed.manager.read(path / ".inara-data.json")
                    if marker.get("format") != 1 or marker.get("installation") != state["id"]:
                        raise ValueError("Foreign profile ownership; preserve it")
                    signed.manager.identifier(marker.get("slot"))
                    if name == "data":
                        if path.name != marker["slot"]:
                            raise ValueError("Profile slot differs")
                    else:
                        recovery.profile_id(path.name)
                        receipt = signed.manager.read(path / backup.RECEIPT)
                        if receipt.get("installation") != state["id"] or receipt.get("slot") != marker["slot"] or receipt.get("profile") != path.name:
                            raise ValueError("Recovery profile ownership differs")
                    roots.append(path)
    records = []
    for target in roots:
        for folder, dirs, names in os.walk(target, followlinks=False):
            for name in dirs + names:
                path = signed.plain(Path(folder) / name)
                if not path.is_relative_to(target):
                    raise ValueError("Removal escaped owned root")
                entry = {"path": path.relative_to(service.root).as_posix()}
                if path.is_dir():
                    entry["directory"] = True
                elif path.is_file() and path.stat().st_nlink == 1:
                    entry.update(bytes=path.stat().st_size, sha256=signed.digest_file(path))
                else:
                    raise ValueError("Linked or unsupported removal entry")
                records.append(entry)
                if len(records) > 100000:
                    raise ValueError("Excessive removal inventory")
        records.append({"path": target.relative_to(service.root).as_posix(), "directory": True})
    if not records:
        raise ValueError("No retained profiles to erase")
    return sorted(records, key=lambda x: x["path"])


def profile_change(service, state, action, slot, profile):
    if slot not in state["slots"]:
        raise ValueError("Profile change requires a registered version")
    service.check(slot)
    selection = json.loads(review.encoded(service.selections(state)))
    current = selection["slots"].get(slot, {"current": None, "previous": None})
    if action == "rollback-profile":
        if slot not in selection["slots"]:
            raise ValueError("No previous profile selection")
        profile = current["previous"]
    target = service.profile_data(state, slot, profile)
    old = service.data(state, slot)
    owners = [signed.manager.read(p / "desktop-profile/resident-identity.json")["id"] for p in (old, target)]
    if owners[0] != owners[1] or profile == current["current"]:
        raise ValueError("Incompatible resident owner or already selected profile")
    binding = {"owner": owners[0], "target": str(target)}
    if action == "activate-profile":
        recovery.profile_id(profile)
        receipt = signed.manager.read(target / backup.RECEIPT)
        actual = snapshot(target, True)
        if receipt.get("generation") != state["generation"] or receipt.get("selection_sha256") != backup.digest(json.dumps(service.selections(state), sort_keys=True).encode()) or receipt.get("inventory") != {x["path"]: x["sha256"] for x in actual["files"]} or receipt.get("directories") != actual["directories"]:
            raise ValueError("Prepared profile or original selection changed; prepare a fresh copy")
        # Receipts alone are not a typed-data authority: validate the prepared DB again.
        paths, _ = backup.inventory(target, recovery=True)
        files = {name: backup.bounded_read(path, backup.MAX_FILE) for name, path in paths.items()}
        manifest = {"installation": state["id"], "slot": slot, "owner": owners[0], "source_data": str(target), "directories": actual["directories"]}
        backup.schema(files, manifest)
        recovery.rebind(files, manifest, service, target, backup.protection())
        binding["prepared"] = review.hashed(actual)
    selection["slots"][slot] = {"current": profile, "previous": current["current"]}
    return selection, profile, review.hashed(binding)


def build(service, state, node, expected, action, slot, profile, issued, expires):
    if action not in ACTIONS:
        raise ValueError("Unsupported lifecycle action")
    signed.manager.identifier(slot)
    after = json.loads(review.encoded(state))
    records = []
    if action in {"activate-profile", "rollback-profile"}:
        after["recovery"], profile, binding = profile_change(service, state, action, slot, profile)
    else:
        if profile is not None:
            raise ValueError("Removal does not take a profile selector")
        records = inventory(service, state, action)
        binding = review.hashed({"installation": state["id"], "action": action})
        if action == "remove-software":
            after.update(current=None, previous=None, slots={})
            after["recovery"]["slots"] = {}
    after["generation"] += 1
    details = {"slot": slot, "profile": profile, "inventory_sha256": review.hashed(records) if records else None,
               "binding_sha256": binding, "files": sum("bytes" in x for x in records), "bytes": sum(x.get("bytes", 0) for x in records)}
    trust.integer(details["files"], 0, 100000)
    trust.integer(details["bytes"], 0, 2_147_483_648)
    old_value = node["change"]["statement"]
    value = {**old_value, "kind": "inara-managed-lifecycle", "action": action, "number": node["number"] + 1,
             "previous_checkpoint": expected, "previous_head": node["grant"], "before_floor": node["floor"],
             "policy_before": node["policy"], "policy_after": node["policy"], "windows_before": node["windows"], "windows_after": node["windows"],
             "installation_before": signed.digest_file(service.root / "installation.json"), "installation_after": review.hashed(after),
             "authorization_before": signed.digest_file(service.root / "authorizations/state.json"), "authorization_after": signed.digest_file(service.root / "authorizations/state.json"),
             "issued_at": issued, "expires_at": expires, "details": details}
    return value, after, records


def prepare(root, anchor, expected, action, slot, profile, output, now=None, minutes=30):
    output = managed.external(output, [root, anchor, ROOT])
    trust.integer(minutes, 1, 60)
    if output.exists():
        raise ValueError("Choose a NEW lifecycle signing-request directory")
    with locked(root, anchor, expected) as (service, state, node):
        current = trust.utc(now)
        value = build(service, state, node, expected, action, slot, profile, current.strftime("%Y-%m-%dT%H:%M:%SZ"), (current + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ"))[0]
        output.mkdir(parents=True)
        (output / "statement.json").write_bytes(review.encoded(value))
        (output / "signing-message.bin").write_bytes(DOMAIN + review.encoded(value))
    return {"prepared": True, "signed": False, "launched": False}


def apply(root, anchor, expected, envelope_path, expected_review=None, confirmation="", now=None):
    root, anchor = managed.separate(root, anchor)
    envelope_path = managed.external(envelope_path, [root, anchor])
    envelope, raw = signed.read(envelope_path, 262144)
    with locked(root, anchor, expected) as (service, state, old):
        policy = managed.policy_file(Path(anchor), old["policy"])[1]
        value = verify(envelope, policy, policy, now)
        built, after, records = build(service, state, old, expected, value["action"], value["details"]["slot"], value["details"]["profile"], value["issued_at"], value["expires_at"])
        if review.encoded(value) != review.encoded(built):
            raise ValueError("Signed lifecycle differs from current state/profile/inventory")
        metadata = {"installation_before": base64.b64encode((service.root / "installation.json").read_bytes()).decode(),
                    "installation_after": base64.b64encode(review.encoded(after)).decode()}
        for key in ("authorization_before", "authorization_after"):
            metadata[key] = base64.b64encode((service.root / "authorizations/state.json").read_bytes()).decode()
        checkpoint_node = managed.node_for(value, envelope, old["archives"], metadata)
        checkpoint = review.hashed(checkpoint_node)
        plan = {"checkpoint": checkpoint, "previous": expected, "action": value["action"], "profile": value["details"]["profile"], "files": value["details"]["files"], "bytes": value["details"]["bytes"], "confirmation_required": value["action"] == "erase-data", "data_preserved": value["action"] != "erase-data", "trust_evidence_retained": True, "launch": False}
        result = {"review_sha256": review.hashed(plan), "plan": plan}
        if expected_review is None:
            return result
        if expected_review != result["review_sha256"] or (plan["confirmation_required"] and confirmation != ERASE):
            raise ValueError("Lifecycle review or exact erasure confirmation differs")
        if records:
            protected_retain(Path(anchor) / "lifecycle-inventories" / (value["details"]["inventory_sha256"] + ".bin"), review.encoded(records))
        protected_retain(Path(anchor) / "checkpoints" / (checkpoint + ".bin"), review.encoded(checkpoint_node))
        journal = {"format": 1, "kind": "inara-update-transaction", "checkpoint": checkpoint, "previous": expected, "root": str(service.root), "anchor": str(anchor), **metadata, "package": None}
        verify(envelope, policy, policy, now)
        managed.retain(service.root / "update-pending.json", review.encoded(journal))
        delete(service.root, records, value["action"])
        managed.commit(service.root, Path(anchor), checkpoint_node, checkpoint, journal)
        return {"applied": True, "checkpoint": checkpoint, "action": value["action"], "data_preserved": plan["data_preserved"], "trust_evidence_retained": True, "launched": False}


def protected_retain(path, raw):
    if len(raw) > managed.protection.MAX_BYTES - 65536:
        raise ValueError("Protected lifecycle evidence exceeds its bound")
    if path.exists():
        if managed.protection.open_sealed(backup.bounded_read(path, managed.protection.MAX_BYTES + 65536)) != raw:
            raise ValueError("Protected evidence conflicts")
    else:
        sealed = managed.protection.seal(raw)
        if managed.protection.open_sealed(sealed) != raw:
            raise ValueError("Lifecycle protection round trip failed")
        managed.retain(path, sealed)


def preflight(root, records, action, require_all=False):
    allowed = {"versions"} if action == "remove-software" else {"data", "recovery-profiles"}
    paths, seen, roots = [], set(), set()
    for entry in records:
        name = backup.path_name(entry["path"])
        if len(name.parts) < 2 or name.parts[0] not in allowed or name.as_posix().casefold() in seen:
            raise ValueError("Unsafe or duplicate removal path")
        seen.add(name.as_posix().casefold())
        (recovery.profile_id if name.parts[0] == "recovery-profiles" else signed.manager.identifier)(name.parts[1])
        path = signed.plain(root.joinpath(*name.parts))
        if not path.is_relative_to(root / name.parts[0]):
            raise ValueError("Removal escaped owned scope")
        directory = entry.get("directory") is True
        review.exact(entry, {"path", "directory"} if directory else {"path", "bytes", "sha256"})
        if require_all and not path.exists():
            raise ValueError("Removal already started; cancellation refused")
        if path.exists() and (not path.is_dir() if directory else not path.is_file() or path.stat().st_nlink != 1 or path.stat().st_size != entry["bytes"] or signed.digest_file(path) != entry["sha256"]):
            raise ValueError("Removal payload changed; preserve it")
        paths.append((path, directory))
        roots.add((name.parts[0], name.parts[1]))
    names = {entry["path"] for entry in records}
    for parent in allowed:
        directory = signed.plain(root / parent)
        if directory.exists() and any((parent, p.name) not in roots for p in directory.iterdir()):
            raise ValueError("Unknown owned root appeared; preserve it")
    if any((root / "transactions").iterdir()):
        raise ValueError("Unresolved version transaction")
    for parent, identifier in roots:
        target = signed.plain(root / parent / identifier)
        if target.exists():
            for folder, dirs, files in os.walk(target, followlinks=False):
                for name in dirs + files:
                    path = signed.plain(Path(folder) / name)
                    if path.relative_to(root).as_posix() not in names:
                        raise ValueError("Unknown file appeared; preserve it")
    return paths


def delete(root, records, action):
    if not records:
        return
    paths = preflight(root, records, action)
    by_name = {entry["path"]: entry for entry in records}
    for path, directory in paths:
        if not directory and path.exists():
            entry = by_name[path.relative_to(root).as_posix()]
            signed.plain(path)
            if path.stat().st_nlink != 1 or signed.digest_file(path) != entry["sha256"]:
                raise ValueError("Removal file changed before deletion")
            path.unlink()
    for path, directory in sorted(paths, key=lambda item: len(item[0].parts), reverse=True):
        if directory and path.exists():
            signed.plain(path).rmdir()


def recover(root, anchor, expected, previous, expected_review=None, cancel=False, confirmation=""):
    root, anchor = managed.separate(root, anchor)
    service = signed.manager.Installation(root, authenticated=True, pending_update=True)
    with service.locked() as state, managed.anchor_lock(anchor):
        journal, raw, node, value, before, after, hashes, _ = managed.pending(service, state, anchor, expected, previous)
        if value["kind"] != "inara-managed-lifecycle":
            raise ValueError("Not a lifecycle transaction")
        records = []
        digest = value["details"]["inventory_sha256"]
        if digest is not None:
            data = backup.bounded_read(anchor / "lifecycle-inventories" / (digest + ".bin"), managed.protection.MAX_BYTES + 65536)
            decoded = managed.protection.open_sealed(data)
            if trust.sha(decoded) != digest:
                raise ValueError("Protected removal inventory changed")
            records = json.loads(decoded, object_pairs_hook=trust.pairs)
            if not isinstance(records, list) or not 1 <= len(records) <= 100000:
                raise ValueError("Excessive removal inventory")
            preflight(root, records, value["action"], require_all=cancel)
        if cancel and hashes != (value["installation_before"], value["authorization_before"]):
            raise ValueError("Commit started; cancellation refused")
        if not cancel and value["action"] in {"activate-profile", "rollback-profile"}:
            selection, profile, binding = profile_change(service, before, value["action"], value["details"]["slot"], value["details"]["profile"])
            if selection != after["recovery"] or profile != value["details"]["profile"] or binding != value["details"]["binding_sha256"]:
                raise ValueError("Recovery profile changed during interruption")
        plan = {"checkpoint": expected, "previous": previous, "journal_sha256": trust.sha(raw), "installation_sha256": hashes[0], "authorization_sha256": hashes[1], "action": value["action"], "cancel": cancel, "files": value["details"]["files"], "confirmation_required": value["action"] == "erase-data" and not cancel, "trust_evidence_retained": True, "launch": False}
        result = {"plan": plan, "review_sha256": review.hashed(plan)}
        if expected_review is None:
            return result
        if expected_review != result["review_sha256"] or (plan["confirmation_required"] and confirmation != ERASE):
            raise ValueError("Recovery review or erasure phrase changed")
        if cancel:
            if signed.read(root / "update-pending.json", 262144)[1] != raw:
                raise ValueError("Journal changed")
            (root / "update-pending.json").unlink()
            return {"cancelled": True, "checkpoint": previous, "evidence_retained": True, "launched": False}
        delete(root, records, value["action"])
        managed.commit(root, anchor, node, expected, journal)
        return {"resumed": True, "checkpoint": expected, "evidence_retained": True, "launched": False}
