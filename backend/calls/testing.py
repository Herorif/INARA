"""Controlled-test workflow; physical evidence can only come from a backend collector.

No collector is installed here. Profile JSON and renderer checkboxes are not
physical verification. Root policy remains disabled until a later owned session.
"""

from dataclasses import dataclass
import hashlib
import importlib.util
import json
from pathlib import Path
import time
import uuid

from calls.contracts import BridgeProfile
from calls.test_contracts import ControlledTestState, TestReview
from services.tools import ServiceError

ROOT = Path(__file__).resolve().parents[2]
CHECKS = frozenset({"controls", "receive", "transmit", "isolation", "stop", "disconnect"})
SOURCE_FILES = ("backend/calls/testing.py", "backend/calls/test_contracts.py", "backend/transport/call_testing.py",
                "config/call-test-policy.json", "backend/services/resources.py", "backend/services/capability_profiles.py",
                "backend/calls/contracts.py", "backend/calls/control.py",
                "backend/calls/audio.py", "backend/calls/session.py", "backend/calls/admission.py",
                "backend/calls/supervisor.py", "backend/calls/local_voice.py", "backend/workers/call_bridge_worker.py")


def digest(path):
    if path.resolve() != path or not path.is_file() or path.stat().st_size > 4_194_304:
        raise ValueError("Missing or linked controlled-test input")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_digest():
    return hashlib.sha256(json.dumps({name: digest(ROOT / name) for name in SOURCE_FILES}, sort_keys=True).encode()).hexdigest()


def profile_digest(profile):
    return hashlib.sha256(profile.model_dump_json().encode()).hexdigest()


@dataclass(frozen=True)
class CapturedEvidence:
    """Backend collector output, not a network/import schema or hardware attestation."""
    capture_id: str
    owner_project_scope: str
    revision: str
    profile_sha256: str
    source_sha256: str
    helper_sha256: str
    issued: float
    expires: float
    checks: frozenset[str]


