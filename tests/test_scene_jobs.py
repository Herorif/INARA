"""Independent scene export inspection and actual owned scene-worker contracts."""

import base64
import json
import struct
import pytest
from pydantic import ValidationError
from creative.scene import assemble, transform
from services.cad import Recipe, SceneObject, BuildRequest, ArtifactRequest, blender_executable
from services.tools import ServiceError
from tests.test_cad_jobs import service, finish, SlowProcess


def scene(**kwargs):
    return Recipe(
        shape="scene",
        objects=[
            SceneObject(name="Base"),
            SceneObject(name="Accent", position=[100, 0, 0], material="amber"),
        ],
        **kwargs,
    )


def unpack(payload):
    assert struct.unpack_from("<III", payload) == (0x46546C67, 2, len(payload))
    length = struct.unpack_from("<I", payload, 12)[0]
    return json.loads(payload[20 : 20 + length]), payload[28 + length :]


def test_scene_keeps_object_names_materials_and_binary_world_coordinates():
    stats, mesh, binary = assemble(scene().model_dump())
    assert stats["volume_mm3"] == pytest.approx(288000)
    assert stats["bounds_mm"] == [[0, 0, 0], [180, 60, 30]]
    assert struct.unpack_from("<I", mesh, 80)[0] == 24
    doc, data = unpack(binary)
    assert [node["name"] for node in doc["nodes"]] == ["Base", "Accent"]
    assert [material["name"] for material in doc["materials"]] == ["cyan", "amber"]
    for index, low in [(0, 0), (1, 0.1)]:
        primitive = doc["meshes"][index]["primitives"][0]
        accessor = doc["accessors"][primitive["attributes"]["POSITION"]]
        view = doc["bufferViews"][accessor["bufferView"]]
        points = list(
            struct.iter_unpack(
                "<3f", data[view["byteOffset"] : view["byteOffset"] + view["byteLength"]]
            )
        )
        assert min(point[0] for point in points) == pytest.approx(low)
        assert max(point[1] for point in points) == pytest.approx(0.03)
        assert min(point[2] for point in points) == pytest.approx(-0.06)
        assert primitive["material"] == index


def test_scale_then_xyz_rotation_then_translation_and_overlap_is_not_union():
    obj = SceneObject(scale=[2, 3, 4], rotation=[90, 0, 90], position=[10, 20, 30]).model_dump()
    assert transform([1, 2, 3], obj) == pytest.approx((22, 22, 36))
    recipe = scene().model_dump()
    recipe["objects"][1]["position"] = [0, 0, 0]
    stats, _, _ = assemble(recipe)
    assert stats["volume_mm3"] == pytest.approx(288000)  # Sum, no boolean union claim.
    assert stats["triangles"] == 24


@pytest.mark.parametrize(
    "patch",
    [
        {"position": [True, 0, 0]},
        {"rotation": [0, float("nan"), 0]},
        {"scale": [1, 0, 1]},
        {"position": [2001, 0, 0]},
        {"rotation": [0, 0, 361]},
        {"scale": [6, 1, 1]},
        {"material": "execute"},
        {"position": [1, 2]},
        {"script": "anything"},
    ],
)
def test_invalid_scene_objects_reject_before_worker(patch):
    with pytest.raises(ValidationError):
        SceneObject(**patch)


def test_scene_bounds_and_no_nested_objects():
    for value in [
        dict(shape="scene"),
        dict(shape="scene", objects=[]),
        dict(shape="scene", objects=[{}] * 9),
        dict(shape="box", objects=[{}]),
        dict(shape="scene", objects=[dict(shape="scene", objects=[{}])]),
    ]:
        with pytest.raises(ValidationError):
            Recipe(**value)


@pytest.mark.asyncio
async def test_actual_scene_revision_preserves_old_solid_and_scoped_dedupe(tmp_path):
    instance, context = service(tmp_path)
    first = BuildRequest()
    await instance.start(first, context)
    await finish(instance)
    old = instance.artifact(
        "owner", context["project_path"], ArtifactRequest(request_id=first.request_id)
    )
    args = BuildRequest(**scene().model_dump())
    await instance.start(args, context)
    await finish(instance)
    saved = instance.load("owner", context["project_path"], args.request_id)
    assert saved["state"] == "succeeded", saved
    assert not instance.active
    artifact = instance.artifact(
        "owner", context["project_path"], ArtifactRequest(request_id=args.request_id, format="glb")
    )
    doc, _ = unpack(base64.b64decode(artifact["data"]))
    assert len(doc["nodes"]) == 2
    assert old == instance.artifact(
        "owner", context["project_path"], ArtifactRequest(request_id=first.request_id)
    )
    assert (await instance.start(args, context))["state"] == "succeeded"
    with pytest.raises(ServiceError):
        await instance.start(args.model_copy(update={"name": "Changed"}), context)
    with pytest.raises(ServiceError, match="does not contain"):
        instance.artifact(
            "owner",
            context["project_path"],
            ArtifactRequest(request_id=args.request_id, format="blend"),
        )


