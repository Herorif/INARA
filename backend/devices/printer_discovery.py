"""Explicit bounded mDNS observation, with cleanup even during cancellation.

Only advertised protocols are recorded. No HTTP probes or camera acquisition.
"""

import asyncio
import ipaddress
from services.device_contracts import EndpointRequest
from devices.printer_models import Printer, PrinterType

LOCAL_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16")
)


class PrinterDiscoveryListener:
    def __init__(self):
        self.printers = []

    def add_service(self, zc, type_, name):
        if len(self.printers) >= 64:
            return
        info = zc.get_service_info(type_, name)
        if not info:
            return
        addresses = info.parsed_addresses()
        host = None
        for value in addresses:
            try:
                address = ipaddress.ip_address(value)
                if (
                    address.version == 4
                    and any(address in network for network in LOCAL_NETWORKS)
                    and not (
                        address.is_loopback
                        or address.is_unspecified
                        or address.is_multicast
                        or address.is_reserved
                    )
                ):
                    host = str(address)
                    break
            except ValueError:
                continue
        if host is None:
            return  # Advertisements cannot turn local discovery into arbitrary DNS/Internet probes.
        try:
            endpoint = EndpointRequest(host=host, port=info.port or 80)
        except ValueError:
            return
        kind = (
            PrinterType.OCTOPRINT
            if "_octoprint._tcp" in type_
            else PrinterType.MOONRAKER
            if any(part in type_ for part in ("_moonraker._tcp", "_klipper._tcp"))
            else PrinterType.UNKNOWN
        )
        self.printers.append(
            Printer(name[:120].replace(f".{type_}", ""), endpoint.host, endpoint.port, kind)
        )

    def remove_service(self, *args):
        pass

    def update_service(self, *args):
        pass


def default_factories():
    from zeroconf import Zeroconf, ServiceBrowser, ServiceListener

    def browse(zc, service, delegate):
        class Listener(ServiceListener):
            def add_service(self, *args):
                delegate.add_service(*args)

            def update_service(self, *args):
                delegate.update_service(*args)

            def remove_service(self, *args):
                delegate.remove_service(*args)

        return ServiceBrowser(zc, service, listener=Listener())

    return Zeroconf, browse


async def discover_printers(timeout=5.0, factories=default_factories, listener=None):
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 8:
        raise ValueError("Discovery timeout must be between zero and eight seconds.")
    zeroconf_factory, browser_factory = factories()
    zc, browsers = zeroconf_factory(), []
    listener = listener or PrinterDiscoveryListener()
    try:
        for service in (
            "_octoprint._tcp.local.",
            "_moonraker._tcp.local.",
            "_klipper._tcp.local.",
            "_http._tcp.local.",
        ):
            browsers.append(browser_factory(zc, service, listener))
        await asyncio.sleep(timeout)
        return listener.printers[:64]
    finally:
        try:
            for browser in browsers:
                try:
                    browser.cancel()
                except Exception:
                    pass
        finally:
            zc.close()
