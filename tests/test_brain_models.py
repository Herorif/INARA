"""S2 brain model and effort settings: router matrix, request effort, settings validation and
the owner-only brain_models route. Offline: Anthropic and google-genai clients are faked."""

import copy
import uuid
from types import SimpleNamespace

import pytest
from anthropic.types.beta import BetaMessage
from pydantic import ValidationError

from llm.base import Message, MessageRole
from llm.catalog import BrainCatalog, text_model_id
from llm.router import TaskRouter, brain_model, effort_setting, gemini_model
from services.settings import ASSISTANT_DEFAULTS, SettingsPatch, SettingsService, SettingsStore

SONNET, HAIKU, FLASH = "claude-sonnet-5-5", "claude-haiku-5-5", "gemini-3.8-flash"
KEYS = {
    "anthropic_only": ("sk-ant-offline", None),
    "gemini_only": (None, "AIza-offline"),
    "both": ("sk-ant-offline", "AIza-offline"),
    "none": (None, None),
}


@pytest.fixture(autouse=True)
def no_model_overrides(monkeypatch):
    for name in ("JARVIS_BRAIN_MODEL", "INARA_BRAIN_MODEL", "JARVIS_TEXT_MODEL",
                 "INARA_TEXT_MODEL", "JARVIS_FAST_MODEL", "INARA_FAST_MODEL"):
        monkeypatch.delenv(name, raising=False)


def router(assistant=None, keys="both"):
    anthropic, gemini = KEYS[keys]
    settings = {"assistant": assistant} if assistant is not None else {}
    return TaskRouter(lambda: settings, anthropic=lambda: anthropic, gemini=lambda: gemini)


# --- router matrix -------------------------------------------------------------------


@pytest.mark.parametrize("keys", KEYS)
@pytest.mark.parametrize("brain", ["auto", "claude", "gemini"])
@pytest.mark.parametrize("claude_model", [SONNET, HAIKU])
@pytest.mark.parametrize("effort", ["low", "medium", "high"])
def test_router_matrix(keys, brain, claude_model, effort):
    has_claude, has_gemini = (bool(key) for key in KEYS[keys])
    selected = router(
        {"brain": brain, "claude_model": claude_model, "effort": effort,
         "gemini_model": "gemini-3.8-pro"},
        keys,
    )
    uses_claude = brain == "claude" or (brain == "auto" and has_claude)
    chat, fast = selected.route("chat"), selected.route("fast")
    if uses_claude:
        assert (chat.provider, chat.model, chat.configured) == ("claude", claude_model, has_claude)
        assert (fast.provider, fast.model) == ("claude", HAIKU)
    else:
        assert (chat.provider, chat.model, chat.configured) == (
            "gemini", "gemini-3.8-pro", has_gemini
        )
        assert (fast.provider, fast.model) == ("gemini", FLASH)
    assert selected.route("transcription").provider == "gemini"

    configured = has_claude if uses_claude else has_gemini
    if not configured:
        with pytest.raises(Exception) as exc:
            selected.provider("chat")
        assert exc.value.code == "provider_not_configured"
        return
    provider = selected.provider("chat")
    if uses_claude:
        assert provider.name == "claude" and provider._model == claude_model
        assert provider.effort == effort
        quick = selected.provider("fast")
        assert (quick._model, quick.effort) == (HAIKU, "low")
    else:
        assert provider.name == "gemini" and provider._model == "gemini-3.8-pro"
        assert not hasattr(provider, "effort")
    status = selected.status()
    assert status["effort"] == effort and status["claude_model"] == claude_model
    assert status["gemini_model"] == "gemini-3.8-pro"
    assert status["model"] == chat.model


def test_defaults_and_stale_values_read_as_defaults():
    for assistant in (None, {}, {"claude_model": "claude-opus-9", "effort": "xhigh",
                                 "gemini_model": ""}, {"gemini_model": 7},
                      {"gemini_model": "gpt-5"}):
        selected = router(assistant)
        provider = selected.provider("chat")
        assert (provider._model, provider.effort) == (SONNET, "medium")
        assert router({**(assistant or {}), "brain": "gemini"}).provider("chat")._model == FLASH
    assert brain_model() == SONNET and effort_setting(None) == "medium"
    assert gemini_model({"assistant": {"gemini_model": "  "}}) == FLASH


