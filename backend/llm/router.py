"""Task router: which provider and model serve each kind of AI work.

- ``chat``: Claude Sonnet 5.5 (the brain) when an Anthropic key is configured,
  otherwise the Gemini text model.
- ``fast`` / ``summary``: Claude Haiku 5.5 when an Anthropic key is configured,
  otherwise the Gemini text model.
- ``transcription``: always Gemini.

The ``assistant.brain`` setting ("auto", "claude" or "gemini") overrides the
automatic choice for chat and fast work. Choosing "claude" without an Anthropic
key is a configuration error, never a silent fallback. Nothing here touches an
SDK or the network; providers are created on request.
"""

import os
from dataclasses import dataclass

from services.capability_profiles import anthropic_key, model_id, provider_key
from services.tools import ServiceError

BRAIN_MODEL = "claude-sonnet-5-5"
FAST_MODEL = "claude-haiku-5-5"
BRAIN_SETTINGS = ("auto", "claude", "gemini")
TASKS = ("chat", "fast", "summary", "transcription")

MODEL_LABELS = {
    "claude-sonnet-5-5": "Claude Sonnet 5.5",
    "claude-haiku-5-5": "Claude Haiku 5.5",
}


def brain_model():
    return os.getenv("INARA_BRAIN_MODEL", "").strip() or BRAIN_MODEL


def fast_model():
    return os.getenv("INARA_FAST_MODEL", "").strip() or FAST_MODEL


def model_label(model):
    if not model:
        return None
    if model in MODEL_LABELS:
        return MODEL_LABELS[model]
    if model.startswith("gemini-"):
        return "Gemini " + model.removeprefix("gemini-").replace("-", " ").title()
    return model


@dataclass(frozen=True)
class Route:
    task: str
    provider: str  # "claude" or "gemini"
    model: str
    configured: bool

    @property
    def label(self):
        return model_label(self.model)


def brain_setting(settings):
    assistant = (settings or {}).get("assistant") or {}
    value = assistant.get("brain", "auto") if isinstance(assistant, dict) else "auto"
    return value if value in BRAIN_SETTINGS else "auto"


class TaskRouter:
    def __init__(self, settings=None, anthropic=anthropic_key, gemini=provider_key):
        # ``settings`` is a callable returning the live settings dict (or None).
        self._settings = settings or (lambda: {})
        self._anthropic, self._gemini = anthropic, gemini

    def settings(self):
        return self._settings() or {}

    def route(self, task):
        if task not in TASKS:
            raise ValueError(f"Unknown AI task: {task}")
        gemini = Route(task, "gemini", model_id("speech" if task == "transcription" else "text"),
                       bool(self._gemini()))
        if task == "transcription":
            return gemini
        choice = brain_setting(self.settings())
        has_claude = bool(self._anthropic())
        if choice == "gemini" or (choice == "auto" and not has_claude):
            return gemini
        return Route(task, "claude", brain_model() if task == "chat" else fast_model(), has_claude)

    def provider(self, task):
        """Create the provider for ``task`` or raise a clear configuration error."""
        route = self.route(task)
        if route.provider == "claude":
            key = self._anthropic()
            if not key:
                raise ServiceError(
                    "provider_not_configured",
                    "The assistant is set to use Claude, but no Anthropic API key is saved. "
                    "Add one in Setup (AI providers) or Preferences, or set the assistant "
                    "brain to Auto.",
                )
            from llm.claude import ClaudeProvider

            return ClaudeProvider(api_key=key, model=route.model)
        key = self._gemini()
        if not key:
            raise ServiceError(
                "provider_not_configured",
                "Add an Anthropic or Gemini API key in Setup (AI providers) or Preferences "
                "to enable AI conversation.",
            )
        from llm.gemini import GeminiProvider

        return GeminiProvider(api_key=key, model=route.model)

    def status(self):
        """Content-free summary for the capability center and status events."""
        chat, fast = self.route("chat"), self.route("fast")
        return {
            "setting": brain_setting(self.settings()),
            "provider": chat.provider,
            "model": chat.model,
            "label": chat.label,
            "configured": chat.configured,
            "fast_provider": fast.provider,
            "fast_model": fast.model,
            "fast_label": fast.label,
            "transcription_model": self.route("transcription").model,
        }


class LLMRouter:
    """Provider registry kept only for the archived ``core/server.py`` reference code."""

    def __init__(self):
        self._providers, self._routes, self._default = {}, {}, None
        self._voice_provider = None

    def register_provider(self, provider, default=False):
        self._providers[provider.name] = provider
        if default or self._default is None:
            self._default = provider.name

    def register_voice_provider(self, provider):
        self._voice_provider = provider

    def set_route(self, task, provider_name):
        if provider_name not in self._providers:
            raise ValueError(f"Unknown provider: {provider_name}")
        self._routes[task] = provider_name

    def get_provider(self, task=None):
        name = self._routes.get(task, self._default)
        if name not in self._providers:
            raise RuntimeError("No LLM provider configured")
        return self._providers[name]

    def get_voice_provider(self):
        if self._voice_provider is None:
            raise RuntimeError("No voice provider configured")
        return self._voice_provider

    async def close_all(self):
        for provider in self._providers.values():
            await provider.close()