@pytest.mark.asyncio
async def test_scene_worker_cancel_and_gaming_cleanup(tmp_path):
    processes = []

    def factory(*args):
        process = SlowProcess()
        processes.append(process)
        return process

    instance, context = service(tmp_path, factory)
    args = BuildRequest(**scene().model_dump())
    await instance.start(args, context)
    import asyncio

    await asyncio.sleep(0.02)
    await instance.cancel("owner", context["project_path"], args.request_id)
    assert processes[0].closed and not instance.active
    assert instance.load("owner", context["project_path"], args.request_id)["state"] == "cancelled"
    instance.governor.state = "gaming"
    with pytest.raises(ServiceError):
        await instance.start(BuildRequest(**scene().model_dump()), context)


@pytest.mark.asyncio
async def test_missing_blender_rejected_before_claim(monkeypatch, tmp_path):
    monkeypatch.setattr("services.cad.blender_executable", lambda: None)
    instance, context = service(tmp_path, lambda *_: pytest.fail("Unavailable worker started"))
    with pytest.raises(ServiceError, match="not installed"):
        await instance.start(BuildRequest(**scene(engine="blender").model_dump()), context)
    assert not instance.list("owner", context["project_path"])


@pytest.mark.asyncio
@pytest.mark.skipif(
    not blender_executable(), reason="Blender is not installed; real round trip unverified"
)
async def test_installed_blender_real_project_render_export(tmp_path):
    instance, context = service(tmp_path)
    args = BuildRequest(**scene(engine="blender").model_dump())
    await instance.start(args, context)
    await finish(instance)
    saved = instance.load("owner", context["project_path"], args.request_id)
    assert saved["state"] == "succeeded", saved
    assert not instance.active
    for extension in ["blend", "png", "glb"]:
        artifact = instance.artifact(
            "owner",
            context["project_path"],
            ArtifactRequest(request_id=args.request_id, format=extension),
        )
        raw = base64.b64decode(artifact["data"])
        assert raw.startswith(
            {"blend": b"BLENDER", "png": b"\x89PNG\r\n\x1a\n", "glb": b"glTF"}[extension]
        )


def test_eight_transformed_enclosures_fit_export_and_volume_limits():
    objects = [
        SceneObject(
            shape="enclosure",
            scale=[0.1, 0.2, 0.3],
            position=[2000, -2000, 2000],
            rotation=[35, 17, 91],
            material="ceramic",
        )
        for _ in range(8)
    ]
    recipe = Recipe(shape="scene", objects=objects).model_dump()
    stats, mesh, binary = assemble(recipe)
    assert stats["triangles"] == 8 * 92
    assert stats["volume_mm3"] == pytest.approx(8 * 36108 * 0.1 * 0.2 * 0.3, rel=1e-7)
    assert len(mesh) == 84 + 50 * stats["triangles"]
    document, data = unpack(binary)
    assert len(document["nodes"]) == 8
    assert len(data) == document["buffers"][0]["byteLength"]


@pytest.mark.asyncio
async def test_pre_scene_revision_defaults_do_not_break_completed_dedupe(tmp_path):
    instance, context = service(tmp_path)
    args = BuildRequest()
    await instance.start(args, context)
    await finish(instance)
    saved = instance.load("owner", context["project_path"], args.request_id)
    saved["recipe"].pop("engine")
    saved["recipe"].pop("objects")
    instance.save("owner", context["project_path"], saved)
    instance.process_factory = lambda *_: pytest.fail("Replayed old revision")
    assert (await instance.start(args, context))["state"] == "succeeded"


def test_nested_scene_tool_schema_converts_through_real_installed_sdk(tmp_path):
    from google.genai import types
    from services.tools import ToolDispatcher
    from services.cad import register_cad_tools

    dispatcher = ToolDispatcher(lambda: {})
    instance, _ = service(tmp_path)
    register_cad_tools(dispatcher, instance)
    declarations = dispatcher.schemas()
    assert "$defs" not in json.dumps(declarations)
    assert "$ref" not in json.dumps(declarations)
    config = types.GenerateContentConfig(tools=[{"function_declarations": declarations}])
    props = config.tools[0].function_declarations[0].parameters.properties
    assert props["objects"].any_of[0].items.properties["material"].enum == [
        "cyan",
        "titanium",
        "amber",
        "ceramic",
    ]