def test_env_overrides_win_over_saved_models(monkeypatch):
    monkeypatch.setenv("JARVIS_BRAIN_MODEL", "claude-env-model")
    monkeypatch.setenv("JARVIS_TEXT_MODEL", "gemini-env-model")
    assert router({"claude_model": HAIKU}).route("chat").model == "claude-env-model"
    assert router({"brain": "gemini", "gemini_model": "gemini-3.8-pro"}).route(
        "chat").model == "gemini-env-model"
    # Fast work stays on Haiku at low effort whatever the brain model.
    fast = router({"claude_model": SONNET, "effort": "high"}).provider("fast")
    assert (fast._model, fast.effort) == (HAIKU, "low")


# --- the Claude request carries the chosen effort --------------------------------------


class FakeStream:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def __aiter__(self):
        for block in self.response.content:
            yield SimpleNamespace(type="text", text=block.text)

    async def get_final_message(self):
        return self.response


class FakeClient:
    def __init__(self, model):
        self.model, self.requests = model, []
        self.beta = SimpleNamespace(messages=self)

    def stream(self, **params):
        self.requests.append(copy.deepcopy(params))
        return FakeStream(BetaMessage.model_validate({
            "id": "msg_" + uuid.uuid4().hex[:8], "type": "message", "role": "assistant",
            "model": self.model, "content": [{"type": "text", "text": "Done, sir."}],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }))

    async def close(self):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("claude_model", [SONNET, HAIKU])
@pytest.mark.parametrize("effort", ["low", "medium", "high"])
async def test_claude_request_carries_the_chosen_effort(claude_model, effort):
    provider = router({"claude_model": claude_model, "effort": effort}).provider("chat")
    provider._client = client = FakeClient(claude_model)
    response = await provider.generate([Message(MessageRole.USER, "Hello")])
    assert response.text == "Done, sir."
    sent = client.requests[0]
    assert sent["model"] == claude_model and sent["output_config"] == {"effort": effort}
    assert sent["thinking"]["type"] == "adaptive"


# --- settings ------------------------------------------------------------------------


def test_settings_defaults_merge_and_validate():
    assert ASSISTANT_DEFAULTS["claude_model"] == SONNET
    assert ASSISTANT_DEFAULTS["effort"] == "medium"
    assert ASSISTANT_DEFAULTS["gemini_model"] == FLASH
    store = {"tool_permissions": {}, "assistant": {"brain": "claude"}}
    service = SettingsService(store, SettingsStore(None), [])
    service.apply(SettingsPatch(assistant={"address": "sir"}))
    assert (store["assistant"]["claude_model"], store["assistant"]["effort"],
            store["assistant"]["gemini_model"]) == (SONNET, "medium", FLASH)
    service.apply(SettingsPatch.model_validate(
        {"assistant": {"claude_model": HAIKU, "effort": "high", "gemini_model": "gemini-3.8-pro"}}
    ))
    assert store["assistant"]["claude_model"] == HAIKU and store["assistant"]["effort"] == "high"
    assert store["assistant"]["gemini_model"] == "gemini-3.8-pro"
    assert store["assistant"]["brain"] == "claude"
    for bad in (
        {"effort": "xhigh"}, {"effort": "max"}, {"effort": "Medium"}, {"effort": None},
        {"effort": 1}, {"claude_model": "claude-opus-9"}, {"claude_model": None},
        {"gemini_model": ""}, {"gemini_model": "gpt-5"}, {"gemini_model": "gemini-"},
        {"gemini_model": "gemini-" + "x" * 80}, {"gemini_model": "gemini-3.8 flash"},
        {"gemini_model": "gemini-3.8\nflash"}, {"gemini_model": None}, {"gemini_model": 3},
    ):
        with pytest.raises(ValidationError):
            SettingsPatch.model_validate({"assistant": bad})


# --- brain_models --------------------------------------------------------------------


def listed(name, actions=("generateContent",)):
    return SimpleNamespace(name=name, supported_actions=list(actions))


LISTING = [
    listed("models/gemini-3.8-flash"),
    listed("models/gemini-3.8-pro"),
    listed("models/gemini-3.8-flash-tts"),
    listed("models/gemini-3.8-live"),
    listed("models/gemini-embedding-2", ("embedContent",)),
    listed("models/gemini-3.8-flash-image"),
    listed("models/gemini-3.8-flash-native-audio"),
    listed("models/gemma-4-27b"),
    listed("models/imagen-5", ("predict",)),
    listed("models/gemini-3.8-ultra", ()),
    SimpleNamespace(name=None, supported_actions=None),
]


class FakePager:
    def __init__(self, items):
        self.items = items

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for item in self.items:
            yield item


class FakeGenai:
    def __init__(self, items=LISTING, error=None):
        self.items, self.error, self.calls, self.closed = items, error, [], 0
        self.aio = SimpleNamespace(models=self, aclose=self.aclose)

    async def list(self, config=None):
        self.calls.append(config)
        if self.error:
            raise self.error
        return FakePager(self.items)

    async def aclose(self):
        self.closed += 1


