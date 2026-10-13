"""Deterministic milestone tests: no camera, microphone, API spend or real app launch."""

import sys
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from llm.base import LLMResponse, ToolCall
from project_manager import ProjectManager
from services.conversation import ConversationRequest, ConversationService, create_text_provider
from services.tools import ServiceError, ToolDispatcher, contained_path, register_project_tools


class FakeProvider:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.closed = False

    async def generate(self, messages, **kwargs):
        self.calls.append(list(messages))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response

    async def close(self):
        self.closed = True


def make_service(responses, permissions=None):
    dispatcher = ToolDispatcher(lambda: permissions or {"read_file": False, "write_file": False})
    register_project_tools(dispatcher)
    provider = FakeProvider(responses)
    return ConversationService(dispatcher, lambda: provider), provider


@pytest.mark.asyncio
async def test_text_without_audio_and_duplicate_request(tmp_path):
    service, provider = make_service([LLMResponse(text="Ready without a microphone.")])
    request = ConversationRequest(text="Hello")
    first = await service.reply("owner", request, tmp_path)
    second = await service.reply("owner", request, tmp_path)
    assert first == second
    assert len(provider.calls) == 1
    assert provider.closed
    assert "inara" not in sys.modules
    with pytest.raises(ServiceError, match="already used"):
        await service.reply("owner", request.model_copy(update={"text": "Different"}), tmp_path)


@pytest.mark.asyncio
async def test_history_and_owner_project_scopes(tmp_path):
    service, provider = make_service([LLMResponse(text="First"), LLMResponse(text="Second")])
    first = ConversationRequest(text="My part is a cube")
    await service.reply("owner", first, tmp_path)
    await service.reply(
        "owner",
        ConversationRequest(text="Make it taller", conversation_id=first.conversation_id),
        tmp_path,
    )
    assert provider.calls[1][0].content == "My part is a cube"
    assert provider.calls[1][1].content == "First"
    with pytest.raises(ServiceError, match="new conversation"):
        await service.reply("other-owner", first, tmp_path)
    with pytest.raises(ServiceError, match="new conversation"):
        await service.reply("owner", first, tmp_path / "another")


@pytest.mark.parametrize("text", [42, "", "x" * 12_001])
def test_request_validation(text):
    with pytest.raises(ValidationError):
        ConversationRequest(text=text)


@pytest.mark.parametrize("key", ["", "your_api_key_here", "changeme"])
def test_missing_placeholder_credentials_are_explicit(monkeypatch, key):
    monkeypatch.setenv("GEMINI_API_KEY", key)
    with pytest.raises(ServiceError) as exc:
        create_text_provider()
    assert exc.value.code == "provider_not_configured"


@pytest.mark.asyncio
async def test_provider_failure_is_sanitized_and_not_replayed(tmp_path):
    service, provider = make_service([RuntimeError("secret-api-key inside SDK error")])
    request = ConversationRequest(text="Hello")
    for _ in range(2):
        with pytest.raises(ServiceError) as exc:
            await service.reply("owner", request, tmp_path)
        assert exc.value.code == "provider_failed"
        assert "secret-api-key" not in str(exc.value)
    assert len(provider.calls) == 1
    assert provider.closed


@pytest.mark.asyncio
async def test_project_tool_iteration_and_output(tmp_path):
    service, provider = make_service(
        [
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        "call-1", "write_file", {"path": "parts/notes.txt", "content": "Dimensions"}
                    )
                ]
            ),
            LLMResponse(text="Saved the notes."),
        ]
    )
    result = await service.reply("owner", ConversationRequest(text="Save notes"), tmp_path)
    assert (tmp_path / "parts/notes.txt").read_text() == "Dimensions"
    assert result.text == "Saved the notes."
    assert provider.calls[1][-1].tool_call_id == "call-1"


