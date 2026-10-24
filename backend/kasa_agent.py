"""Compatibility import; SDK discovery/control is separated and remains lazy."""
from devices.kasa import KasaController as KasaAgent

__all__ = ["KasaAgent"]
