"""Local inference contracts with inert model replies; real evaluation is separate."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from calls.local_model import LocalModel, ModelDialogue
from calls.local_voice import LocalVoice
from services.tools import ServiceError


def fake(intent="answer", value="Alex Tan"):
    return SimpleNamespace(complete=AsyncMock(return_value=json.dumps({"intent": intent, "value": value})))


@pytest.mark.asyncio
async def test_verbatim_field_extraction_and_no_private_context_or_tools():
    model = fake()
    dialogue = ModelDialogue(model)
    reply = await dialogue.reply("My name is Alex Tan.")
    assert dialogue.controller.fields == ["Alex Tan"] and "reason" in reply
    args, kwargs = model.complete.call_args
    assert args[1] == "My name is Alex Tan."
    assert set(kwargs) == {"schema"} and not {"tools", "memory", "owner"} & kwargs.keys()


@pytest.mark.asyncio
@pytest.mark.parametrize("intent", ["repeat", "identity", "decline", "unrelated"])
async def test_questions_and_action_requests_are_not_recorded_as_fields(intent):
    model = fake(intent, "")
    dialogue = ModelDialogue(model)
    reply = await dialogue.reply("synthetic utterance")
    assert reply and dialogue.controller.fields == [] and not dialogue.controller.confirmed


@pytest.mark.asyncio
@pytest.mark.parametrize("output", ['{"intent":"answer","value":"Invented Person"}',
                                    '{"intent":"answer","value":""}',
                                    '{"intent":"tool","value":"run"}',
                                    '{"intent":"answer","value":"Alex","command":"send"}', 'broken'])
async def test_hallucinated_or_invalid_json_never_advances_controller(output):
    model = SimpleNamespace(complete=AsyncMock(return_value=output))
    dialogue = ModelDialogue(model)
    assert "repeat" in (await dialogue.reply("My name is Alex." )).lower()
    assert dialogue.controller.fields == []


@pytest.mark.asyncio
@pytest.mark.parametrize("answer,confirmed", [("yes", True), ("yes maybe", False), ("no", False)])
async def test_only_literal_caller_confirmation_can_confirm(answer, confirmed):
    model = fake()
    dialogue = ModelDialogue(model)
    dialogue.controller.fields = ["Alex", "Appointment", "Call tomorrow", "none"]
    await dialogue.reply(answer)
    assert dialogue.controller.confirmed is confirmed
    model.complete.assert_not_called()


@pytest.mark.asyncio
async def test_local_inference_timeout_reasks_without_cloud_or_saving_question():
    model = SimpleNamespace(complete=AsyncMock(side_effect=TimeoutError()))
    dialogue = ModelDialogue(model)
    assert "repeat" in (await dialogue.reply("Who are you?")).lower()
    assert dialogue.controller.fields == []


@pytest.mark.asyncio
async def test_voice_awaits_dialogue_and_cancels_ongoing_inference():
    entered = asyncio.Event()

    async def slow(_):
        entered.set()
        await asyncio.Event().wait()

    dialogue = SimpleNamespace(reply=AsyncMock(side_effect=slow))
    voice = LocalVoice(None, AsyncMock(return_value=b"\0\0"), dialogue=dialogue)
    voice.generating = True
    voice.reply_task = asyncio.create_task(voice.respond("Alex"))
    await entered.wait()
    await voice.close()
    assert voice.reply_task.cancelled() and not voice.generating and voice.queue.empty()


@pytest.mark.asyncio
async def test_session_close_kills_runtime_and_closes_http_client():
    model = LocalModel()
    model.client = AsyncMock()
    model.process = SimpleNamespace(returncode=None, kill=Mock(), wait=AsyncMock())
    process, client = model.process, model.client
    await model.close()
    process.kill.assert_called_once()
    process.wait.assert_awaited_once()
    client.aclose.assert_awaited_once()
    assert model.client is model.process is None


def test_missing_or_failed_or_stale_evaluation_refuses_model_calls(tmp_path, monkeypatch):
    import calls.local_model as module
    path = tmp_path / "evaluation.json"
    monkeypatch.setattr(module, "EVALUATION", path)
    monkeypatch.setattr(module, "ready", lambda: {})
    monkeypatch.setattr(module, "fingerprints", lambda: {"source": "current"})
    for value in (None, {"accepted_for_calls": False},
                  {"accepted_for_calls": True, "real_inference": True, "inputs": {"source": "old"}}):
        if value is not None:
            path.write_text(json.dumps(value))
        with pytest.raises(ServiceError) as error:
            module.require_evaluation()
        assert error.value.code == "call_model_not_accepted"


@pytest.mark.asyncio
async def test_capacity_failure_occurs_before_loading_runtime(monkeypatch):
    import psutil
    monkeypatch.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(available=1024))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(side_effect=AssertionError("No load")))
    with pytest.raises(ServiceError) as error:
        async with LocalModel():
            pytest.fail("No model at insufficient capacity")
    assert error.value.code == "call_model_capacity"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["ok", "oversized", "redirect", "tool", "truncated"])
async def test_http_contract_bounds_reject_redirects_tools_and_incomplete_output(kind):
    import httpx
    from calls.local_model import Decision

    def handle(request):
        value = json.loads(request.content)
        assert value["max_tokens"] == 160 and "tools" not in value
        assert value["chat_template_kwargs"]["enable_thinking"] is False
        if kind == "oversized":
            return httpx.Response(200, content=b"x" * 65537)
        if kind == "redirect":
            return httpx.Response(302, headers={"Location": "https://must-not-follow.invalid"})
        message = {"content": '{"intent":"repeat","value":""}'}
        if kind == "tool":
            message["tool_calls"] = [{"function": {"name": "send"}}]
        return httpx.Response(200, json={"choices": [{"message": message,
                              "finish_reason": "length" if kind == "truncated" else "stop"}]})

    model = LocalModel()
    model.url = "http://127.0.0.1:12345"
    model.client = httpx.AsyncClient(transport=httpx.MockTransport(handle), trust_env=False)
    try:
        if kind == "ok":
            assert await model.complete("test", "literal", schema=Decision.model_json_schema())
        else:
            with pytest.raises(ServiceError):
                await model.complete("test", "literal")
    finally:
        await model.close()


@pytest.mark.asyncio
async def test_http_close_failure_still_terminates_runtime():
    model = LocalModel()
    model.client = SimpleNamespace(aclose=AsyncMock(side_effect=OSError("synthetic close failure")))
    model.process = SimpleNamespace(returncode=None, kill=Mock(), wait=AsyncMock())
    process = model.process
    with pytest.raises(OSError):
        await model.close()
    process.kill.assert_called_once()
    process.wait.assert_awaited_once()


@pytest.mark.asyncio
async def test_model_mode_reserves_larger_profile_and_records_real_model_id(application_factory, monkeypatch):
    import uuid
    from calls.fixture import fixture_profile

    app = application_factory()
    app.sessions.accept("owner", {"client_id": str(uuid.uuid4())})
    app.resources.probe = lambda: {"cpu_count": 8, "ram_available_mb": 16000}
    monkeypatch.setattr("calls.local_voice.ready", lambda: None)
    monkeypatch.setattr("calls.local_model.require_evaluation", lambda: None)
    monkeypatch.setattr("calls.local_model.ready", lambda: {"model": {"id": "synthetic-model"}})
    calls = []

    class Supervisor:
        last_record_id = None

        async def run(self, bootstrap, *_args, **_kwargs):
            calls.append(bootstrap)
            return {"state": "completed", "id": None, "code": None}

    app.call_admission.supervisor_factory = Supervisor
    app.call_admission.start("owner", uuid.uuid4(), fixture_profile(), acceptance_check=lambda _: True, dialogue_mode="model")
    run = app.call_admission.active
    assert app.resources.reservations[run["reservation"]]["profile"] == "call_model"
    await run["task"]
    assert calls[0]["dialogue_mode"] == "model" and calls[0]["voice_mode"] == "local"
    assert app.usage.snapshot(app.sessions.local_owner)["records"][0]["model"] == "synthetic-model"
    assert not app.resources.reservations
