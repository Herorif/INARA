"""Lazy Kasa discovery/control, bounded requests and cached observations only."""

import asyncio
import inspect
import time
from services.device_contracts import KasaTarget


def sdk():
    from kasa import Discover

    return Discover


async def disconnect(device):
    close = getattr(device, "disconnect", None)
    if close:
        async with asyncio.timeout(2):
            value = close()
            if inspect.isawaitable(value):
                await value


class KasaController:
    def __init__(self, known_devices=None, discover_factory=sdk):
        self.devices, self.observations = {}, {}
        self.known_devices_config = known_devices or []
        self.discover_factory, self.lock = discover_factory, asyncio.Lock()
        for value in self.known_devices_config[:64]:
            try:
                ip = KasaTarget(ip=value["ip"]).ip
                self.observations[ip] = {
                    "ip": ip,
                    "alias": str(value.get("alias", ip))[:120],
                    "model": str(value.get("model", "unknown"))[:120],
                    "type": "unknown",
                    "is_on": None,
                    "online": False,
                    "brightness": None,
                    "hsv": None,
                    "has_color": False,
                    "has_brightness": False,
                    "observed_at": None,
                }
            except (ValueError, KeyError, TypeError):
                continue

    def snapshot(self):
        return [dict(value) for value in self.observations.values()]

    def remember(self, ip, device):
        bulb, dimmer = (
            bool(getattr(device, "is_bulb", False)),
            bool(getattr(device, "is_dimmer", False)),
        )
        kind = next(
            (
                name
                for name in ("bulb", "plug", "strip", "dimmer")
                if getattr(device, "is_" + name, False)
            ),
            "unknown",
        )
        color = bulb and bool(getattr(device, "is_color", False))
        brightness = (bulb or dimmer) and bool(getattr(device, "is_dimmable", False))
        hsv = getattr(device, "hsv", None) if color else None
        if hsv is not None:
            hsv = {"h": int(hsv[0]), "s": int(hsv[1]), "v": int(hsv[2])}
        self.observations[ip] = {
            "ip": ip,
            "alias": str(device.alias)[:120],
            "model": str(device.model)[:120],
            "type": kind,
            "is_on": bool(device.is_on),
            "online": True,
            "brightness": getattr(device, "brightness", None) if brightness else None,
            "hsv": hsv,
            "has_color": color,
            "has_brightness": brightness,
            "observed_at": time.time(),
        }

    async def release(self, device):
        try:
            await disconnect(device)
        except Exception:
            pass  # Never log credentials or raw device errors.

    async def initialize(self):
        async with self.lock:
            async with asyncio.timeout(20):
                for ip in tuple(self.observations):
                    device = None
                    try:
                        async with asyncio.timeout(3):
                            device = await self.discover_factory().discover_single(ip)
                            if device:
                                await device.update()
                                self.remember(ip, device)
                                self.devices[ip] = device
                    except Exception:
                        self.observations[ip]["online"] = False
                    finally:
                        if device:
                            await self.release(device)

    async def discover_devices(self):
        async with self.lock:
            found = {}
            try:
                async with asyncio.timeout(20):
                    found = await self.discover_factory().discover(
                        target="255.255.255.255", timeout=5
                    )
                    for value in self.observations.values():
                        value["online"] = False
                    for raw, device in list(found.items())[:64]:
                        try:
                            ip = KasaTarget(ip=raw).ip
                            if ip not in self.observations and len(self.observations) >= 64:
                                continue
                            async with asyncio.timeout(3):
                                await device.update()
                            self.remember(ip, device)
                            self.devices[ip] = device
                        except Exception:
                            continue
                    return self.snapshot()
            finally:
                await self.release_many(found.values())

    def get_device_by_alias(self, alias):
        matches = [
            device
            for ip, device in self.devices.items()
            if self.observations.get(ip, {}).get("alias", "").lower() == alias.lower()
        ]
        return matches[0] if len(matches) == 1 else None

    def _resolve_device(self, target):
        return self.devices.get(target) or self.get_device_by_alias(target)

    async def control(self, target, method, *args):
        async with self.lock:
            device = self._resolve_device(target)
            if device is None:
                return False  # Never discover a new target during a control action.
            ip = next(ip for ip, candidate in self.devices.items() if candidate is device)
            try:
                async with asyncio.timeout(8):
                    await getattr(device, method)(*args)
                    await device.update()
                    self.remember(ip, device)
                    return True
            except Exception:
                self.observations[ip]["online"] = False
                return False
            finally:
                await self.release(device)

    async def turn_on(self, target):
        return await self.control(target, "turn_on")

    async def turn_off(self, target):
        return await self.control(target, "turn_off")

    async def set_brightness(self, target, brightness):
        device = self._resolve_device(target)
        if (
            type(brightness) is not int
            or not 0 <= brightness <= 100
            or not device
            or not getattr(device, "is_dimmable", False)
        ):
            return False
        return await self.control(target, "set_brightness", brightness)

    async def set_color(self, target, color_input):
        device = self._resolve_device(target)
        if not device or not getattr(device, "is_color", False):
            return False
        hsv = self.name_to_hsv(color_input) if isinstance(color_input, str) else color_input
        if (
            not isinstance(hsv, (tuple, list))
            or len(hsv) != 3
            or any(
                type(v) is not int or not 0 <= v <= limit for v, limit in zip(hsv, (360, 100, 100))
            )
        ):
            return False
        return await self.control(target, "set_hsv", *hsv)

    async def release_many(self, devices):
        semaphore = asyncio.Semaphore(8)

        async def release_one(device):
            async with semaphore:
                await self.release(device)

        try:
            async with asyncio.timeout(3):
                async with asyncio.TaskGroup() as group:
                    for device in {id(item): item for item in devices}.values():
                        group.create_task(release_one(device))
        except TimeoutError:
            pass

    async def close(self):
        async with self.lock:
            await self.release_many(self.devices.values())
            for value in self.observations.values():
                value["online"] = False

    def name_to_hsv(self, color_name):
        """Converts common color names to HSV (Hue, Saturation, Value).
        Hue: 0-360, Sat: 0-100, Val: 0-100
        """
        color_name = color_name.lower().strip()
        colors = {
            "red": (0, 100, 100),
            "orange": (30, 100, 100),
            "yellow": (60, 100, 100),
            "green": (120, 100, 100),
            "cyan": (180, 100, 100),
            "blue": (240, 100, 100),
            "purple": (300, 100, 100),
            "pink": (300, 50, 100),
            "white": (0, 0, 100),
            "warm": (30, 20, 100),  # Warm White approx
            "cool": (200, 10, 100),  # Cool White approx
            "daylight": (0, 0, 100),
        }
        return colors.get(color_name, None)
