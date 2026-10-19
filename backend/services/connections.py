"""Readiness is a local metadata/cache inspection; never activates optional adapters."""

import importlib.util
from services.lazy import LazyService
from services.connections_contracts import ConnectionsState


def installed(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ValueError, ImportError):
        return False


def loaded(adapter):
    return adapter.instance if isinstance(adapter, LazyService) else None


class ConnectionsReadiness:
    def __init__(self, app):
        self.app = app
        self.package_probe = installed

    def snapshot(self):
        service = self.app.compat_service
        kasa, printer = loaded(service.kasa), loaded(service.printer)
        kasa_ready = self.package_probe("kasa")
        http_ready, mdns_ready = self.package_probe("aiohttp"), self.package_probe("zeroconf")
        devices = getattr(kasa, "observations", {}) if kasa is not None else {}
        statuses = getattr(printer, "_last_status", {}) if printer is not None else {}
        cards = []
        for identifier, title, ready, adapter, configured, observed, message in (
            (
                "kasa",
                "Smart home",
                kasa_ready,
                kasa,
                len(self.app.settings.get("kasa_devices", [])),
                sum(item.get("observed_at") is not None for item in devices.values()),
                "Explicit discovery loads the Kasa adapter. Saved devices are not proof of connectivity.",
            ),
            (
                "printers",
                "Print workshop",
                http_ready,
                printer,
                len(self.app.settings.get("printers", [])),
                sum(status.state != "offline" for status in statuses.values()),
                "Upload and physical start remain separate approved stages. Cached status is not live verification.",
            ),
        ):
            state = (
                "missing_dependency"
                if not ready
                else "observed"
                if observed
                else "unverified"
                if configured
                else "unconfigured"
            )
            cards.append(
                {
                    "id": identifier,
                    "title": title,
                    "installed": ready,
                    "loaded": adapter is not None,
                    "configured_count": configured,
                    "observed_count": observed,
                    "state": state,
                    "message": message,
                }
            )
        monitor = service.observation.task
        return ConnectionsState.model_validate(
            {
                "schema_version": 1,
                "network_used": False,
                "physical_verified": False,
                "cards": cards,
                "printer_discovery_installed": mdns_ready,
                "observation_active": monitor is not None and not monitor.done(),
                "slicer_inspected": printer is not None,
                "slicer_available": bool(getattr(printer, "slicer_path", None))
                if printer is not None
                else False,
            }
        ).model_dump()