@pytest.mark.asyncio
async def test_denied_tool_does_not_write(tmp_path):
    service, provider = make_service(
        [
            LLMResponse(
                tool_calls=[
                    ToolCall("call-1", "write_file", {"path": "notes.txt", "content": "No"})
                ]
            ),
            LLMResponse(text="That action is disabled."),
        ],
        {"write_file": "deny"},
    )
    await service.reply("owner", ConversationRequest(text="Save"), tmp_path)
    assert not (tmp_path / "notes.txt").exists()
    assert "permission_denied" in provider.calls[1][-1].content


@pytest.mark.asyncio
async def test_approval_owner_binding_and_expiry(tmp_path):
    dispatcher = ToolDispatcher(lambda: {"write_file": True}, timeout=0.01)
    register_project_tools(dispatcher)

    async def approve(payload):
        assert not dispatcher.resolve("intruder", payload["id"], True)
        assert dispatcher.resolve("owner", payload["id"], True)
        assert not dispatcher.resolve("owner", payload["id"], True)

    await dispatcher.dispatch(
        "owner",
        "write_file",
        {"path": "yes.txt", "content": "yes"},
        {"project_path": tmp_path},
        approve,
    )
    assert (tmp_path / "yes.txt").exists()
    with pytest.raises(ServiceError) as exc:
        await dispatcher.dispatch(
            "owner",
            "write_file",
            {"path": "no.txt", "content": "no"},
            {"project_path": tmp_path},
            AsyncMock(),
        )
    assert exc.value.code == "approval_expired"
    assert not dispatcher.pending
    assert not (tmp_path / "no.txt").exists()


@pytest.mark.parametrize(
    "path",
    [
        "../outside",
        "..\\outside",
        "/absolute",
        "C:\\outside",
        "notes.txt:stream",
        "\\\\host\\share",
    ],
)
def test_containment_rejects_escape_paths(tmp_path, path):
    with pytest.raises(ServiceError):
        contained_path(tmp_path, path)


def test_project_restart_preserves_temporary_work(tmp_path):
    manager = ProjectManager(str(tmp_path))
    artifact = manager.get_current_project_path() / "cad" / "keep.stl"
    artifact.write_text("existing model")
    restarted = ProjectManager(str(tmp_path))
    assert artifact.read_text() == "existing model"
    assert restarted.current_project == "temp"


@pytest.mark.asyncio
async def test_socket_text_contract_no_audio(monkeypatch, tmp_path):
    import server

    emitted = []

    async def emit(event, data=None, room=None):
        emitted.append((event, data, room))

    service, _ = make_service([LLMResponse(text="Text is ready.")])
    monkeypatch.setattr(server, "conversation_service", service)
    monkeypatch.setattr(server.sio, "emit", emit)
    monkeypatch.setattr(server, "audio_loop", None)
    monkeypatch.setattr(
        server, "project_manager", SimpleNamespace(get_current_project_path=lambda: tmp_path)
    )
    monkeypatch.setitem(server.client_principals, "client", "owner")
    monkeypatch.setitem(server.SETTINGS, "face_auth_enabled", False)
    await server.user_input("client", {"text": "Hello"})
    assert (
        "transcription",
        {"sender": "INARA", "text": "Text is ready.", "request_id": emitted[1][1]["request_id"]},
        "client",
    ) in emitted
    assert emitted[0][1]["state"] == "processing"
    assert emitted[-1][1]["state"] == "idle"
    assert server.audio_loop is None


@pytest.mark.asyncio
async def test_direct_app_action_uses_shared_policy(monkeypatch):
    import server

    fake_agent = SimpleNamespace(
        handle_tool_call=AsyncMock(return_value=SimpleNamespace(success=True, message="Launched"))
    )
    monkeypatch.setattr(server, "desktop_agent", fake_agent)
    monkeypatch.setattr(server.sio, "emit", AsyncMock())
    monkeypatch.setitem(server.client_principals, "client", "owner")
    monkeypatch.setitem(server.SETTINGS, "face_auth_enabled", False)
    monkeypatch.setitem(server.SETTINGS["tool_permissions"], "launch_app", "deny")
    await server.launch_app("client", {"name": "notepad"})
    fake_agent.handle_tool_call.assert_not_awaited()
    assert server.sio.emit.call_args.args[1]["code"] == "permission_denied"
    monkeypatch.setitem(server.SETTINGS["tool_permissions"], "launch_app", False)
    await server.launch_app("client", {"name": "notepad"})
    fake_agent.handle_tool_call.assert_awaited_once()


