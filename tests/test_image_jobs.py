"""Image admission, isolated fixture artifacts, scopes, policy and adapter contracts."""

import asyncio
import base64
from contextlib import nullcontext
import importlib
import json
import struct
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from pydantic import ValidationError
from services.images import (
    ImageRequest,
    ImageRecipe,
    ImageArtifactRequest,
    ImageService,
    register_image_tool,
)
from services.image_config import image_backend, inspect_model
from services.image_transport import ImageTransport
from services.resources import ResourceGovernor
from services.storage import Database
from services.tools import ServiceError, ToolDispatcher
from tests.image_support import FixtureImageService
from tests.test_cad_jobs import SlowProcess, finish
from services.cad import CadService, BuildRequest


def service(tmp_path, **kwargs):
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    instance = FixtureImageService(Database(tmp_path / "database"), ResourceGovernor(probe=lambda: {"cpu_count": 8, "ram_available_mb": 16000, "vram_mb": None}), **kwargs)
    return instance, {"principal": "owner", "project_path": project}


def request(**kwargs):
    return ImageRequest(prompt="A test visual direction", **kwargs)


@pytest.mark.parametrize(
    "patch",
    [
        {"prompt": " "},
        {"prompt": " a "},
        {"prompt": "x" * 2001},
        {"width": 513},
        {"height": True},
        {"width": 512.0},
        {"seed": True},
        {"seed": -1},
        {"steps": 41},
        {"guidance": float("nan")},
        {"script": "run me"},
        {"model_dir": "somewhere"},
        {"name": "\x00"},
    ],
)
def test_bounded_image_contract(patch):
    with pytest.raises(ValidationError):
        ImageRecipe.model_validate({"prompt": "A test visual", **patch})


def test_config_missing_invalid_or_unavailable_never_imports_tensors(monkeypatch, tmp_path):
    monkeypatch.delenv("INARA_IMAGE_MODEL_DIR", raising=False)
    before = set(sys.modules)
    assert not image_backend()["available"]
    monkeypatch.setenv("INARA_IMAGE_MODEL_DIR", str(tmp_path))
    assert not image_backend()["available"]
    (tmp_path / "model_index.json").write_text("[]")
    assert not image_backend()["available"]
    assert not {"torch", "diffusers", "PIL"} & (set(sys.modules) - before)


def model_index(tmp_path, pipeline="StableDiffusionPipeline"):
    index = {
        "_class_name": pipeline,
        "vae": ["diffusers", "AutoencoderKL"],
        "unet": ["diffusers", "UNet2DConditionModel"],
        "text_encoder": ["transformers", "CLIPTextModel"],
        "tokenizer": ["transformers", "CLIPTokenizer"],
        "scheduler": ["diffusers", "PNDMScheduler"],
    }
    if pipeline == "StableDiffusionXLPipeline":
        index["text_encoder_2"] = ["transformers", "CLIPTextModelWithProjection"]
        index["tokenizer_2"] = ["transformers", "CLIPTokenizer"]
    (tmp_path / "model_index.json").write_text(json.dumps(index))
    return index


def test_model_contract_rejects_custom_code_and_metadata(monkeypatch, tmp_path):
    index = model_index(tmp_path)
    assert inspect_model(tmp_path)[1] == "StableDiffusionPipeline"
    index["unet"] = ["custom_module", "RunPython"]
    (tmp_path / "model_index.json").write_text(json.dumps(index))
    with pytest.raises(ValueError):
        inspect_model(tmp_path)
    model_index(tmp_path)
    monkeypatch.setenv("INARA_IMAGE_MODEL_DIR", str(tmp_path))
    monkeypatch.setattr("services.image_config.importlib.util.find_spec", lambda _: None)
    assert not image_backend()["available"]


@pytest.mark.asyncio
async def test_unconfigured_backend_rejects_without_claim_or_worker(monkeypatch, tmp_path):
    monkeypatch.delenv("INARA_IMAGE_MODEL_DIR", raising=False)
    fixture, context = service(tmp_path)
    instance = ImageService(
        fixture.database, fixture.governor, process_factory=lambda *_: pytest.fail("Worker started")
    )
    with pytest.raises(ServiceError, match="deferred"):
        await instance.start(request(), context)
    assert (
        not instance.list("owner", context["project_path"])
        and not instance.governor.creative_active
    )


