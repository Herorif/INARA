"""Owner-only ``voice_preview``: a short spoken sample of one prebuilt voice."""

import asyncio

from pydantic import ValidationError

from services.log import get_logger
from services.tools import ServiceError
from services.voice_preview import VoicePreviewRequest

logger = get_logger(__name__)


class VoicePreviewTransport:
    def __init__(self, app):
        self.app = app
        app.sio.on("voice_preview", handler=self.preview)

    async def preview(self, sid, data=None):
        try:
            request = VoicePreviewRequest.model_validate(data)
            return {"ok": True, **await self.app.voice_preview.preview(sid, request)}
        except asyncio.CancelledError:
            raise
        except ServiceError as exc:
            return {"ok": False, "code": exc.code, "message": str(exc)}
        except ValidationError:
            return {
                "ok": False,
                "code": "invalid_arguments",
                "message": "Choose one of the listed voices.",
            }
        except Exception:
            logger.exception("Voice preview failed")
            return {
                "ok": False,
                "code": "voice_preview_failed",
                "message": "The voice preview could not play. Try again.",
            }
