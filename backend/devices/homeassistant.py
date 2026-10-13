"""
Home Assistant REST API bridge.

Provides a thin async wrapper around the HA REST API so DeviceAgent
can query and control any entity exposed by Home Assistant — lights,
switches, sensors, media players, climate, etc.

Configuration (from settings.json):
  home_assistant.url      — e.g. "http://homeassistant.local:8123"
  home_assistant.token    — Long-lived access token from HA profile page
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class HomeAssistantBridge:
    """Async REST client for the Home Assistant API."""

    def __init__(self, url: str, token: str):
        # Strip trailing slash for clean URL joins
        self._base = url.rstrip("/")
        self._token = token
        self._session = None   # aiohttp.ClientSession, created lazily

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    async def _get_session(self):
        if self._session is None or self._session.closed:
            import aiohttp
            headers = {
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            }
            self._session = aiohttp.ClientSession(headers=headers)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    # ------------------------------------------------------------------
    # Core REST helpers
    # ------------------------------------------------------------------

    async def _get(self, path: str) -> Any:
        session = await self._get_session()
        url = f"{self._base}/api{path}"
        async with session.get(url) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _post(self, path: str, payload: dict | None = None) -> Any:
        session = await self._get_session()
        url = f"{self._base}/api{path}"
        async with session.post(url, json=payload or {}) as resp:
            resp.raise_for_status()
            try:
                return await resp.json()
            except Exception:
                return {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def ping(self) -> bool:
        """Check if HA is reachable. Returns True on success."""
        try:
            result = await self._get("/")
            return isinstance(result, dict) and result.get("message") == "API running."
        except Exception as e:
            logger.warning(f"[HA] Ping failed: {e}")
            return False

    async def get_states(self, domain: Optional[str] = None) -> list[dict]:
        """
        Return all entity states, optionally filtered by domain
        (e.g. 'light', 'switch', 'sensor', 'climate', 'media_player').
        """
        states: list[dict] = await self._get("/states")
        if domain:
            states = [s for s in states if s.get("entity_id", "").startswith(f"{domain}.")]
        return states

    async def get_state(self, entity_id: str) -> dict:
        """Return the current state of a single entity."""
        return await self._get(f"/states/{entity_id}")

    async def call_service(self, domain: str, service: str, data: dict | None = None) -> Any:
        """
        Call any HA service.
        Example: call_service("light", "turn_on", {"entity_id": "light.office", "brightness": 200})
        """
        return await self._post(f"/services/{domain}/{service}", data or {})

    async def turn_on(self, entity_id: str, **kwargs) -> bool:
        """Turn on any entity. Extra kwargs passed as service data (e.g. brightness=200)."""
        try:
            await self.call_service(
                "homeassistant", "turn_on",
                {"entity_id": entity_id, **kwargs},
            )
            return True
        except Exception as e:
            logger.warning(f"[HA] turn_on {entity_id} failed: {e}")
            return False

    async def turn_off(self, entity_id: str) -> bool:
        """Turn off any entity."""
        try:
            await self.call_service("homeassistant", "turn_off", {"entity_id": entity_id})
            return True
        except Exception as e:
            logger.warning(f"[HA] turn_off {entity_id} failed: {e}")
            return False

    async def toggle(self, entity_id: str) -> bool:
        """Toggle the state of any entity."""
        try:
            await self.call_service("homeassistant", "toggle", {"entity_id": entity_id})
            return True
        except Exception as e:
            logger.warning(f"[HA] toggle {entity_id} failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Convenience device list
    # ------------------------------------------------------------------

    async def list_devices(self) -> list[dict]:
        """
        Returns a simplified device list suitable for the DeviceAgent / frontend.
        Includes lights, switches, and media players.
        """
        try:
            states = await self._get("/states")
        except Exception as e:
            logger.warning(f"[HA] list_devices failed: {e}")
            return []

        include_domains = {"light", "switch", "input_boolean", "media_player", "climate", "fan", "cover"}
        devices = []
        for s in states:
            eid = s.get("entity_id", "")
            domain = eid.split(".")[0] if "." in eid else ""
            if domain not in include_domains:
                continue
            attrs = s.get("attributes", {})
            devices.append({
                "id": eid,
                "name": attrs.get("friendly_name", eid),
                "domain": domain,
                "state": s.get("state", "unknown"),
                "source": "home_assistant",
                "attributes": {
                    k: v for k, v in attrs.items()
                    if k in ("brightness", "color_temp", "rgb_color", "current_temperature",
                             "temperature", "volume_level", "media_title")
                },
            })
        return devices
