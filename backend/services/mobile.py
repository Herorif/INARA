"""Owner-confirmed mobile identity and narrow project access; no desktop token reuse."""

import asyncio
import hashlib
import hmac
import secrets
import time
import uuid
from pathlib import Path
from services.conversation import ConversationRequest, ConversationService
from services.mobile_identity import MobileIdentities, decode_key, verify
from services.sessions import SessionStore
from services.tools import ServiceError, ToolDispatcher


class MobileService:
    def __init__(self, app, clock=time.time):
        self.app, self.clock = app, clock
        self.identities = MobileIdentities(app.database, clock)
        self.challenge = None
        self.pending = {}
        self.running = {}
        from services.notifications import NotificationInbox

        self.notifications = NotificationInbox(self)
        # Deliberately empty dispatcher. Phone chat cannot invoke even read-file tools.
        self.chat = ConversationService(
            ToolDispatcher(lambda: {}),
            timeout=30,
            store=SessionStore(app.database),
            usage=app.usage,
            instructions="You are INARA in a tool-free phone conversation. You cannot inspect files, control the laptop, approve actions, or read desktop conversations. Explain those limits when relevant. WhatsApp drafting and sending are unavailable.",
        )
        from services.mobile_listener import MobileListener

        self.listener = MobileListener(self)

    def prune(self):
        now = self.clock()
        self.pending = {
            key: value for key, value in self.pending.items() if value["pair_expires"] > now
        }
        if self.challenge and self.challenge["expires"] <= now:
            self.challenge = None

    def owner(self, owner):
        if not self.app.sessions.is_owner(owner) or not self.app.sessions.authenticated(owner):
            raise ServiceError("mobile_owner", "Unlock the registered desktop owner first.")

    def snapshot(self, owner):
        self.owner(owner)
        self.prune()
        keys = ("device_id", "name", "fingerprint", "project", "grants", "expires", "revoked")
        return {
            "listener": self.listener.snapshot(),
            "pending": [
                {k: value[k] for k in keys if k in value}
                for value in self.pending.values()
                if value["owner"] == owner
            ],
            "devices": [
                {k: value[k] for k in keys}
                for value in sorted(
                    self.identities.list(), key=lambda item: (item["revoked"], -item["expires"])
                )[:128]
                if value["owner"] == owner
            ],
        }

    def pair(self, owner, project, allow_chat):
        self.owner(owner)
        self.prune()
        if not self.listener.running:
            raise ServiceError("mobile_off", "Explicitly start the private TLS listener first.")
        secret = secrets.token_urlsafe(32)
        self.pending.clear()
        self.challenge = {
            "id": str(uuid.uuid4()),
            "digest": hashlib.sha256(secret.encode()).hexdigest(),
            "owner": owner,
            "project": str(project.resolve()),
            "expires": self.clock() + 120,
            "grants": ["status:read", "jobs:read"] + (["chat:ask"] if allow_chat else []),
        }
        return {
            "version": 1,
            "endpoint": self.listener.endpoint,
            "certificate": self.listener.certificate,
            "challenge_id": self.challenge["id"],
            "secret": secret,
            "expires": int(self.challenge["expires"]),
            "project": project.name,
        }

    def claim(self, envelope, args, path):
        self.prune()
        key, fingerprint = decode_key(args.public_key)
        verify(key, envelope, path, self.clock())
        challenge = self.challenge
        if (
            not challenge
            or str(args.challenge_id) != challenge["id"]
            or not hmac.compare_digest(
                hashlib.sha256(args.secret.encode()).hexdigest(), challenge["digest"]
            )
        ):
            raise ServiceError(
                "mobile_pair", "Pairing expired or was consumed. Generate a new invitation."
            )
        self.owner(challenge["owner"])
        identifier = str(envelope.device_id)
        if self.identities.get(identifier) or identifier in self.pending:
            raise ServiceError("mobile_pair", "Use a new device identity for a new pairing.")
        active = [
            value
            for value in self.identities.list()
            if not value["revoked"] and value["expires"] > self.clock()
        ]
        if len(active) >= 8:
            raise ServiceError("mobile_limit", "Revoke an unused device before pairing another.")
        self.identities.consume(identifier, str(envelope.request_id))
        self.pending[identifier] = {
            "device_id": identifier,
            "name": args.name,
            "public_key": args.public_key,
            "fingerprint": fingerprint,
            "owner": challenge["owner"],
            "project_path": challenge["project"],
            "project": Path(challenge["project"]).name,
            "grants": challenge["grants"],
            "pair_expires": challenge["expires"],
            "expires": self.clock() + 30 * 86400,
            "revoked": False,
        }
        self.challenge = None
        return {"state": "pending", "fingerprint": fingerprint}

    def decide(self, owner, identifier, approved):
        self.owner(owner)
        self.prune()
        value = self.pending.get(str(identifier))
        if not value or value["owner"] != owner:
            raise ServiceError("mobile_pair", "This pairing is no longer pending.")
        if approved:
            self.identities.save(value)
        self.pending.pop(str(identifier))

    def authenticate(self, envelope, path, grant=None, pending=False):
        self.prune()
        identifier = str(envelope.device_id)
        value = self.identities.get(identifier) or (
            self.pending.get(identifier) if pending else None
        )
        if not value or value["revoked"] or value["expires"] <= self.clock():
            raise ServiceError(
                "mobile_auth", "Device is expired, revoked or not approved. Pair again."
            )
        self.owner(value["owner"])
        key, _ = decode_key(value["public_key"])
        verify(key, envelope, path, self.clock())
        self.identities.consume(identifier, str(envelope.request_id))
        if grant and grant not in value["grants"]:
            raise ServiceError("mobile_grant", "This device does not have that grant.")
        root = self.app.projects.projects_dir.resolve()
        project = Path(value["project_path"])
        if not project.is_dir() or project.resolve().parent != root or project.resolve() != project:
            raise ServiceError("mobile_scope", "The paired project is no longer available.")
        return value

    def recheck(self, value, grant):
        current = self.identities.get(value["device_id"])
        self.owner(value["owner"])
        if (
            not current
            or current["revoked"]
            or current["expires"] <= self.clock()
            or grant not in current["grants"]
        ):
            raise ServiceError("mobile_auth", "Device authorization changed.")

    async def revoke(self, owner, identifier):
        self.owner(owner)
        value = self.identities.get(str(identifier))
        if not value or value["owner"] != owner:
            raise ServiceError("mobile_scope", "Device does not belong to this owner.")
        value["revoked"] = True
        self.identities.save(value)
        self.notifications.revoke(value)
        await self.stop_requests(str(identifier))

    def status(self, value):
        return {
            "project": value["project"],
            "resource_state": self.app.resources.state,
            "grants": value["grants"],
            "expires": int(value["expires"]),
            "tools_enabled": False,
        }

    def jobs(self, value):
        project = Path(value["project_path"])
        results = []
        for kind, service in (("cad", self.app.cad), ("image", self.app.images)):
            for job in service.list(value["owner"], project):
                results.append(
                    {
                        "kind": kind,
                        "request_id": job["request_id"],
                        "state": job["state"],
                        "name": job["recipe"].get("name", "Saved design"),
                        "created_at": job["created_at"],
                    }
                )
        return {
            "project": value["project"],
            "jobs": sorted(results, key=lambda v: v["created_at"], reverse=True)[:12],
        }

    def preview(self, value, args):
        service = self.app.cad if args.kind == "cad" else self.app.images
        project = Path(value["project_path"])
        job = service.load(value["owner"], project, args.request_id)
        if not job or job["state"] != "succeeded":
            raise ServiceError(
                "mobile_preview", "No completed preview exists in this paired project."
            )
        if args.kind == "cad":
            return {"kind": "cad", "recipe": job["recipe"], "stats": job.get("stats")}
        if job.get("artifacts", {}).get("png", {}).get("bytes", 99999999) > 2_097_152:
            raise ServiceError(
                "mobile_preview", "Image exceeds the mobile preview limit. Open it on the laptop."
            )
        from services.images import ImageArtifactRequest

        return {
            "kind": "image",
            **service.artifact(
                value["owner"], project, ImageArtifactRequest(request_id=args.request_id)
            ),
        }

    def principal(self, value):
        return f"mobile:{value['owner']}:{value['device_id']}"

    async def ask(self, value, args):
        if not args.text.strip():
            raise ServiceError("mobile_text", "Enter a message first.")
        identifier = value["device_id"]
        if len(self.running) >= 4 or identifier in self.running.values():
            raise ServiceError("mobile_busy", "Wait for the current phone request to finish.")
        task = asyncio.current_task()
        self.running[task] = identifier
        try:
            try:
                result = await asyncio.wait_for(
                    self.chat.reply(
                        self.principal(value),
                        ConversationRequest(**args.model_dump()),
                        Path(value["project_path"]),
                        authorize=lambda: self.recheck(value, "chat:ask"),
                        billing_owner=value["owner"],
                        usage_feature="phone_chat",
                    ),
                    55,
                )
            except TimeoutError as exc:
                raise ServiceError(
                    "mobile_timeout", "Phone request expired. Check its receipt before retrying."
                ) from exc
            self.recheck(value, "chat:ask")
            return result.model_dump(mode="json")
        finally:
            self.running.pop(task, None)

    def history(self, value, args):
        # Never import a desktop project's legacy voice/chat file into phone history.
        return {
            "messages": self.chat.store.restore(
                str(args.conversation_id), self.principal(value), value["project_path"]
            )
        }

    def receipt(self, value, args):
        store = self.chat.store
        with self.app.database.connection() as db:
            store._load(db, str(args.conversation_id), self.principal(value), value["project_path"])
            row = db.execute(
                "SELECT payload FROM requests WHERE session=? AND id=?",
                (str(args.conversation_id), str(args.request_id)),
            ).fetchone()
            if not row:
                return {"state": "absent"}
            previous = self.app.database.decode(
                f"request:{args.conversation_id}:{args.request_id}", row[0]
            )
            state = previous["state"]
            return {
                "state": "uncertain" if state == "running" else state,
                **({"result": previous["result"]} if state == "succeeded" else {}),
            }

    async def stop_requests(self, identifier=None):
        tasks = [
            task
            for task, device in tuple(self.running.items())
            if (identifier is None or device == identifier) and task is not asyncio.current_task()
        ]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def close(self):
        self.challenge = None
        self.pending.clear()
        await self.stop_requests()
        await self.listener.stop()