@pytest.mark.asyncio
async def test_socket_rejects_missing_auth_token(monkeypatch):
    import server

    monkeypatch.setenv("INARA_SESSION_TOKEN", "test-only-token")
    assert await server.connect("client", {}, {"client_id": str(uuid.uuid4())}) is False


def test_server_lifespan_is_lean_and_cleans_tasks(monkeypatch, tmp_path):
    import server
    from fastapi.testclient import TestClient
    from core.reminder_store import ReminderStore

    monkeypatch.setattr(server, "reminder_store", ReminderStore(tmp_path))
    with TestClient(server.app) as client:
        response = client.get("/status")
        assert response.status_code == 200
        assert response.json()["text_ready"] is True
        assert not any(module in sys.modules for module in ["inara", "pyaudio", "cv2", "build123d"])
        assert any(not task.done() for task in server.background_tasks)
        running_tasks = list(server.background_tasks)
    assert running_tasks and all(task.done() for task in running_tasks)
    assert server.background_tasks == []


@pytest.mark.asyncio
async def test_socket_missing_key_and_invalid_payload(monkeypatch, tmp_path):
    import server

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(server, "conversation_service", ConversationService(server.dispatcher))
    monkeypatch.setattr(
        server, "project_manager", SimpleNamespace(get_current_project_path=lambda: tmp_path)
    )
    monkeypatch.setattr(server.sio, "emit", AsyncMock())
    monkeypatch.setitem(server.client_principals, "client", "owner")
    monkeypatch.setitem(server.SETTINGS, "face_auth_enabled", False)
    await server.user_input("client", {"text": "Hello"})
    errors = [call for call in server.sio.emit.call_args_list if call.args[0] == "error"]
    assert errors[-1].args[1]["code"] == "provider_not_configured"
    await server.user_input("client", {"text": 42})
    errors = [call for call in server.sio.emit.call_args_list if call.args[0] == "error"]
    assert errors[-1].args[1]["code"] == "invalid_request"


@pytest.mark.asyncio
async def test_sdk_adapter_preserves_signed_tool_content(monkeypatch, tmp_path):
    from google.genai import types
    from llm.gemini import GeminiProvider, _messages_to_gemini_contents
    from llm.base import Message, MessageRole

    provider = GeminiProvider(api_key="offline-test-key")
    assert provider._GeminiProvider__client is None
    content = types.Content(
        role="model",
        parts=[
            types.Part(
                function_call=types.FunctionCall(
                    name="read_file", args={"path": "notes.txt"}, id="call-1"
                ),
                thought_signature=b"offline-test-signature",
            )
        ],
    )
    response = types.GenerateContentResponse(candidates=[types.Candidate(content=content)])
    fake_client = SimpleNamespace(
        aio=SimpleNamespace(
            models=SimpleNamespace(generate_content=AsyncMock(return_value=response)),
            aclose=AsyncMock(),
        )
    )
    provider._GeminiProvider__client = fake_client
    dispatcher = ToolDispatcher(lambda: {})
    register_project_tools(dispatcher)
    result = await provider.generate(
        [Message(MessageRole.USER, "Read notes")],
        tools=[{"function_declarations": dispatcher.schemas()}],
    )
    assert result.tool_calls[0].name == "read_file"
    converted = _messages_to_gemini_contents(
        [
            Message(
                MessageRole.ASSISTANT,
                "",
                attachments=[{"type": "provider_content", "content": content}],
            )
        ]
    )
    assert converted[0].parts[0].thought_signature == b"offline-test-signature"
    await provider.close()
    fake_client.aio.aclose.assert_awaited_once()
