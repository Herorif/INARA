"""Printer data without optional networking SDK imports."""

from dataclasses import dataclass, asdict
from enum import Enum
from typing import Optional, Dict


class PrinterType(Enum):
    OCTOPRINT = "octoprint"
    MOONRAKER = "moonraker"
    PRUSALINK = "prusalink"
    UNKNOWN = "unknown"


@dataclass
class Printer:
    """Represents a discovered 3D printer."""

    name: str
    host: str
    port: int
    printer_type: PrinterType
    api_key: Optional[str] = None
    camera_url: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("api_key", None)
        d["printer_type"] = self.printer_type.value
        return d


@dataclass
class PrintStatus:
    """Current status of a print job."""

    printer: str
    state: str  # "printing", "idle", "paused", "error"
    progress_percent: float
    time_remaining: Optional[str]
    time_elapsed: Optional[str]
    filename: Optional[str]
    temperatures: Optional[Dict[str, Dict[str, float]]] = None
    details: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)
