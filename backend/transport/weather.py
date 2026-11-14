"""Owner-only weather routes for Preferences (docs/WEATHER.md).

``weather_home_set`` {place: str | null}: geocodes the place with Open-Meteo and saves it as
``assistant.home_place`` ({name, lat, lon}), or clears it with null. Answers
``{ok, home_place}`` or ``{ok: false, code, message}``; the new settings go to the owner's
renderers. Needs the authenticated, unlocked desktop owner renderer.
"""

from pydantic import ValidationError

from services.log import get_logger
from services.tools import ServiceError
from services.weather import HomePlaceRequest

logger = get_logger(__name__)


class WeatherTransport:
    events = ("weather_home_set",)

    def __init__(self, app):
        self.app = app
        for name in self.events:
            handler = self.handler(name)
            setattr(self, name, handler)
            app.sio.on(name, handler=handler)

    def handler(self, name):
        method = getattr(self, "_" + name)

        async def handle(sid, data=None):
            try:
                principal = self.app.sessions.require_owner(sid, {"renderer"})
                return await method(principal, {} if data is None else data)
            except ServiceError as exc:
                return {"ok": False, "code": exc.code, "message": str(exc)}
            except ValidationError:
                return {
                    "ok": False,
                    "code": "invalid_arguments",
                    "message": "Type a town or city name (up to 120 characters).",
                }
            except Exception as exc:
                logger.warning("Weather request %s failed (%s)", name, type(exc).__name__)
                return {
                    "ok": False,
                    "code": "weather_unavailable",
                    "message": "The home town couldn't be saved. Try again.",
                }

        return handle

    async def _weather_home_set(self, principal, data):
        request = HomePlaceRequest.model_validate(data)
        if request.place is None:
            return await self.app.weather.set_home(None, principal)
        place = " ".join(request.place.split())
        if not place:
            raise ServiceError("invalid_arguments", "Type a town or city name.")
        return await self.app.weather.set_home(place, principal)