class ControlledCalls:
    kind = "controlled_call_draft_v1"

    def __init__(self, app, clock=time.monotonic):
        self.app, self.clock = app, clock
        self.collector = None  # Later physical capture integration, never set by RPC/config JSON.
        self.reviews = {}

    def context(self, sid):
        return self.app.call_admission.context(sid)

    def invalidate(self, sid=None):
        self.reviews = {key: value for key, value in self.reviews.items()
                        if sid is not None and value["sid"] != sid}

    def policy(self):
        try:
            path = ROOT / "config/call-test-policy.json"
            if path.resolve() != path or path.stat().st_size > 4096:
                raise ValueError("Invalid policy path")
            value = json.loads(path.read_text())
            if (set(value) != {"format", "enabled", "channels"} or type(value["format"]) is not int or value["format"] != 1
                    or type(value["enabled"]) is not bool or not isinstance(value["channels"], list)
                    or len(value["channels"]) > 2 or not set(value["channels"]) <= {"sim", "whatsapp_personal"}):
                raise ValueError("Invalid policy")
            return value
        except (OSError, ValueError, KeyError, TypeError):
            return {"enabled": False, "channels": []}

    def load(self, owner, project):
        with self.app.database.connection() as db:
            return self.app.database.get(db, self.kind, self.app.call_admission.scope(owner, project))

    def bindings(self, draft):
        profile = BridgeProfile.model_validate(draft["profile"])
        if profile.route_confirmed or profile.controls_confirmed or draft["source_sha256"] != source_digest():
            raise ValueError("Changed draft/source")
        return profile

    def evidence(self, owner, project, draft):
        if self.collector is None:
            return None
        return self.collector.current(owner, project, draft["revision"])

    def proof_valid(self, proof, profile, scope, revision):
        try:
            return (isinstance(proof, CapturedEvidence) and str(uuid.UUID(proof.capture_id)) == proof.capture_id
                    and proof.owner_project_scope == scope and proof.revision == revision
                    and type(proof.checks) is frozenset and proof.checks == CHECKS and proof.profile_sha256 == profile_digest(profile)
                    and proof.source_sha256 == source_digest()
                    and proof.helper_sha256 == digest(ROOT / ".runtime/call-bridge/bin/CallControl.exe")
                    and proof.issued <= self.clock() < proof.expires <= proof.issued + 600)
        except (OSError, ValueError, TypeError):
            return False

    def blockers(self, sid, draft):
        owner, project = self.context(sid)
        policy, reasons, proof = self.policy(), [], None
        if not policy["enabled"]:
            reasons.append("policy_disabled")
        if draft is None:
            reasons.append("profile_missing")
        else:
            try:
                profile = self.bindings(draft)
                if profile.channel not in policy["channels"]:
                    reasons.append("channel_disabled")
                proof = self.evidence(owner, project, draft)
                if proof is None:
                    reasons.append("evidence_missing")
                elif not self.proof_valid(proof, profile, self.app.call_admission.scope(owner, project), draft["revision"]):
                    reasons.append("evidence_invalid")
            except (OSError, ValueError, KeyError, TypeError):
                reasons.append("profile_changed")
        if not self.components_ready():
            reasons.append("components_missing")
        resources = self.app.resources
        if resources.state in {"resident", "gaming"}:
            reasons.append("resource_policy")
        if resources.fault:
            reasons.append("resource_fault")
        if self.app.call_admission.active or resources.reservations or resources.runner is not None:
            reasons.append("resources_busy")
        try:
            resources.check_capacity("call_local")
        except ServiceError:
            reasons.append("resource_capacity")
        return reasons, proof

    def components_ready(self):
        from calls.local_voice import ready
        try:
            ready()
            return (ROOT / ".runtime/call-bridge/bin/CallControl.exe").is_file() and importlib.util.find_spec("sounddevice") is not None
        except ServiceError:
            return False

    def state(self, sid):
        owner, project = self.context(sid)
        draft = self.load(owner, project)
        blockers, _ = self.blockers(sid, draft)
        active = self.app.call_admission.active
        own = active and active["sid"] == sid and active["owner"] == owner and active["project"] == project
        summary = None if draft is None else {"revision": draft["revision"], "channel": draft["profile"]["channel"],
                   "profile_sha256": profile_digest(BridgeProfile.model_validate(draft["profile"])),
                   "max_seconds": draft["profile"]["max_seconds"]}
        return ControlledTestState(project=project.name, policy_enabled=self.policy()["enabled"], ready=not blockers,
                                   blockers=blockers, draft=summary, active_id=active["id"] if own else None,
                                   worker_busy=bool(active)).model_dump(mode="json")

    def prepare(self, sid, args):
        owner, project = self.context(sid)
        if self.app.call_admission.active:
            raise ServiceError("call_test_busy", "Stop the current call before replacing its enrollment draft.")
        if args.profile.route_confirmed or args.profile.controls_confirmed:
            raise ServiceError("call_test_claimed_proof", "Imported enrollment flags must be false. Physical proof comes from the backend collector.")
        value = {"revision": str(uuid.uuid4()), "profile": args.profile.model_dump(), "source_sha256": source_digest()}
        with self.app.database.transaction() as db:
            self.app.database.put(db, self.kind, self.app.call_admission.scope(owner, project), value)
        self.invalidate()  # A fresh draft cannot inherit any pending arming review.
        return self.state(sid)

    def review(self, sid, args):
        owner, project = self.context(sid)
        draft = self.load(owner, project)
        if not draft or draft["revision"] != str(args.revision):
            raise ServiceError("call_test_stale", "Enrollment changed. Refresh and review the current draft.")
        blockers, proof = self.blockers(sid, draft)
        result = TestReview(project=project.name, revision=args.revision, ready=not blockers, blockers=blockers)
        self.reviews = {key: value for key, value in self.reviews.items() if value["deadline"] > self.clock()}
        if not blockers:
            if len(self.reviews) >= 16:
                raise ServiceError("call_test_review_capacity", "Too many pending call reviews. Wait for expiry.")
            identifier = str(uuid.uuid4())
            self.reviews[identifier] = {"sid": sid, "owner": owner, "project": project, "revision": draft["revision"],
                                        "capture_id": proof.capture_id, "deadline": self.clock() + 60}
            result.review_id, result.expires_at = uuid.UUID(identifier), time.time() + 60
        return result.model_dump(mode="json")

    def accepted(self, sid, revision, capture_id, armed_profile):
        owner, project = self.context(sid)
        policy, draft = self.policy(), self.load(owner, project)
        if not policy["enabled"] or not draft or draft["revision"] != revision:
            return False
        profile = self.bindings(draft)
        expected = profile.model_copy(update={"controls_confirmed": True, "route_confirmed": True})
        proof = self.evidence(owner, project, draft)
        return (profile.channel in policy["channels"] and expected == armed_profile
                and self.proof_valid(proof, profile, self.app.call_admission.scope(owner, project), revision)
                and proof.capture_id == capture_id)

    def arm(self, sid, args):
        owner, project = self.context(sid)
        review = self.reviews.get(str(args.review_id))
        if not review or review["sid"] != sid or review["owner"] != owner or review["project"] != project:
            raise ServiceError("call_test_review", "Use a fresh arming review from this workspace.")
        self.reviews.pop(str(args.review_id))  # One attempt, including a refused/lost outcome.
        if review["deadline"] <= self.clock() or review["revision"] != str(args.revision):
            raise ServiceError("call_test_stale", "Arming review expired or enrollment changed.")
        draft = self.load(owner, project)
        blockers, proof = self.blockers(sid, draft)
        if blockers or proof.capture_id != review["capture_id"]:
            raise ServiceError("call_test_not_ready", "Policy, physical evidence or resources changed. Review again.")
        profile = self.bindings(draft).model_copy(update={"controls_confirmed": True, "route_confirmed": True})
        self.app.call_admission.start(sid, args.request_id, profile, arm_seconds=30,
            acceptance_check=lambda actual: self.accepted(sid, str(args.revision), review["capture_id"], actual))
        return self.state(sid)

    async def stop(self, sid, args):
        owner, project = self.context(sid)
        active = self.app.call_admission.active
        if active and active["id"] == str(args.id):
            if active["sid"] != sid or active["owner"] != owner or active["project"] != project:
                raise ServiceError("call_test_origin", "Stop this one-call lease from its owning workspace.")
            await self.app.call_admission.stop_sid(sid)
        self.invalidate(sid)
        return self.state(sid)
