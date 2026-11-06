"""Owner-only ``audio_devices``: this PC's microphones and speakers for tray voice (J2).

Lists devices without opening them; a missing audio library is reported as a setup state
(``available: false``), not an error. The choice itself is saved through update_settings.
"""

import asyncio

from pydantic import ValidationError

from services.audio_contracts import AudioDevicesRequest
from services.log import get_logger
from services.tools import ServiceError

logger = get_logger(__name__)


class AudioDevicesTransport:
    def __init__(self, app):
        self.app = app
        app.sio.on("audio_devices", handler=self.devices)

    async def devices(self, sid, data=None):
        try:
            self.app.sessions.require_owner(sid, {"renderer"})
            AudioDevicesRequest.model_validate({} if data is None else data)
            # The "Hey Jarvis" stream is released briefly so PortAudio can re-read devices.
            return {"ok": True, **await self.app.wake.report_devices()}
        except asyncio.CancelledError:
            raise
        except ServiceError as exc:
            return {"ok": False, "code": exc.code, "message": str(exc)}
        except ValidationError:
            return {
                "ok": False,
                "code": "invalid_arguments",
                "message": "The device list takes no fields.",
            }
        except Exception:
            logger.exception("Audio device listing failed")
            return {
                "ok": False,
                "code": "audio_devices_failed",
                "message": "The device list could not be read. Try again.",
            }
