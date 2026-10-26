"""Owner-only controlled-test preparation, never proof upload or unattended calling."""

from typing import Literal
from uuid import UUID
from pydantic import Field, StrictBool, StrictStr
from calls.contracts import BridgeProfile
from services.settings import EmptyRequest

Blocker = Literal["policy_disabled", "channel_disabled", "profile_missing", "profile_changed",
                  "evidence_missing", "evidence_invalid", "components_missing", "resource_policy",
                  "resources_busy", "resource_capacity", "resource_fault"]


class TestPrepare(EmptyRequest):
    profile: BridgeProfile


class TestRevision(EmptyRequest):
    revision: UUID


class TestArm(TestRevision):
    review_id: UUID
    request_id: UUID
    confirmation: Literal["ANSWER ONE CONTROLLED TEST CALL"]


class TestStop(EmptyRequest):
    id: UUID


class TestDraft(EmptyRequest):
    revision: UUID
    channel: Literal["sim", "whatsapp_personal"]
    profile_sha256: StrictStr = Field(pattern="^[a-f0-9]{64}$")
    max_seconds: int


class TestReview(EmptyRequest):
    project: StrictStr
    revision: UUID
    ready: StrictBool
    blockers: list[Blocker] = Field(max_length=11)
    review_id: UUID | None = None
    expires_at: float | None = None


class ControlledTestState(EmptyRequest):
    project: StrictStr
    unattended_enabled: Literal[False] = False
    policy_enabled: StrictBool
    ready: StrictBool
    blockers: list[Blocker] = Field(max_length=11)
    draft: TestDraft | None = None
    active_id: UUID | None = None
    worker_busy: StrictBool
    voice_mode: Literal["local_structured_english"] = "local_structured_english"
