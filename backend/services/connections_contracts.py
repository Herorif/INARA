"""Metadata-only readiness; no endpoints, names or secrets in this report."""

from typing import Literal
from pydantic import Field, StrictBool, StrictInt, StrictStr
from services.settings import EmptyRequest


class ConnectionCard(EmptyRequest):
    id: Literal["kasa", "printers"]
    title: StrictStr = Field(max_length=120)
    installed: StrictBool
    loaded: StrictBool
    configured_count: StrictInt = Field(ge=0)
    observed_count: StrictInt = Field(ge=0)
    state: Literal["missing_dependency", "unconfigured", "unverified", "observed"]
    message: StrictStr = Field(max_length=500)


class ConnectionsState(EmptyRequest):
    schema_version: Literal[1]
    network_used: Literal[False]
    physical_verified: Literal[False]
    cards: list[ConnectionCard] = Field(min_length=2, max_length=2)
    printer_discovery_installed: StrictBool
    observation_active: StrictBool
    slicer_inspected: StrictBool
    slicer_available: StrictBool
