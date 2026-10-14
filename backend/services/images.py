"""Bounded image contracts over the common owned creative-job service."""

import json
import struct
import uuid
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictStr, StrictInt, field_validator
from services.creative_jobs import CreativeJobService, ExportMetadata, JobRequest
from services.image_config import image_backend
from services.tools import ServiceError, ToolSpec


class ImageRecipe(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    name: StrictStr = Field(default="Untitled visual", min_length=1, max_length=60)
    prompt: StrictStr = Field(min_length=3, max_length=2000)
    negative_prompt: StrictStr = Field(default="", max_length=1000)
    width: StrictInt = Field(
        default=512, ge=512, le=1024, description="Use 512, 768 or 1024 pixels."
    )
    height: StrictInt = Field(
        default=512, ge=512, le=1024, description="Use 512, 768 or 1024 pixels."
    )
    steps: StrictInt = Field(default=24, ge=1, le=40)
    seed: StrictInt = Field(default=1234, ge=0, le=2_147_483_647)
    guidance: float = Field(default=7.0, ge=1, le=15, strict=True)

    @field_validator("name", "prompt", mode="before")
    @classmethod
    def readable(cls, value, info):
        if (
            not isinstance(value, str)
            or "\x00" in value
            or (info.field_name == "name" and any(ord(char) < 32 for char in value))
        ):
            raise ValueError("Use readable text")
        return value.strip()

    @field_validator("width", "height", mode="before")
    @classmethod
    def strict_size(cls, value):
        if type(value) is not int or value not in (512, 768, 1024):
            raise ValueError("Use a supported integer image size")
        return value


class ImageRequest(ImageRecipe):
    request_id: uuid.UUID = Field(default_factory=uuid.uuid4)


class ImageArtifactRequest(JobRequest):
    format: Literal["png", "json"] = "png"


class ImageStats(BaseModel):
    model_config = ConfigDict(extra="forbid")
    width: StrictInt
    height: StrictInt
    seed: StrictInt
    backend: Literal["local_diffusers", "verification_fixture"]
    model: StrictStr = Field(min_length=1, max_length=80)
    device: Literal["cpu", "cuda", "fixture"]


class ImageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stats: ImageStats
    artifacts: dict[str, ExportMetadata]


class ImageService(CreativeJobService):
    namespace = "image_jobs:"
    artifact_root = "images"
    recipe_model = ImageRecipe
    worker_script = "workers/image_worker.py"
    phases = ("building", "loading", "generating", "validating", "saving")
    default_timeout = 180
    expected_backend = "local_diffusers"

    def capabilities(self):
        return {key: value for key, value in image_backend().items() if key != "model_dir"}

    def admit(self, recipe):
        backend = image_backend()
        if not backend["available"]:
            raise ServiceError("image_not_configured", backend["reason"])
        return backend

    def bootstrap(self, staging, recipe, backend):
        return {"staging": str(staging), "recipe": recipe, "model_dir": backend["model_dir"]}

    def artifact_label(self, recipe):
        return "image"

    def validate_result(self, raw, recipe):
        result = ImageResult.model_validate_json(raw).model_dump()
        stats = result["stats"]
        if (
            set(result["artifacts"]) != {"png", "json"}
            or result["artifacts"].get("json", {}).get("bytes", 0) > 32768
            or stats["backend"] != self.expected_backend
            or any(stats[key] != recipe[key] for key in ("width", "height", "seed"))
        ):
            raise ServiceError("worker_failed", "Image output validation failed.")
        if self.expected_backend == "local_diffusers" and stats["device"] == "fixture":
            raise ServiceError("worker_failed", "Unexpected image worker provenance.")
        return result

    def validate_artifact(self, extension, raw, recipe):
        if extension == "json":
            value = json.loads(raw)
            stats = ImageStats.model_validate(value["provenance"])
            if (
                value["recipe"] != recipe
                or stats.backend != self.expected_backend
                or any(getattr(stats, key) != recipe[key] for key in ("width", "height", "seed"))
            ):
                raise ServiceError("artifact_invalid", "Image recipe provenance is invalid.")
        if extension == "png" and (
            len(raw) < 33
            or raw[:8] != b"\x89PNG\r\n\x1a\n"
            or raw[12:16] != b"IHDR"
            or struct.unpack(">II", raw[16:24]) != (recipe["width"], recipe["height"])
        ):
            raise ServiceError("artifact_invalid", "Image dimensions or PNG header are invalid.")


def register_image_tool(dispatcher, service):
    dispatcher.register(
        ToolSpec(
            "generate_image",
            "Generate one local PNG using a separately configured image model. Prompt, dimensions, seed and quality steps are bounded; returns a scoped creative job.",
            ImageRequest,
            service.start,
        )
    )
