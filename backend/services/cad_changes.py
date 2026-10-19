"""Bounded data-only change sets. No paths, scripts, imports or generated execution."""

import asyncio
import uuid
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    model_validator,
    field_validator,
)
from services.cad import Recipe, SceneObject, SolidRecipe, ScenePresentation
from services.tools import ServiceError


class RevisionReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_request_id: uuid.UUID
    base_fingerprint: str = Field(pattern="^[a-f0-9]{64}$")


class EditableFields(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    name: StrictStr | None = Field(default=None, min_length=1, max_length=60)
    width: float | None = Field(default=None, strict=True, ge=1, le=1000)
    depth: float | None = Field(default=None, strict=True, ge=1, le=1000)
    height: float | None = Field(default=None, strict=True, ge=1, le=1000)
    thickness: float | None = Field(default=None, strict=True, ge=0.5, le=100)
    position: list[float] | None = Field(default=None, min_length=3, max_length=3)
    rotation: list[float] | None = Field(default=None, min_length=3, max_length=3)
    scale: list[float] | None = Field(default=None, min_length=3, max_length=3)
    presentation: ScenePresentation | None = None
    material: StrictStr | None = Field(default=None, max_length=20)

    @field_validator("position", "rotation", "scale", mode="before")
    @classmethod
    def valid_vectors(cls, value, info):
        return None if value is None else SceneObject.valid_vector(value, info)


class ObjectEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # None edits the solid/root name; integer edits a scene object at that base index.
    object_index: StrictInt | None = Field(default=None, ge=0, le=7)
    fields: EditableFields

    @model_validator(mode="after")
    def nonempty(self):
        if not self.fields.model_dump(exclude_none=True):
            raise ValueError("Provide at least one supported field")
        return self


class EditList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    edits: list[ObjectEdit] = Field(min_length=1, max_length=16)


class ChangeSet(RevisionReference, EditList):
    pass


class ChangePrompt(RevisionReference):
    prompt: StrictStr = Field(min_length=1, max_length=2000)


def apply_changes(base, edits):
    recipe = Recipe.model_validate(base).model_dump()
    for edit in edits:
        patch = edit.fields.model_dump(exclude_none=True)
        if edit.object_index is None:
            allowed = (
                {"name", "presentation"}
                if recipe["shape"] == "scene"
                else (set(SolidRecipe.model_fields) - {"shape"}) | {"presentation"}
            )
            if not set(patch) <= allowed:
                raise ServiceError(
                    "change_invalid", "Transforms and materials require a scene object selection."
                )
            recipe.update(patch)
        else:
            if recipe["shape"] != "scene" or edit.object_index >= len(recipe["objects"]):
                raise ServiceError(
                    "change_invalid", "That object is not present in the base revision."
                )
            obj = recipe["objects"][edit.object_index]
            recipe["objects"][edit.object_index] = SceneObject.model_validate(
                {**obj, **patch}
            ).model_dump()
    return Recipe.model_validate(recipe).model_dump()


async def propose_changes(prompt, base, provider_factory=None):
    from llm.base import Message, MessageRole
    from services.conversation import create_text_provider
    import json
    from services.tools import inline_tool_schema

    provider = None
    try:
        provider = (provider_factory or create_text_provider)()
        async with asyncio.timeout(30):
            result = await provider.generate(
                [Message(MessageRole.USER, json.dumps({"request": prompt, "base_recipe": base}))],
                tools=[
                    {
                        "function_declarations": [
                            {
                                "name": "propose_scene_edits",
                                "description": "Return supported field edits against the supplied immutable recipe; indices refer to its object order.",
                                "parameters": inline_tool_schema(EditList),
                            }
                        ]
                    }
                ],
                system_instruction="Return exactly one propose_scene_edits call. Use only supported dimensional fields and existing objects. CAD dimensions/positions are millimetres, rotations X/Y/Z in degrees, then translation. No scripts, topology changes, holes, booleans or fabricated features. This is a proposal for user review; do not execute anything.",
            )
            if len(result.tool_calls) != 1 or result.tool_calls[0].name != "propose_scene_edits":
                raise ServiceError(
                    "change_invalid", "The planner did not return a supported change set."
                )
            return EditList.model_validate(result.tool_calls[0].args)
    except ServiceError:
        raise
    except TimeoutError as exc:
        raise ServiceError("provider_timeout", "The change proposal timed out.") from exc
    except Exception as exc:
        raise ServiceError(
            "change_invalid", "The planner could not propose supported changes."
        ) from exc
    finally:
        if provider:
            try:
                await asyncio.wait_for(provider.close(), 5)
            except Exception:
                pass
