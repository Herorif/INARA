"""The talking overlay's two buttons (J4): ``overlay_stop`` and ``overlay_open``.

Only the owner's ``overlay`` socket may send them (allowed while locked, like the tray's
own items), and they take no fields. ``overlay_stop`` is the tray's "Stop talking";
``overlay_open`` is the tray's "Open JARVIS", run on the tray thread. ACKs are
``{ok: True}`` or ``{ok: False, code, message}``. The overlay receives only
``voice_overlay`` and ``voice_level`` (services/voice_overlay.py).
"""

import asyncio

from pydantic import ValidationError

from services.audio_contracts import OverlayRequest
from services.log import get_logger
from services.tools import ServiceError

logger = get_logger(__name__)

ROLES = {"overlay"}


class VoiceOverlayTransport:
    def __init__(self, app):
        self.app = app
        app.sio.on("overlay_stop", handler=self.stop)
        app.sio.on("overlay_open", handler=self.open)

    def check(self, sid, data):
        self.app.sessions.require_owner(sid, ROLES, allow_locked=True)
        OverlayRequest.model_validate({} if data is None else data)

    async def stop(self, sid, data=None):
        return await self.run(
            sid, data, self.stop_voice, "overlay_stop_failed", "Voice could not stop. Use the tray."
        )

    async def open(self, sid, data=None):
        return await self.run(
            sid, data, self.open_workspace, "overlay_open_failed",
            "JARVIS could not open. Use the tray.",
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

    async def run(self, sid, data, action, code, message):
        try:
            self.check(sid, data)
            await action()
            return {"ok": True}
        except asyncio.CancelledError:
            raise
        except ServiceError as exc:
            return {"ok": False, "code": exc.code, "message": str(exc)}
        except ValidationError:
            return {
                "ok": False,
                "code": "invalid_arguments",
                "message": "The overlay buttons take no fields.",
            }
        except Exception:
            logger.exception("Overlay request failed")
            return {"ok": False, "code": code, "message": message}
