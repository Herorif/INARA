"""Owner-only offline diagnostics; no live enrollment/answer operation is exposed."""

from typing import Literal
from uuid import UUID
from pydantic import Field, StrictBool, StrictStr
from services.settings import EmptyRequest


class LabReference(EmptyRequest):
    id: UUID


class LabRun(EmptyRequest):
    id: UUID
    mode: Literal["offline_fixture"]
    state: Literal["running", "completed", "interrupted", "failed", "uncertain"]
    code: StrictStr | None = Field(default=None, max_length=120)
    started_at: float
    finished_at: float | None = None
    record_id: UUID | None = None


class CallAvailability(EmptyRequest):
    admission_ready: StrictBool
    active: StrictBool
    live_enabled: Literal[False] = False
    voice_mode: Literal["local_structured_english"] = "local_structured_english"
    cloud_fallback: Literal[False] = False
    blockers: list[Literal["call_components_missing", "call_resources_busy", "resource_policy",
                           "resource_fault", "resource_capacity", "call_physical_unverified"]] = Field(max_length=6)


class LabState(EmptyRequest):
    project: StrictStr = Field(max_length=200)
    live_enabled: Literal[False] = False
    physical_verified: Literal[False] = False
    helper_built: StrictBool
    audio_installed: StrictBool
    voice_configured: StrictBool
    model_installed: StrictBool
    model_accepted: StrictBool
    worker_supported: StrictBool
    worker_busy: StrictBool
    admission: CallAvailability
    runs: list[LabRun] = Field(max_length=24)


class LabSegment(EmptyRequest):
    role: Literal["caller", "assistant"]
    text: StrictStr = Field(max_length=12000)


class LabRecord(EmptyRequest):
    id: UUID
    mode: Literal["offline_fixture"] = "offline_fixture"
    source: Literal["sim", "whatsapp_personal"]
    state: Literal["completed", "interrupted", "failed", "uncertain"]
    identity_verified: Literal[False] = False
    message_confirmed: Literal[False] = False
    transcript: list[LabSegment] = Field(max_length=200)


class WorkerResult(EmptyRequest):
    ok: Literal[True]
    mode: Literal["offline_fixture", "live"]
    id: UUID | None = None
    state: Literal["completed", "interrupted", "failed", "uncertain"]
    code: StrictStr | None = Field(default=None, max_length=120)
