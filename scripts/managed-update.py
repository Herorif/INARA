"""Externally pinned protected checkpoints, dual-policy changes and retained-version updates."""

from contextlib import contextmanager
import base64
from datetime import timedelta
import json
import os
from pathlib import Path
import shutil
import uuid

# Resolve only the trusted controller's sibling modules.
import importlib.util

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(
        "managed_" + name, ROOT / "scripts" / (name + ".py")
    )
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


admission, protection = module("admission"), module("protected-state")
signed, trust, review = admission.signed, admission.trust, admission.review
DOMAIN = b"INARA:managed-change:v1\n"
ACTIONS = {"enroll", "renew", "rotate", "update", "rollback"}
FIELDS = {
    "format",
    "kind",
    "root",
    "installation",
    "anchor",
    "anchor_id",
    "action",
    "number",
    "previous_checkpoint",
    "previous_head",
    "before_floor",
    "target",
    "sequence",
    "policy_before",
    "windows_before",
    "policy_after",
    "windows_after",
    "source_policy",
    "grant_sha256",
    "installation_before",
    "authorization_before",
    "installation_after",
    "authorization_after",
    "archives_sha256",
    "issued_at",
    "expires_at",
}
NODE_FIELDS = {
    "format",
    "kind",
    "root",
    "installation",
    "anchor",
    "anchor_id",
    "number",
    "previous",
    "floor",
    "policy",
    "windows",
    "grant",
    "installation_sha256",
    "authorization_sha256",
    "archives",
    "change",
    "metadata",
}


def message(value):
    return DOMAIN + review.encoded(value)