@pytest.mark.asyncio
async def test_real_fixture_exports_private_history_scoping_dedupe_and_tampering(tmp_path):
    instance, context = service(tmp_path)
    args = request(name="private-test-image-name")
    await instance.start(args, context)
    await finish(instance)
    saved = instance.load("owner", context["project_path"], args.request_id)
    assert saved["state"] == "succeeded", saved
    assert saved["stats"]["backend"] == "verification_fixture"
    exports = {
        extension: instance.artifact(
            "owner",
            context["project_path"],
            ImageArtifactRequest(request_id=args.request_id, format=extension),
        )
        for extension in ["png", "json"]
    }
    png = base64.b64decode(exports["png"]["data"])
    assert struct.unpack(">II", png[16:24]) == (512, 512)
    assert (
        json.loads(base64.b64decode(exports["json"]["data"]))["provenance"]["backend"]
        == "verification_fixture"
    )
    assert not instance.active and not instance.governor.creative_active
    assert (await instance.start(args, context))["state"] == "succeeded"
    with pytest.raises(ServiceError):
        await instance.start(args.model_copy(update={"seed": 9}), context)
    assert instance.list("stranger", context["project_path"]) == []
    assert instance.list("owner", tmp_path / "other") == []
    with pytest.raises(ServiceError):
        instance.artifact(
            "stranger", context["project_path"], ImageArtifactRequest(request_id=args.request_id)
        )
    with instance.database.connection() as db:
        payload = db.execute(
            "SELECT payload FROM documents WHERE kind=?",
            (instance.kind("owner", context["project_path"]),),
        ).fetchone()[0]
    assert b"private-test-image-name" not in payload
    (context["project_path"] / saved["directory"] / "model.png").write_bytes(b"tampered")
    with pytest.raises(ServiceError):
        instance.artifact(
            "owner", context["project_path"], ImageArtifactRequest(request_id=args.request_id)
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["cancel", "gaming", "close", "timeout"])
async def test_owned_worker_released_for_all_stops(tmp_path, stop):
    processes = []

    def factory(*args):
        process = SlowProcess()
        processes.append(process)
        return process

    instance, context = service(
        tmp_path, process_factory=factory, timeout=0.02 if stop == "timeout" else 30
    )
    args = request()
    await instance.start(args, context)
    await asyncio.sleep(0.01)
    if stop == "cancel":
        await instance.cancel("owner", context["project_path"], args.request_id)
    elif stop == "gaming":
        instance.governor.select("gaming")
        await finish(instance)
    elif stop == "close":
        await instance.close()
    else:
        await finish(instance)
    assert processes[0].closed and not instance.active and not instance.governor.creative_active
    assert instance.load("owner", context["project_path"], args.request_id)["state"] in {
        "cancelled",
        "failed",
    }


@pytest.mark.asyncio
async def test_cad_and_images_share_one_creative_slot(tmp_path):
    instance, context = service(tmp_path, process_factory=SlowProcess)
    await instance.start(request(), context)
    cad = CadService(
        instance.database,
        instance.governor,
        process_factory=lambda *_: pytest.fail("Concurrent worker"),
    )
    assert (await cad.start(BuildRequest(), context))["state"] == "queued"
    await asyncio.sleep(0.06)
    await cad.close()
    await instance.close()
    instance.governor.select("gaming")
    with pytest.raises(ServiceError):
        await instance.start(request(), context)


@pytest.mark.asyncio
async def test_permission_denial_and_duplicate_approval_stay_cancellable(tmp_path):
    instance, context = service(
        tmp_path, process_factory=lambda *_: pytest.fail("Unapproved worker")
    )
    policy = {"generate_image": "deny"}
    dispatcher = ToolDispatcher(lambda: policy)
    register_image_tool(dispatcher, instance)
    with pytest.raises(ServiceError):
        await dispatcher.dispatch(
            "owner", "generate_image", request().model_dump(mode="json"), context
        )
    policy["generate_image"] = True
    transport = ImageTransport(
        SimpleNamespace(on=lambda *a, **k: None, emit=AsyncMock()),
        instance,
        dispatcher,
        lambda _: context,
    )
    args = request().model_dump(mode="json")
    first = asyncio.create_task(transport.guard(transport.submit)("client", args))
    await asyncio.sleep(0.01)
    original = dict(transport.approvals)
    assert not (await transport.guard(transport.submit)("client", args))["ok"]
    assert transport.approvals == original
    await transport.guard(transport.cancel)("client", {"request_id": args["request_id"]})
    assert not (await first)["ok"] and not instance.active


