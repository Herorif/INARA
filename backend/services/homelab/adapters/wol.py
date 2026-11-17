"""``wol``: Wake-on-LAN. A magic packet is 6 bytes of 0xFF then the MAC address 16 times,
sent as one UDP broadcast (stdlib socket). A wol system has nothing to watch: pair it with a
ping system (or set ``wake_mac`` on any other system) to see whether it woke.
"""

import socket
from typing import Literal

from pydantic import StrictStr, field_validator

from services.homelab.adapters.common import BaseAdapter, CommonOptions, broadcast_address, mac_address


def magic_packet(mac):
    raw = bytes.fromhex(mac_address(mac).replace(":", ""))
    return b"\xff" * 6 + raw * 16


def send_udp(packet, address):
    """Send one UDP broadcast datagram (the real sender; tests pass their own)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, address)


class WolOptions(CommonOptions):
    mac: StrictStr
    broadcast: StrictStr = "255.255.255.255"
    port: Literal[7, 9] = 9

    @field_validator("mac")
    @classmethod
    def check_mac(cls, value):
        return mac_address(value)

    @field_validator("broadcast")
    @classmethod
    def check_broadcast(cls, value):
        return broadcast_address(value)


class WolAdapter(BaseAdapter):
    Options = WolOptions

    async def probe(self):
        return [self.entity(None, "host", self.config.name, "unknown", {},
                            "Wake-on-LAN only: add a ping system to watch it.")]


def wake_target(config):
    """(mac, broadcast, port) for ``homelab_wake``, or None when the system can't be woken."""
    options = config.options
    if config.adapter == "wol":
        return options["mac"], options["broadcast"], options["port"]
    if options.get("wake_mac"):
        return options["wake_mac"], options.get("wake_broadcast", "255.255.255.255"), \
            options.get("wake_port", 9)
    return None