def catalog(client, key="AIza-offline", clock=None):
    keys, factory_keys = [key], []

    def factory(value):
        factory_keys.append(value)
        return client

    made = BrainCatalog(key=lambda: keys[0], client_factory=factory,
                        clock=clock or (lambda: 0.0))
    return made, keys, factory_keys


def ids(result):
    return [item["id"] for item in result["gemini"]]


def test_text_model_filter():
    assert [text_model_id(model) for model in LISTING] == [
        "gemini-3.8-flash", "gemini-3.8-pro", None, None, None, None, None, None, None,
        None, None,
    ]


@pytest.mark.asyncio
async def test_brain_models_lists_filters_and_caches():
    now = [0.0]
    client = FakeGenai()
    made, keys, factory_keys = catalog(client, clock=lambda: now[0])
    settings = {"assistant": {"gemini_model": "gemini-3.8-saved"}}
    result = await made.models(settings)
    assert result["claude"] == [
        {"id": SONNET, "label": "Claude Sonnet 5.5", "note": "Smartest"},
        {"id": HAIKU, "label": "Claude Haiku 5.5", "note": "Fastest, cheapest"},
    ]
    assert result["efforts"] == ["low", "medium", "high"]
    assert ids(result) == ["gemini-3.8-flash", "gemini-3.8-pro", "gemini-3.8-saved"]
    assert result["gemini"][1] == {"id": "gemini-3.8-pro", "label": "Gemini 3.8 Pro"}
    assert factory_keys == ["AIza-offline"] and client.closed == 1
    # Cached for an hour per key.
    now[0] = 3599.0
    await made.models({})
    assert len(client.calls) == 1
    now[0] = 3601.0
    assert ids(await made.models({})) == ["gemini-3.8-flash", "gemini-3.8-pro"]
    assert len(client.calls) == 2
    keys[0] = "AIza-other"
    await made.models({})
    assert len(client.calls) == 3


@pytest.mark.asyncio
async def test_brain_models_without_key_or_on_failure_lists_default_and_saved():
    client = FakeGenai()
    made, keys, factory_keys = catalog(client, key=None)
    settings = {"assistant": {"gemini_model": "gemini-3.8-pro"}}
    assert ids(await made.models(settings)) == ["gemini-3.8-flash", "gemini-3.8-pro"]
    assert factory_keys == [] and client.calls == []

    now = [0.0]
    failing = FakeGenai(error=RuntimeError("boom"))
    made, _, _ = catalog(failing, clock=lambda: now[0])
    assert ids(await made.models({})) == ["gemini-3.8-flash"]
    assert ids(await made.models({"assistant": {"gemini_model": "bad id"}})) == [
        "gemini-3.8-flash"
    ]
    assert len(failing.calls) == 1 and failing.closed == 1  # failure retried after 5 min
    now[0] = 301.0
    failing.error = None
    assert ids(await made.models({})) == ["gemini-3.8-flash", "gemini-3.8-pro"]


@pytest.mark.asyncio
async def test_brain_models_listing_is_bounded(monkeypatch):
    import asyncio

    import llm.catalog as module

    class Slow(FakeGenai):
        async def list(self, config=None):
            await asyncio.sleep(5)

    monkeypatch.setattr(module, "LIST_TIMEOUT", 0.05)
    made, _, _ = catalog(Slow())
    assert ids(await made.models({})) == ["gemini-3.8-flash"]


@pytest.mark.asyncio
async def test_brain_models_route_is_owner_only(application_factory):
    app = application_factory()
    app.sessions.principals.update({"client": "owner", "tray": "owner", "second": "other"})
    app.sessions.roles.update({"client": "renderer", "tray": "resident", "second": "renderer"})
    app.sessions.local_owner = "owner"
    client = FakeGenai()
    app.settings_transport.catalog, _, _ = catalog(client)
    handler = app.sio.handlers["/"]["brain_models"]
    for sid, code in (("unknown", "authentication_required"), ("tray", "authentication_required"),
                      ("second", "permission_denied")):
        result = await handler(sid, {})
        assert result["ok"] is False and result["code"] == code
    assert client.calls == []
    result = await handler("client", {})
    assert result["ok"] is True and ids(result) == ["gemini-3.8-flash", "gemini-3.8-pro"]
    assert (await handler("client", {"x": 1}))["code"] == "invalid_arguments"
    app.settings["face_auth_enabled"] = True
    assert (await handler("client"))["code"] == "authentication_required"