def test_production_rejects_fixture_provenance_and_bad_png(tmp_path):
    instance, context = service(tmp_path)
    production = ImageService(instance.database, instance.governor)
    with pytest.raises(ServiceError):
        production.validate_artifact("png", b"not an image", request().model_dump())
    manifest = {
        "stats": {
            "width": 512,
            "height": 512,
            "seed": 1234,
            "backend": "verification_fixture",
            "device": "fixture",
            "model": "fixture",
        },
        "artifacts": {
            "png": {"bytes": 40, "sha256": "0" * 64},
            "json": {"bytes": 40, "sha256": "0" * 64},
        },
    }
    with pytest.raises(ServiceError):
        production.validate_result(json.dumps(manifest), request().model_dump())


@pytest.mark.parametrize("pipeline_name", ["StableDiffusionPipeline", "StableDiffusionXLPipeline"])
def test_fixed_diffusers_adapter_uses_local_safetensors_and_bounded_settings(
    monkeypatch, tmp_path, pipeline_name
):
    model_index(tmp_path, pipeline_name)
    calls = {}

    class Pipeline:
        @classmethod
        def from_pretrained(cls, path, **kwargs):
            calls["load"] = (path, kwargs)
            return cls()

        def to(self, device):
            calls["device"] = device

        def enable_vae_slicing(self):
            pass

        def set_progress_bar_config(self, **kwargs):
            pass

        def __call__(self, **kwargs):
            calls["generate"] = kwargs
            return SimpleNamespace(images=["test pixels"])

    generator = SimpleNamespace(manual_seed=lambda seed: seed)
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(
            set_num_threads=lambda n: calls.update(threads=n),
            cuda=SimpleNamespace(is_available=lambda: False),
            float16="f16",
            float32="f32",
            Generator=lambda device: generator,
            inference_mode=nullcontext,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "diffusers",
        SimpleNamespace(StableDiffusionPipeline=Pipeline, StableDiffusionXLPipeline=Pipeline),
    )
    for name in ["HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY"]:
        monkeypatch.setenv(name, "before")
    module = importlib.import_module("creative.image_backend")
    image, stats = module.generate(request().model_dump(), str(tmp_path), lambda _: None)
    assert image == "test pixels" and stats["backend"] == "local_diffusers"
    assert calls["load"][1] == {
        "local_files_only": True,
        "use_safetensors": True,
        "torch_dtype": "f32",
    }
    assert calls["threads"] == 2 and calls["device"] == "cpu"
    assert calls["generate"]["num_inference_steps"] == 24 and calls["generate"]["generator"] == 1234
    assert calls["generate"]["width"] == 512


def test_image_tool_schema_converts_through_installed_sdk(tmp_path):
    from google.genai import types

    instance, _ = service(tmp_path)
    dispatcher = ToolDispatcher(lambda: {})
    register_image_tool(dispatcher, instance)
    config = types.GenerateContentConfig(tools=[{"function_declarations": dispatcher.schemas()}])
    assert config.tools[0].function_declarations[0].name == "generate_image"


@pytest.mark.asyncio
async def test_final_storage_failure_releases_shared_worker_slot(tmp_path, monkeypatch):
    from services.storage import StorageError

    instance, context = service(tmp_path)
    original = instance.save

    def save(owner, project, value):
        if value["state"] == "succeeded":
            raise StorageError("Simulated storage failure")
        return original(owner, project, value)

    monkeypatch.setattr(instance, "save", save)
    args = request()
    await instance.start(args, context)
    await finish(instance)
    assert not instance.active and not instance.governor.creative_active
    assert (
        instance.load("owner", context["project_path"], args.request_id)["state"] == "interrupted"
    )
    # The uncertain claim is retained, so another submission cannot replay it.
    assert (await instance.start(args, context))["state"] == "interrupted"