def atomic(path, raw):
    path = signed.plain(path)
    signed.plain(path.parent, True)
    temporary = path.parent / (".write-" + uuid.uuid4().hex)
    with temporary.open("xb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def retain(path, raw):
    path = signed.plain(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.stat().st_size != len(raw) or path.read_bytes() != raw:
            raise ValueError("Retained evidence conflicts; preserve it")
    else:
        with path.open("xb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())


@contextmanager
def anchor_lock(anchor):
    if not anchor.exists():
        yield
        return
    import msvcrt

    path = signed.plain(anchor / ".anchor.lock")
    with path.open("a+b") as stream:
        if path.stat().st_size == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise ValueError("Trust anchor is busy") from error
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def external(path, roots):
    path = signed.plain(path)
    if any(path.is_relative_to(signed.plain(root)) for root in roots):
        raise ValueError("Keep inputs/requests outside installation and checkpoint roots")
    return path


def separate(root, anchor):
    root, anchor = signed.plain(root, True), signed.plain(anchor)
    if root.is_relative_to(anchor) or anchor.is_relative_to(root):
        raise ValueError("Choose a separate external checkpoint directory")
    return root, anchor


def policy_file(anchor, digest, windows=False):
    trust.digest(digest)
    path = signed.plain(anchor / "policies" / (digest + ".json"))
    value = admission.windows.policy(path, digest) if windows else trust.policy(path, digest)
    if value["mode"] != "production":
        raise ValueError("Managed trust requires production-purpose policies")
    return path, value


def roles(signatures, policy, value, now, domain=None):
    issued, expires = trust.stamp(value["issued_at"]), trust.stamp(value["expires_at"])
    if not isinstance(signatures, list) or not 1 <= len(signatures) <= 32:
        raise ValueError("Missing change signatures")
    keys, seen, counts = (
        {k["key_id"]: k for k in policy["keys"]},
        set(),
        {"publisher": 0, "reviewer": 0},
    )
    for signature in signatures:
        review.exact(signature, {"key_id", "signature"})
        key = keys.get(signature["key_id"])
        if key is None or key["state"] != "active" or key["key_id"] in seen:
            raise ValueError("Unknown, revoked or duplicate change signer")
        if (
            not trust.stamp(key["not_before"])
            <= issued
            <= now
            < expires
            <= trust.stamp(key["not_after"])
        ):
            raise ValueError("Change signer window invalid")
        try:
            admission.Ed25519PublicKey.from_public_bytes(trust.b64(key["public_key"], 32)).verify(
                trust.b64(signature["signature"], 64), message(value) if domain is None else domain + review.encoded(value)
            )
        except admission.InvalidSignature as error:
            raise ValueError("Change signature mismatch") from error
        counts[key["role"]] += 1
        seen.add(key["key_id"])
    if any(counts[role] < policy["thresholds"][role] for role in counts):
        raise ValueError("Change role threshold missing")


def verify_change(envelope, before, after, now=None):
    if isinstance(envelope, dict) and isinstance(envelope.get("statement"), dict) and envelope["statement"].get("kind") == "inara-managed-lifecycle":
        return module("managed-lifecycle").verify(envelope, before, after, now)
    review.exact(envelope, {"statement", "signatures_before", "signatures_after"})
    value = envelope["statement"]
    review.exact(value, FIELDS)
    if (
        type(value["format"]) is not int
        or value["format"] != 1
        or value["kind"] != "inara-managed-change"
        or value["action"] not in ACTIONS
    ):
        raise ValueError("Unsupported managed change")
    issued, expires, current = (
        trust.stamp(value["issued_at"]),
        trust.stamp(value["expires_at"]),
        trust.utc(now),
    )
    if not issued <= current < expires or not timedelta(0) < expires - issued <= timedelta(hours=1):
        raise ValueError("Change authorization expired or malformed")
    for key in ("number", "sequence", "before_floor"):
        trust.integer(value[key])
    if (value["action"] == "update" and value["sequence"] <= value["before_floor"]) or (
        value["action"] == "rollback" and value["sequence"] > value["before_floor"]
    ):
        raise ValueError("Update/rollback sequence rule violated")
    for key in (
        "policy_before",
        "windows_before",
        "policy_after",
        "windows_after",
        "source_policy",
        "grant_sha256",
        "installation_before",
        "authorization_before",
        "installation_after",
        "authorization_after",
        "archives_sha256",
        "previous_head",
        "target",
    ):
        trust.digest(value[key])
    if value["previous_checkpoint"] != "new":
        trust.digest(value["previous_checkpoint"])
    if before["mode"] != "production" or after["mode"] != "production":
        raise ValueError("Fixture and disabled change trust refused")
    if (
        before["publisher"] != after["publisher"]
        or before["channel"] != after["channel"]
        or after["minimum_sequence"] < before["minimum_sequence"]
        or (
            value["policy_before"] != value["policy_after"]
            and after["policy_sequence"] != before["policy_sequence"] + 1
        )
    ):
        raise ValueError("Unreviewed publisher/channel or policy sequence transition")
    roles(envelope["signatures_before"], before, value, current)
    roles(envelope["signatures_after"], after, value, current)
    return value


def read_node(root, anchor, expected):
    trust.digest(expected)
    path = signed.plain(anchor / "checkpoints" / (expected + ".bin"))
    if path.stat().st_size > protection.MAX_BYTES:
        raise ValueError("Oversized checkpoint")
    raw = protection.open_sealed(path.read_bytes())
    if trust.sha(raw) != expected:
        raise ValueError("Checkpoint differs from independently retained pin")
    node = json.loads(raw, object_pairs_hook=trust.pairs)
    review.exact(node, NODE_FIELDS)
    trust.integer(node["number"])
    trust.integer(node["floor"])
    value = node["change"]["statement"]
    if (
        type(node["format"]) is not int
        or node["format"] != 1
        or node["kind"] != "inara-managed-checkpoint"
        or node["root"] != str(root)
        or node["anchor"] != str(anchor)
        or node["installation"] != value["installation"]
        or node["anchor_id"] != value["anchor_id"]
        or value["root"] != str(root)
        or value["anchor"] != str(anchor)
    ):
        raise ValueError("Checkpoint belongs to another root/account/anchor")
    before = policy_file(anchor, value["policy_before"])[1]
    after = policy_file(anchor, value["policy_after"])[1]
    verify_change(node["change"], before, after, trust.stamp(value["issued_at"]))
    review.exact(
        node["metadata"],
        {
            "installation_before",
            "authorization_before",
            "installation_after",
            "authorization_after",
        },
    )
    if any(
        trust.sha(base64.b64decode(raw, validate=True)) != value[key]
        for key, raw in node["metadata"].items()
    ):
        raise ValueError("Protected metadata images differ from signed transition")
    archives(node["archives"])
    if (
        review.hashed(node["archives"]) != value["archives_sha256"]
        or node["floor"] != max(value["before_floor"], value["sequence"])
        or any(
            node[key] != value[field]
            for key, field in {
                "number": "number",
                "previous": "previous_checkpoint",
                "policy": "policy_after",
                "windows": "windows_after",
                "grant": "grant_sha256",
                "installation_sha256": "installation_after",
                "authorization_sha256": "authorization_after",
            }.items()
        )
    ):
        raise ValueError("Checkpoint and signed change differ")
    for digest in (value["policy_before"], value["policy_after"], value["source_policy"]):
        if digest not in node["archives"]["release"]:
            raise ValueError("Missing historical source policy")
    for digest in (value["windows_before"], value["windows_after"]):
        if digest not in node["archives"]["windows"]:
            raise ValueError("Missing historical native policy")
    return node


def archives(value):
    review.exact(value, {"release", "windows"})
    for items in value.values():
        if not isinstance(items, list) or not 1 <= len(items) <= 64 or items != sorted(set(items)):
            raise ValueError("Missing, duplicate or excessive policy history")
        for digest in items:
            trust.digest(digest)


def pointer(node, digest):
    return {
        "format": 1,
        "kind": "inara-checkpoint-head",
        "root": node["root"],
        "installation": node["installation"],
        "anchor_id": node["anchor_id"],
        "checkpoint": digest,
    }


def context(service, state, anchor, expected, expected_head):
    if expected == "new":
        if state["format"] == 3 or anchor.exists():
            raise ValueError("Enrollment needs an unmanaged root and NEW external anchor")
        old = None
    else:
        old = read_node(service.root, anchor, expected)
        if (
            state["format"] != 3
            or state["security"] != {"format": 1, "anchor": str(anchor), "id": old["anchor_id"]}
            or state["id"] != old["installation"]
            or signed.digest_file(service.root / "installation.json") != old["installation_sha256"]
            or signed.digest_file(service.root / "authorizations/state.json")
            != old["authorization_sha256"]
            or old["grant"] != expected_head
        ):
            raise ValueError("Managed state changed or stale external pin supplied")
        actual, _ = signed.read(anchor / "head.json", 16384)
        if review.encoded(actual) != review.encoded(pointer(old, expected)):
            raise ValueError("Protected checkpoint pointer changed")
    previous = admission.head(service, state, expected_head)
    if previous is None:
        raise ValueError("Admit an initial signed launch grant before managed enrollment")
    return old, previous


def inputs(
    root,
    anchor,
    expected,
    expected_head,
    policy,
    policy_pin,
    windows,
    windows_pin,
    next_policy=None,
    next_pin=None,
    next_windows=None,
    next_windows_pin=None,
):
    root, anchor = separate(root, anchor)
    records = {}
    for path, pin, native in (
        (policy, policy_pin, False),
        (windows, windows_pin, True),
        (next_policy or policy, next_pin or policy_pin, False),
        (next_windows or windows, next_windows_pin or windows_pin, True),
    ):
        path = external(path, [root, anchor])
        value = admission.windows.policy(path, pin) if native else trust.policy(path, pin)
        if value["mode"] != "production":
            raise ValueError("Owned production-purpose trust must be configured")
        records[pin] = (path, value)
    before, after = records[policy_pin][1], records[next_pin or policy_pin][1]
    if (
        before["publisher"] != after["publisher"]
        or before["channel"] != after["channel"]
        or after["minimum_sequence"] < before["minimum_sequence"]
        or (
            (next_pin or policy_pin) != policy_pin
            and after["policy_sequence"] != before["policy_sequence"] + 1
        )
    ):
        raise ValueError("Invalid trust policy rotation")
    return {
        "root": root,
        "anchor": anchor,
        "expected": expected,
        "head": expected_head,
        "policy": policy_pin,
        "windows": windows_pin,
        "next_policy": next_pin or policy_pin,
        "next_windows": next_windows_pin or windows_pin,
        "records": records,
    }


def source_material(service, state, cfg, old, target, sequence, package=None, grant=None):
    signed.manager.identifier(target)
    trust.integer(sequence)
    if package is not None:
        if target in state["slots"]:
            raise ValueError("Registered versions use retained evidence, not replacement packages")
        package = external(package, [service.root, cfg["anchor"]])
        manifest, _ = signed.read(package / signed.MANIFEST)
    else:
        if target not in state["slots"]:
            raise ValueError("An unregistered target requires an authenticated package")
        manifest, _ = signed.read(service.root / "admissions" / target / signed.MANIFEST)
    source_pin = manifest["policy_sha256"]
    known = {cfg["policy"], cfg["next_policy"]} | (
        set() if old is None else set(old["archives"]["release"])
    )
    if source_pin not in known:
        raise ValueError("Source package policy is outside authorized policy history")
    source_path = (
        cfg["records"][source_pin][0]
        if source_pin in cfg["records"]
        else policy_file(cfg["anchor"], source_pin)[0]
    )
    if package is not None:
        verified = signed.verify(
            package, source_path, source_pin, sequence, now=trust.stamp(manifest["issued_at"])
        )
        if manifest["candidate_manifest_sha256"] != target:
            raise ValueError("Package belongs to another slot")
        data = signed.plain(service.root / "data" / target)
        if data.exists():
            service.profile_data(state, target)
        directory = package / "payload"
        core = signed.manager.package.verify(directory)
        if core["kind"] != "desktop-core-pilot" or not core["self_contained"]:
            raise ValueError("Managed updates require an isolated core payload")
    else:
        projected = {**state, "current": target}
        projected_grant = None if grant is None else {**grant, "policy_sha256": source_pin}
        verified, directory, data = admission.source(
            service, projected, source_path, source_pin, sequence, projected_grant
        )
    if grant is not None and any(
        grant[key] != verified[key] for key in ("manifest_sha256", "attestation_sha256")
    ):
        raise ValueError("Signed target grant differs from source evidence")
    return {
        "verified": verified,
        "directory": directory,
        "data": data,
        "source_pin": source_pin,
        "source_path": source_path,
        "package": package,
        "manifest": manifest,
    }


def grant_request(cfg, action, target, sequence, output, package=None, hours=24, now=None):
    service = signed.manager.Installation(cfg["root"], authenticated=True)
    output = external(output, [cfg["root"], cfg["anchor"]])
    if output.exists():
        raise ValueError("Choose a NEW signing-request directory")
    trust.integer(hours, 1, 720)
    with service.locked() as state, anchor_lock(cfg["anchor"]):
        old, previous = context(service, state, cfg["anchor"], cfg["expected"], cfg["head"])
        check_context(cfg, old, previous)
        material = source_material(service, state, cfg, old, target, sequence, package)
        current = trust.utc(now)
        value = {
            "format": 1,
            "kind": "inara-installation-launch-grant",
            "root": str(service.root),
            "installation": state["id"],
            "slot": target,
            "manifest_sha256": material["verified"]["manifest_sha256"],
            "attestation_sha256": material["verified"]["attestation_sha256"],
            "policy_sha256": cfg["next_policy"],
            "windows_policy_sha256": cfg["next_windows"],
            "sequence": sequence,
            "number": previous["statement"]["number"] + 1,
            "previous": cfg["head"],
            "issued_at": current.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expires_at": (current + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        trust.integer(value["number"])
        rules(action, state, old, previous, cfg, value)
        policy = cfg["records"][cfg["next_policy"]][1]
        if any(
            sum(
                k["state"] == "active"
                and k["role"] == role
                and trust.stamp(k["not_before"]) <= current
                and trust.stamp(value["expires_at"]) <= trust.stamp(k["not_after"])
                for k in policy["keys"]
            )
            < policy["thresholds"][role]
            for role in policy["thresholds"]
        ):
            raise ValueError("New grant window exceeds enrolled keys")
        output.mkdir(parents=True)
        (output / "statement.json").write_bytes(review.encoded(value))
        (output / "signing-message.bin").write_bytes(admission.message(value))
    return {"prepared": True, "signed": False, "launched": False}


def check_context(cfg, old, previous):
    if old is not None and (old["policy"] != cfg["policy"] or old["windows"] != cfg["windows"]):
        raise ValueError("Supplied old trust differs from protected checkpoint")
    value = previous["statement"]
    admission.verify_grant(
        previous,
        cfg["records"][cfg["policy"]][1],
        cfg["policy"],
        cfg["windows"],
        trust.stamp(value["issued_at"]),
    )


def rules(action, state, old, previous, cfg, value):
    if action not in ACTIONS or (action == "enroll") != (old is None):
        raise ValueError("Invalid enrollment/change action")
    current = previous["statement"]
    changed = cfg["policy"] != cfg["next_policy"] or cfg["windows"] != cfg["next_windows"]
    if (
        value["root"] != str(cfg["root"])
        or value["installation"] != state["id"]
        or value["previous"] != cfg["head"]
        or value["number"] != current["number"] + 1
    ):
        raise ValueError("Grant/root/previous-number binding differs")
    floor = current["sequence"] if old is None else old["floor"]
    if action in {"enroll", "renew", "rotate"}:
        if (
            value["slot"] != state["current"]
            or value["sequence"] != current["sequence"]
            or any(value[key] != current[key] for key in ("manifest_sha256", "attestation_sha256"))
        ):
            raise ValueError("A trust/renewal change cannot replace application bytes")
        if (action == "rotate") != changed:
            raise ValueError("Trust changes require the explicit rotate action")
    elif action == "update":
        if value["slot"] == state["current"] or value["sequence"] <= floor:
            raise ValueError("An update requires a new slot above the retained sequence floor")
    elif (
        value["slot"] == state["current"]
        or value["slot"] not in state["slots"]
        or value["sequence"] > floor
    ):
        raise ValueError("Rollback requires an explicitly retained older target")


def build(service, state, cfg, action, grant_path, package, issued, expires, now, native_check):
    old, previous = context(service, state, cfg["anchor"], cfg["expected"], cfg["head"])
    check_context(cfg, old, previous)
    grant_path = external(grant_path, [service.root, cfg["anchor"]])
    envelope, grant_raw = signed.read(grant_path, 262144)
    grant = admission.verify_grant(
        envelope,
        cfg["records"][cfg["next_policy"]][1],
        cfg["next_policy"],
        cfg["next_windows"],
        now,
    )
    rules(action, state, old, previous, cfg, grant)
    if grant["slot"] not in state["slots"] and len(state["slots"]) >= 16:
        raise ValueError("Managed version limit reached; preserve installed versions")
    material = source_material(
        service, state, cfg, old, grant["slot"], grant["sequence"], package, grant
    )
    native_check(material["directory"], cfg["records"][cfg["next_windows"]][0], cfg["next_windows"])
    after = json.loads(review.encoded(state))
    after.update(format=3, kind="authenticated-pilot-slots", generation=state["generation"] + 1)
    anchor_id = (
        review.hashed(
            {"root": str(service.root), "installation": state["id"], "anchor": str(cfg["anchor"])}
        )[:32]
        if old is None
        else old["anchor_id"]
    )
    after["security"] = {"format": 1, "anchor": str(cfg["anchor"]), "id": anchor_id}
    after["recovery"] = service.selections(state)
    after["slots"][grant["slot"]] = {"manifest_sha256": grant["slot"]}
    if grant["slot"] != state["current"]:
        after["previous"], after["current"] = state["current"], grant["slot"]
    grant_sha = trust.sha(grant_raw)
    authorization = {
        "format": 1,
        "kind": "inara-authorization-head",
        "installation": state["id"],
        "grant_sha256": grant_sha,
        "number": grant["number"],
        "sequence": grant["sequence"],
    }
    history = {
        "release": sorted(
            set(() if old is None else old["archives"]["release"])
            | {cfg["policy"], cfg["next_policy"], material["source_pin"]}
        ),
        "windows": sorted(
            set(() if old is None else old["archives"]["windows"])
            | {cfg["windows"], cfg["next_windows"]}
        ),
    }
    archives(history)
    value = {
        "format": 1,
        "kind": "inara-managed-change",
        "root": str(service.root),
        "installation": state["id"],
        "anchor": str(cfg["anchor"]),
        "anchor_id": anchor_id,
        "action": action,
        "number": 1 if old is None else old["number"] + 1,
        "previous_checkpoint": cfg["expected"],
        "previous_head": cfg["head"],
        "before_floor": previous["statement"]["sequence"] if old is None else old["floor"],
        "target": grant["slot"],
        "sequence": grant["sequence"],
        "policy_before": cfg["policy"],
        "windows_before": cfg["windows"],
        "policy_after": cfg["next_policy"],
        "windows_after": cfg["next_windows"],
        "source_policy": material["source_pin"],
        "grant_sha256": grant_sha,
        "installation_before": signed.digest_file(service.root / "installation.json"),
        "authorization_before": signed.digest_file(service.root / "authorizations/state.json"),
        "installation_after": review.hashed(after),
        "authorization_after": review.hashed(authorization),
        "archives_sha256": review.hashed(history),
        "issued_at": issued,
        "expires_at": expires,
    }
    return value, after, authorization, history, grant_raw, material


def prepare(cfg, action, grant, output, package=None, minutes=30, now=None, *, _native_check=None):
    output = external(output, [cfg["root"], cfg["anchor"]])
    trust.integer(minutes, 1, 60)
    if output.exists():
        raise ValueError("Choose a NEW change-request directory")
    service = signed.manager.Installation(cfg["root"], authenticated=True)
    current = trust.utc(now)
    with service.locked() as state, anchor_lock(cfg["anchor"]):
        value = build(
            service,
            state,
            cfg,
            action,
            grant,
            package,
            current.strftime("%Y-%m-%dT%H:%M:%SZ"),
            (current + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            now,
            admission.windows.check if _native_check is None else _native_check,
        )[0]
        output.mkdir(parents=True)
        (output / "statement.json").write_bytes(review.encoded(value))
        (output / "signing-message.bin").write_bytes(message(value))
    return {"prepared": True, "signed": False, "selected": False, "launched": False}


def node_for(value, envelope, history, metadata):
    return {
        "format": 1,
        "kind": "inara-managed-checkpoint",
        "root": value["root"],
        "installation": value["installation"],
        "anchor": value["anchor"],
        "anchor_id": value["anchor_id"],
        "number": value["number"],
        "previous": value["previous_checkpoint"],
        "floor": max(value["before_floor"], value["sequence"]),
        "policy": value["policy_after"],
        "windows": value["windows_after"],
        "grant": value["grant_sha256"],
        "installation_sha256": value["installation_after"],
        "authorization_sha256": value["authorization_after"],
        "archives": history,
        "change": envelope,
        "metadata": metadata,
    }


def change(
    cfg,
    action,
    grant_path,
    change_path,
    package=None,
    expected_review=None,
    now=None,
    *,
    _native_check=None,
):
    service = signed.manager.Installation(cfg["root"], authenticated=True)
    change_path = external(change_path, [cfg["root"], cfg["anchor"]])
    envelope, raw = signed.read(change_path, 262144)
    value = verify_change(
        envelope, cfg["records"][cfg["policy"]][1], cfg["records"][cfg["next_policy"]][1], now
    )
    with service.locked() as state, anchor_lock(cfg["anchor"]):
        built, after, authorization, history, grant_raw, material = build(
            service,
            state,
            cfg,
            action,
            grant_path,
            package,
            value["issued_at"],
            value["expires_at"],
            now,
            admission.windows.check if _native_check is None else _native_check,
        )
        if review.encoded(built) != review.encoded(value):
            raise ValueError("Signed change does not match current inputs/state")
        metadata = {
            "installation_before": base64.b64encode(
                (service.root / "installation.json").read_bytes()
            ).decode(),
            "authorization_before": base64.b64encode(
                (service.root / "authorizations/state.json").read_bytes()
            ).decode(),
            "installation_after": base64.b64encode(review.encoded(after)).decode(),
            "authorization_after": base64.b64encode(review.encoded(authorization)).decode(),
        }
        if any(
            trust.sha(base64.b64decode(raw, validate=True)) != value[key]
            for key, raw in metadata.items()
        ):
            raise ValueError("Metadata changed while preparing checkpoint")
        node = node_for(value, envelope, history, metadata)
        checkpoint = review.hashed(node)
        plan = {
            "change_sha256": trust.sha(raw),
            "checkpoint": checkpoint,
            "previous": cfg["expected"],
            "package": None if material["package"] is None else str(material["package"]),
            "profile": str(material["data"]),
            "select": after["current"],
            "launch": False,
        }
        reviewed = {"review_sha256": review.hashed(plan), "plan": plan}
        if expected_review is None:
            return reviewed
        if expected_review != reviewed["review_sha256"]:
            raise ValueError("Managed change review changed")
        verify_change(
            envelope, cfg["records"][cfg["policy"]][1], cfg["records"][cfg["next_policy"]][1], now
        )
        snapshots = {}
        for pin, (path, _) in cfg["records"].items():
            policy_raw = signed.read(path, 262144)[1]
            if trust.sha(policy_raw) != pin:
                raise ValueError("External trust changed after review")
            snapshots[pin] = policy_raw
        anchor = cfg["anchor"]
        if not anchor.exists():
            anchor.mkdir(parents=True)
        for pin, policy_raw in snapshots.items():
            retain(anchor / "policies" / (pin + ".json"), policy_raw)
        sealed = protection.seal(review.encoded(node))
        if protection.open_sealed(sealed) != review.encoded(node):
            raise ValueError("Checkpoint protection round trip failed")
        checkpoint_path = anchor / "checkpoints" / (checkpoint + ".bin")
        if checkpoint_path.exists():
            if protection.open_sealed(checkpoint_path.read_bytes()) != review.encoded(node):
                raise ValueError("Retained checkpoint conflicts")
        else:
            retain(checkpoint_path, sealed)
        retain(service.root / "authorizations" / (value["grant_sha256"] + ".json"), grant_raw)
        journal = {
            "format": 1,
            "kind": "inara-update-transaction",
            "checkpoint": checkpoint,
            "previous": cfg["expected"],
            "root": str(service.root),
            "anchor": str(anchor),
            **metadata,
            "package": plan["package"],
        }
        retain(service.root / "update-pending.json", review.encoded(journal))
        stage(service, after, value, material)
        verify_change(
            envelope, cfg["records"][cfg["policy"]][1], cfg["records"][cfg["next_policy"]][1], now
        )
        admission.verify_grant(
            json.loads(grant_raw),
            cfg["records"][cfg["next_policy"]][1],
            cfg["next_policy"],
            cfg["next_windows"],
            now,
        )
        commit(service.root, anchor, node, checkpoint, journal)
        return {
            "applied": True,
            "checkpoint": checkpoint,
            "action": action,
            "selected": after["current"],
            "previous_versions_retained": True,
            "data_migrated": False,
            "launched": False,
            "release_authorized": False,
        }


def stage(service, after, value, material):
    slot, package = value["target"], material["package"]
    if package is not None:
        target, pending = service.root / "versions" / slot, service.root / "transactions" / slot
        if target.exists() and pending.exists():
            raise ValueError("Ambiguous staged update; preserve both copies")
        if not target.exists():
            if not pending.exists():
                shutil.copytree(package / "payload", pending, symlinks=True)
            records = {
                name.removeprefix("payload/"): entry
                for name, entry in signed.inventory(material["manifest"]["files"]).items()
                if name.startswith("payload/")
            }
            actual = {
                p.relative_to(pending).as_posix() for p in signed.audit.package.files_in(pending)
            }
            if actual != set(records) or any(
                signed.digest_file(pending / name) != entry["sha256"]
                for name, entry in records.items()
            ):
                raise ValueError("Partial or changed update copy; preserve it")
            service.check(slot, pending)
            os.rename(pending, target)
        signed.retain_admission(
            package,
            service,
            after,
            slot,
            target,
            material["source_path"],
            material["source_pin"],
            value["sequence"],
            trust.stamp(material["manifest"]["issued_at"]),
            {
                "manifest_sha256": material["verified"]["manifest_sha256"],
                "attestation_sha256": material["verified"]["attestation_sha256"],
            },
        )
    service.check(slot)
    # Creates only our missing marker, or validates an existing original/recovery profile.
    service.data(after, slot, create=True)


def commit(root, anchor, node, checkpoint, journal):
    atomic(
        root / "installation.json", base64.b64decode(journal["installation_after"], validate=True)
    )
    atomic(
        root / "authorizations/state.json",
        base64.b64decode(journal["authorization_after"], validate=True),
    )
    atomic(anchor / "head.json", review.encoded(pointer(node, checkpoint)))
    path = signed.plain(root / "update-pending.json")
    if signed.read(path, 262144)[1] != review.encoded(journal):
        raise ValueError("Transaction journal changed; preserve it")
    path.unlink()  # Only this exact committed journal. No version/profile deletion.


def pending(service, current, anchor, expected, previous):
    root = service.root
    journal, raw = signed.read(root / "update-pending.json", 262144)
    review.exact(
        journal,
        {
            "format",
            "kind",
            "checkpoint",
            "previous",
            "root",
            "anchor",
            "installation_before",
            "authorization_before",
            "installation_after",
            "authorization_after",
            "package",
        },
    )
    if (
        type(journal["format"]) is not int
        or journal["format"] != 1
        or journal["kind"] != "inara-update-transaction"
        or journal["root"] != str(root)
        or journal["anchor"] != str(anchor)
        or journal["checkpoint"] != expected
        or journal["previous"] != previous
    ):
        raise ValueError("Recovery requires exact externally retained old/new checkpoint pins")
    node = read_node(root, anchor, expected)
    value = node["change"]["statement"]
    blobs = {
        key: base64.b64decode(journal[key], validate=True)
        for key in (
            "installation_before",
            "authorization_before",
            "installation_after",
            "authorization_after",
        )
    }
    if any(trust.sha(blobs[key]) != value[key] for key in blobs):
        raise ValueError("Journal bytes differ from signed transition")
    before, after = (
        json.loads(blobs[key], object_pairs_hook=trust.pairs)
        for key in ("installation_before", "installation_after")
    )
    if current["id"] != node["installation"] or value["previous_checkpoint"] != previous:
        raise ValueError("Recovery installation/checkpoint binding changed")
    hashes = (
        signed.digest_file(root / "installation.json"),
        signed.digest_file(root / "authorizations/state.json"),
    )
    pairs = [
        (value["installation_before"], value["authorization_before"]),
        (value["installation_after"], value["authorization_before"]),
        (value["installation_after"], value["authorization_after"]),
    ]
    if hashes not in pairs:
        raise ValueError("Unknown partial metadata; preserve it")
    head_path = anchor / "head.json"
    if head_path.exists():
        actual, _ = signed.read(head_path, 16384)
        wanted = pointer(node, expected)
        if review.encoded(actual) == review.encoded(wanted) and hashes != pairs[2]:
            raise ValueError("Anchor advanced before installation metadata; preserve it")
        if previous != "new":
            old = read_node(root, anchor, previous)
            if review.encoded(actual) not in (
                review.encoded(wanted),
                review.encoded(pointer(old, previous)),
            ):
                raise ValueError("Recovery anchor pointer changed")
        elif review.encoded(actual) != review.encoded(wanted):
            raise ValueError("Foreign anchor pointer")
    elif previous != "new":
        raise ValueError("Prior anchor pointer is missing")
    return journal, raw, node, value, before, after, hashes, head_path


def resume(root, anchor, expected, previous, expected_review=None, now=None, *, _native_check=None, confirmation=""):
    if read_node(*separate(root, anchor), expected)["change"]["statement"]["kind"] == "inara-managed-lifecycle":
        return module("managed-lifecycle").recover(root, anchor, expected, previous, expected_review, confirmation=confirmation)
    root, anchor = separate(root, anchor)
    service = signed.manager.Installation(root, authenticated=True, pending_update=True)
    with service.locked() as current, anchor_lock(anchor):
        journal, raw, node, value, before, after, hashes, head_path = pending(
            service, current, anchor, expected, previous
        )
        cfg = {
            "root": root,
            "anchor": anchor,
            "policy": value["policy_before"],
            "windows": value["windows_before"],
            "next_policy": node["policy"],
            "next_windows": node["windows"],
            "records": {},
        }
        for digest in node["archives"]["release"]:
            cfg["records"][digest] = policy_file(anchor, digest)
        for digest in node["archives"]["windows"]:
            cfg["records"][digest] = policy_file(anchor, digest, True)
        grant_envelope, grant_raw = signed.read(
            root / "authorizations" / (node["grant"] + ".json"), 262144
        )
        if trust.sha(grant_raw) != node["grant"]:
            raise ValueError("Retained target grant bytes changed")
        grant = admission.verify_grant(
            grant_envelope, cfg["records"][node["policy"]][1], node["policy"], node["windows"], now
        )
        if grant["slot"] != value["target"] or grant["sequence"] != value["sequence"]:
            raise ValueError("Recovery launch grant differs")
        material = source_material(
            service,
            before,
            cfg,
            node,
            value["target"],
            value["sequence"],
            journal["package"],
            grant,
        )
        (admission.windows.check if _native_check is None else _native_check)(
            material["directory"], cfg["records"][node["windows"]][0], node["windows"]
        )
        plan = {
            "journal_sha256": trust.sha(raw),
            "checkpoint": expected,
            "previous": previous,
            "installation_sha256": hashes[0],
            "authorization_sha256": hashes[1],
            "anchor_head_sha256": None if not head_path.exists() else signed.digest_file(head_path),
            "launch": False,
        }
        reviewed = {"review_sha256": review.hashed(plan), "plan": plan}
        if expected_review is None:
            return reviewed
        if expected_review != reviewed["review_sha256"]:
            raise ValueError("Recovery review changed")
        stage(service, after, value, material)
        commit(root, anchor, node, expected, journal)
        return {
            "resumed": True,
            "checkpoint": expected,
            "selected": after["current"],
            "launched": False,
        }


def abort(root, anchor, expected, previous, expected_review=None):
    """Cancel only a prepared change whose three committed metadata files are untouched."""
    root, anchor = separate(root, anchor)
    if read_node(root, anchor, expected)["change"]["statement"]["kind"] == "inara-managed-lifecycle":
        return module("managed-lifecycle").recover(root, anchor, expected, previous, expected_review, cancel=True)
    service = signed.manager.Installation(root, authenticated=True, pending_update=True)
    with service.locked() as state, anchor_lock(anchor):
        journal, raw, node, value, before, after, hashes, head_path = pending(
            service, state, anchor, expected, previous
        )
        if hashes != (value["installation_before"], value["authorization_before"]):
            raise ValueError("Metadata commit started; use reviewed resume, not cancellation")
        if previous != "new":
            old = read_node(root, anchor, previous)
            if hashes != (old["installation_sha256"], old["authorization_sha256"]):
                raise ValueError("Original committed state differs")
        plan = {
            "journal_sha256": trust.sha(raw),
            "checkpoint": expected,
            "previous": previous,
            "installation_sha256": hashes[0],
            "authorization_sha256": hashes[1],
            "anchor_head_sha256": None if not head_path.exists() else signed.digest_file(head_path),
            "copies_retained": True,
            "launch": False,
        }
        reviewed = {"review_sha256": review.hashed(plan), "plan": plan}
        if expected_review is None:
            return reviewed
        if expected_review != reviewed["review_sha256"]:
            raise ValueError("Cancellation review changed")
        path = signed.plain(root / "update-pending.json")
        if signed.read(path, 262144)[1] != raw:
            raise ValueError("Cancellation journal changed")
        path.unlink()
        return {
            "cancelled": True,
            "checkpoint": previous,
            "copies_retained": True,
            "selected": state["current"],
            "launched": False,
            "release_authorized": False,
        }


def status(root, anchor, expected):
    root, anchor = separate(root, anchor)
    service = signed.manager.Installation(root, authenticated=True)
    with service.locked() as state, anchor_lock(anchor):
        node = read_node(root, anchor, expected)
        context(service, state, anchor, expected, node["grant"])
        return {
            "checkpoint": expected,
            "number": node["number"],
            "sequence_floor": node["floor"],
            "selected": state["current"],
            "grant": node["grant"],
            "policy": node["policy"],
            "windows_policy": node["windows"],
            "launched": False,
            "release_authorized": False,
        }


def launch(root, anchor, expected, resident_only=False, now=None, *, _native_check=None, _run=None):
    root, anchor = separate(root, anchor)
    service = signed.manager.Installation(root, authenticated=True)
    with service.locked() as state, anchor_lock(anchor):
        node = read_node(root, anchor, expected)
        context(service, state, anchor, expected, node["grant"])
        policy_path, policy = policy_file(anchor, node["policy"])
        windows_path, _ = policy_file(anchor, node["windows"], True)
        envelope = admission.head(service, state, node["grant"])
        grant = admission.verify_grant(envelope, policy, node["policy"], node["windows"], now)
        if grant["slot"] != state["current"]:
            raise ValueError("Managed selection differs from signed grant")
        target, capsule = root / "versions" / grant["slot"], root / "admissions" / grant["slot"]
        profile = service.data(state, grant["slot"])
        paths = list(signed.audit.package.files_in(target)) + list(
            signed.audit.package.files_in(capsule)
        )
        paths += list(signed.audit.package.files_in(anchor / "policies"))
        paths += [
            root / "installation.json",
            root / "authorizations/state.json",
            root / "authorizations" / (node["grant"] + ".json"),
            root / "admissions" / (grant["slot"] + ".json"),
            profile / ".inara-data.json",
            anchor / "head.json",
            anchor / "checkpoints" / (expected + ".bin"),
        ]
        if (profile / ".inara-recovery.json").exists():
            paths += [
                profile / ".inara-recovery.json",
                profile / "desktop-profile/resident-identity.json",
            ]
        with admission.launcher.file_leases(paths):
            if review.encoded(service.load()) != review.encoded(state):
                raise ValueError("Selection changed before file leases")
            fresh = read_node(root, anchor, expected)
            context(service, state, anchor, expected, fresh["grant"])
            grant = admission.verify_grant(
                admission.head(service, state, node["grant"]),
                policy,
                node["policy"],
                node["windows"],
                now,
            )
            source_pin = node["change"]["statement"]["source_policy"]
            source_path, _ = policy_file(anchor, source_pin)
            admission.source(
                service,
                state,
                source_path,
                source_pin,
                grant["sequence"],
                {**grant, "policy_sha256": source_pin},
            )
            (admission.windows.check if _native_check is None else _native_check)(
                target, windows_path, node["windows"]
            )
            args = ["-I", "-B", str(target / "backend/resident_main.py")] + (
                ["--resident-only"] if resident_only else []
            )
            result = (admission.launcher.run if _run is None else _run)(
                target / "runtime/python/python.exe",
                args,
                target,
                admission.launcher.environment(profile),
                trust.stamp(grant["expires_at"]),
            )
        return {**result, "launched": True, "checkpoint": expected, "release_authorized": False}
