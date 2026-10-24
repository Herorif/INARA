"""Deterministic product-contract evaluations with synthetic data and providers only."""

import json
import math
from pathlib import Path
import struct
import time
import uuid
import zlib

SUITE_VERSION = 1
CASE_IDS = (
    "assistant.reply_and_deduplicate",
    "assistant.permissions",
    "memory.consent_and_scope",
    "budget.shared_admission",
    "cad.box_volume",
    "cad.bracket_volume",
    "cad.enclosure_volume",
    "cad.scene_transforms",
    "cad.unsupported_shape",
    "image.fixture_png",
    "image.reject_wrong_size",
    "image.reject_fixture_provenance",
)


def fixture_png():
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    scanlines = (b"\x00" + b"\x26\x82\x91" * 512) * 512
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 512, 512, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(scanlines))
        + chunk(b"IEND", b"")
    )


async def run_fixture_suite(directory):
    from application import create_application
    from services.storage import Database
    from services.tools import ServiceError
    from services.conversation import ConversationRequest
    from services.memory_contracts import MemoryWrite
    from services.usage_contracts import UsagePolicy
    from services.cad import Recipe, SceneObject
    from services.images import ImageRecipe
    from creative.geometry import build, validate, stl
    from creative.scene import assemble
    from llm.base import LLMResponse
    from pydantic import ValidationError

    directory = Path(directory)
    app = create_application(
        settings={
            "face_auth_enabled": False,
            "tool_permissions": {"read_file": "deny"},
            "kasa_devices": [],
        },
        project_root=directory / "projects",
        legacy_data_dir=directory / "legacy",
        database=Database(directory / "private"),
    )
    app.sessions.local_owner = "fixture-owner"
    app.sessions.principals["fixture"] = "fixture-owner"
    app.sessions.roles["fixture"] = "renderer"
    project = app.projects.get_current_project_path()
    cases = []
    started = time.monotonic()

    async def run(identifier, action):
        before = time.monotonic()
        try:
            result = action()
            if hasattr(result, "__await__"):
                result = await result
            passed = result is True
        except Exception:
            passed = False
        cases.append(
            {
                "id": identifier,
                "passed": passed,
                "duration_seconds": round(time.monotonic() - before, 4),
            }
        )

    class Provider:
        calls = 0
        _model = "fixture-only"

        async def generate(self, messages, **kwargs):
            Provider.calls += 1
            return LLMResponse(text="Synthetic fixture response")

        async def close(self):
            pass

    app.conversation.provider_factory = Provider

    async def reply():
        args = ConversationRequest(text="Synthetic fixture question")
        first = await app.conversation.reply("fixture-owner", args, project, origin_sid="fixture")
        second = await app.conversation.reply("fixture-owner", args, project, origin_sid="fixture")
        return (
            first.text == "Synthetic fixture response" and first == second and Provider.calls == 1
        )

    async def denied():
        try:
            await app.dispatcher.dispatch(
                "fixture-owner",
                "read_file",
                {"path": "never-open.txt"},
                {"principal": "fixture-owner", "project_path": project},
            )
        except ServiceError as exc:
            return exc.code == "permission_denied" and not (project / "never-open.txt").exists()
        return False

    def memory():
        current = app.memory.snapshot("fixture-owner", project)
        args = MemoryWrite(
            revision=current["revision"],
            id=uuid.uuid4(),
            title="Fixture clearance",
            text="Synthetic clearance 42 mm",
        )
        app.memory.write("fixture-owner", project, args)
        if app.memory.context("fixture-owner", project, "clearance", "fixture")["items"]:
            return False
        current = app.memory.snapshot("fixture-owner", project)
        app.memory.write(
            "fixture-owner",
            project,
            args.model_copy(
                update={"revision": uuid.UUID(current["revision"]), "assistant_enabled": True}
            ),
        )
        other = app.projects.projects_dir / "other"
        other.mkdir()
        return (
            len(app.memory.context("fixture-owner", project, "clearance", "fixture")["items"]) == 1
            and not app.memory.snapshot("fixture-owner", other)["items"]
        )

    def budget():
        report = app.usage.snapshot("fixture-owner")
        app.usage.configure(
            "fixture-owner",
            UsagePolicy(
                revision=report["policy"]["revision"],
                enabled=True,
                daily_microusd=5,
                monthly_microusd=5,
                per_call_microusd=3,
            ),
        )
        first = app.usage.begin(
            "fixture-owner", project, "desktop_chat", "fixture-budget", 0, "fixture-only"
        )
        app.usage.finish(first, "completed", None, 0)
        try:
            app.usage.begin(
                "fixture-owner", project, "phone_chat", "fixture-budget", 1, "fixture-only"
            )
        except ServiceError as exc:
            return exc.code == "usage_daily_limit"
        return False

    def solid(shape, expected):
        recipe = Recipe(shape=shape, width=80, depth=60, height=30, thickness=3).model_dump()
        vertices, faces = build(recipe)
        stats = validate(vertices, faces)
        binary = stl(vertices, faces)
        return (
            stats["watertight"]
            and math.isclose(stats["volume_mm3"], expected, rel_tol=1e-9)
            and len(binary) == 84 + 50 * len(faces)
            and struct.unpack_from("<I", binary, 80)[0] == len(faces)
        )

    def scene():
        recipe = Recipe(
            shape="scene",
            objects=[SceneObject(name="Base"), SceneObject(name="Accent", position=[100, 0, 0])],
        ).model_dump()
        stats, _, binary = assemble(recipe)
        size = struct.unpack_from("<I", binary, 12)[0]
        document = json.loads(binary[20 : 20 + size])
        return (
            stats["bounds_mm"] == [[0, 0, 0], [180, 60, 30]]
            and math.isclose(stats["volume_mm3"], 288000)
            and [node["name"] for node in document["nodes"]] == ["Base", "Accent"]
        )

    def unsupported():
        try:
            Recipe(shape="sphere")
        except ValidationError:
            return True
        return False

    def image():
        raw = fixture_png()
        app.images.validate_artifact(
            "png", raw, ImageRecipe(prompt="Synthetic fixture only").model_dump()
        )
        cursor, pixels = 8, b""
        while cursor < len(raw):
            size = struct.unpack_from(">I", raw, cursor)[0]
            kind, data = raw[cursor + 4 : cursor + 8], raw[cursor + 8 : cursor + 8 + size]
            if zlib.crc32(kind + data) != struct.unpack_from(">I", raw, cursor + 8 + size)[0]:
                return False
            if kind == b"IDAT":
                pixels += data
            cursor += 12 + size
        return len(zlib.decompress(pixels)) == 512 * (1 + 512 * 3)

    def wrong_size():
        try:
            app.images.validate_artifact(
                "png",
                fixture_png(),
                ImageRecipe(prompt="Synthetic fixture only", width=768).model_dump(),
            )
        except ServiceError:
            return True
        return False

    def provenance():
        recipe = ImageRecipe(prompt="Synthetic fixture only").model_dump()
        raw = json.dumps(
            {
                "recipe": recipe,
                "provenance": {
                    "width": 512,
                    "height": 512,
                    "seed": 1234,
                    "backend": "verification_fixture",
                    "model": "fixture",
                    "device": "fixture",
                },
            }
        ).encode()
        try:
            app.images.validate_artifact("json", raw, recipe)
        except ServiceError:
            return True
        return False

    actions = (
        reply,
        denied,
        memory,
        budget,
        lambda: solid("box", 144000),
        lambda: solid("bracket", 20880),
        lambda: solid("enclosure", 36108),
        scene,
        unsupported,
        image,
        wrong_size,
        provenance,
    )
    try:
        for identifier, action in zip(CASE_IDS, actions):
            await run(identifier, action)
    finally:
        await app.close()
    return {
        "suite_version": SUITE_VERSION,
        "fixture_only": True,
        "provider_used": False,
        "model_quality_verified": False,
        "passed": all(case["passed"] for case in cases),
        "passed_count": sum(case["passed"] for case in cases),
        "total": len(cases),
        "cases": cases,
        "duration_seconds": round(time.monotonic() - started, 3),
    }
