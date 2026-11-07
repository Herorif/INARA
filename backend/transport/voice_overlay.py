"""The talking overlay's two buttons (J4) and the workspace's speaking core (C1).

``overlay_stop`` and ``overlay_open``: only the owner's ``overlay`` socket may send them
(allowed while locked, like the tray's own items), and they take no fields.
``overlay_stop`` is the tray's "Stop talking"; ``overlay_open`` is the tray's "Open
JARVIS", run on the tray thread. The overlay receives only ``voice_overlay`` and
``voice_level`` (services/voice_overlay.py).

``voice_stage`` (``{visible: bool}``, nothing else) and ``local_voice_stop`` (no fields):
only the owner's ``renderer`` sockets may send them, allowed while locked. ``voice_stage``
reports whether that socket shows the speaking core, which decides when a tray session's
overlay opens; ``local_voice_stop`` is the stage's "Stop talking" for a tray session.

ACKs are ``{ok: True}`` or ``{ok: False, code, message}``.
"""

import asyncio

from pydantic import BaseModel, ConfigDict, ValidationError

from services.audio_contracts import OverlayRequest
from services.log import get_logger
from services.tools import ServiceError

logger = get_logger(__name__)

ROLES = {"overlay"}
RENDERER = {"renderer"}


class VoiceStageRequest(BaseModel):
    """``voice_stage``: whether this renderer shows the speaking core."""

    model_config = ConfigDict(extra="forbid", strict=True)

    visible: bool


class VoiceOverlayTransport:
    def __init__(self, app):
        self.app = app
        app.sio.on("overlay_stop", handler=self.stop)
        app.sio.on("overlay_open", handler=self.open)
        app.sio.on("voice_stage", handler=self.stage)
        app.sio.on("local_voice_stop", handler=self.stop_from_stage)

    def check(self, sid, data, roles=ROLES):
        self.app.sessions.require_owner(sid, roles, allow_locked=True)
        OverlayRequest.model_validate({} if data is None else data)

    async def stop(self, sid, data=None):
        return await self.run(
            lambda: self.check(sid, data), self.stop_voice,
            "overlay_stop_failed", "Voice could not stop. Use the tray.",
        )

    async def open(self, sid, data=None):
        return await self.run(
            lambda: self.check(sid, data), self.open_workspace, "overlay_open_failed",
            "JARVIS could not open. Use the tray.",
        )

    async def stop_from_stage(self, sid, data=None):
        return await self.run(
            lambda: self.check(sid, data, RENDERER), self.stop_voice,
            "local_voice_stop_failed", "Voice could not stop. Use the tray.",
            invalid="Stop talking takes no fields.",
        )

    async def stage(self, sid, data=None):
        request = {}

        def check():
            self.app.sessions.require_owner(sid, RENDERER, allow_locked=True)
            request["value"] = VoiceStageRequest.model_validate(data)

        async def remember():
            self.app.voice_overlay.set_stage(sid, request["value"].visible)

        return await self.run(
            check, remember, "voice_stage_failed", "The voice stage could not be updated.",
            invalid="Send only visible: true or false.",
        )

    async def stop_voice(self):
        # The tray's "Stop talking": a safety stop, always allowed.
        await self.app.voice.stop_local()

    async def open_workspace(self):
        native = self.app.sessions.native_desktop
        tray = getattr(native, "tray", None)
        if native is None or tray is None:
            raise ServiceError("workspace_unavailable", "Open JARVIS from the tray.")
        # The tray's "Open JARVIS": process work happens on the tray thread.
        tray.post(lambda: native.open_workspace(quick=False))

    async def run(self, check, action, code, message, invalid="The overlay buttons take no fields."):
        try:
            check()
            await action()
            return {"ok": True}
        except asyncio.CancelledError:
            raise
        except ServiceError as exc:
            return {"ok": False, "code": exc.code, "message": str(exc)}
        except ValidationError:
            return {"ok": False, "code": "invalid_arguments", "message": invalid}
        except Exception:
            logger.exception("Overlay request failed")
            return {"ok": False, "code": code, "message": message}
