"""Retired always-on AudioLoop. Use services.speech and the quick assistant."""

from services.tools import ServiceError


class AudioLoop:
    def __init__(self, **kwargs):
        raise ServiceError(
            "voice_migrated",
            "Always-on voice is retired. Open Quick assistant and explicitly hold Push to talk.",
        )
