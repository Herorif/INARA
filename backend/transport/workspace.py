"""Preserved desktop wire events over owned workspace services."""

import hashlib
from services.workspace import WORKSPACE_TOOLS
from transport.local_actions import LocalActionTransport


class WorkspaceTransport(LocalActionTransport):
    events = tuple(
        "generate_cad" if name == "legacy_generate_cad" else name for name in WORKSPACE_TOOLS
    )

    def __init__(self, sio, dispatcher, sessions, service):
        self.service = service
        super().__init__(sio, dispatcher, sessions)

    def handler(self, name):
        return super().handler("legacy_generate_cad" if name == "generate_cad" else name)

    def context(self, sid):
        self.sessions.require_owner(sid, {"renderer"})
        return super().context(sid)

    def tool_context(self, sid, context):
        return {**context.tools(), "origin_sid": sid}

    def approval_payload(self, payload):
        return approval_summary(payload)

    async def emit_result(self, name, result, sid):
        await self.sio.emit("status", {"msg": result["message"]}, room=sid)
        if name in ("legacy_generate_cad", "iterate_cad"):
            await self.sio.emit("cad_status", {"status": "idle"}, room=sid)

    async def emit_error(self, name, sid, payload):
        if name in ("legacy_generate_cad", "iterate_cad"):
            await self.sio.emit("cad_status", {"status": "error"}, room=sid)
        await super().emit_error(name, sid, payload)


def approval_summary(payload):
    """Review metadata without duplicating private transcript bodies in UI."""
    args = payload["args"]
    if payload["tool"] == "save_memory":
        import json

        raw = json.dumps(
            args, sort_keys=True, default=lambda v: hashlib.sha256(v).hexdigest()
        ).encode()
        summary = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        summary.update(filename=args.get("filename"), messages=len(args["messages"]))
        return {**payload, "args": summary}
    return payload
