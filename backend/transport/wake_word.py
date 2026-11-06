"""Owner-only ``wake_word_status``: whether the tray is listening for "Hey Jarvis".

Answers ``{ok, state, message}`` (``WakeWordStatus``) from what the core already knows; it
never opens a device. The switch itself is saved through update_settings
(``voice.wake_word``) or the tray menu.
"""

import asyncio

from pydantic import ValidationError

from services.audio_contracts import WakeWordStatus, WakeWordStatusRequest
from services.log import get_logger
from services.tools import ServiceError

logger = get_logger(__name__)


class WakeWordTransport:
    def __init__(self, app):
        self.app = app
        app.sio.on("wake_word_status", handler=self.status)

    async def status(self, sid, data=None):
        try:
            self.app.sessions.require_owner(sid, {"renderer"})
            WakeWordStatusRequest.model_validate({} if data is None else data)
            view = WakeWordStatus.model_validate(self.app.wake.report()).model_dump()
            return {"ok": True, **view}
        except asyncio.CancelledError:
            raise
        except ServiceError as exc:
            return {"ok": False, "code": exc.code, "message": str(exc)}
        except ValidationError:
            return {
                "ok": False,
                "code": "invalid_arguments",
                "message": '"Hey Jarvis" status takes no fields.',
            }
        except Exception:
            logger.exception('"Hey Jarvis" status failed')
            return {
                "ok": False,
                "code": "wake_word_failed",
                "message": '"Hey Jarvis" status could not be read. Try again.',
            }
