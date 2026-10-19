"""Version-one mobile boundary, separate from desktop identities and tool routes."""

import uuid
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr


class MobileModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListenerRequest(MobileModel):
    enabled: StrictBool
    host: StrictStr = "127.0.0.1"
    port: StrictInt = Field(default=8443, ge=1024, le=65535)


class PairRequest(MobileModel):
    allow_chat: StrictBool = False


class DeviceRequest(MobileModel):
    device_id: uuid.UUID


class PairDecision(DeviceRequest):
    approved: StrictBool


class PairClaim(MobileModel):
    challenge_id: uuid.UUID
    secret: StrictStr = Field(min_length=43, max_length=43)
    name: StrictStr = Field(min_length=1, max_length=60, pattern=r"^[\w .()\-]+$")
    public_key: StrictStr = Field(min_length=100, max_length=256)


class SignedEnvelope(MobileModel):
    device_id: uuid.UUID
    request_id: uuid.UUID
    timestamp: StrictInt
    signature: StrictStr = Field(min_length=80, max_length=128)
    # Signed raw UTF-8 JSON, not platform-dependent JSON canonicalization.
    payload: StrictStr = Field(max_length=24000)


class MobileEmpty(MobileModel):
    pass


class MobileHistory(MobileModel):
    conversation_id: uuid.UUID


class MobileReceipt(MobileHistory):
    request_id: uuid.UUID


class MobileChat(MobileReceipt):
    text: StrictStr = Field(min_length=1, max_length=12000)


class MobilePreview(MobileModel):
    kind: Literal["cad", "image"]
    request_id: uuid.UUID
