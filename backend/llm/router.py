"""Task router: which provider and model serve each kind of AI work.

- ``chat``: the chosen Claude model (``assistant.claude_model``, Sonnet 5.5 by default) at
  the chosen effort (``assistant.effort``, medium by default) when an Anthropic key is
  configured, otherwise the chosen Gemini text model (``assistant.gemini_model``).
- ``fast`` / ``summary``: Claude Haiku 5.5 at low effort when an Anthropic key is
  configured, otherwise the default Gemini text model.
- ``transcription``: always Gemini.

The ``assistant.brain`` setting ("auto", "claude" or "gemini") overrides the
automatic choice for chat and fast work. Choosing "claude" without an Anthropic
key is a configuration error, never a silent fallback. ``assistant.web_search``
(default on) gives the chat route Claude's web search and web fetch. The env overrides
``BRAIN_MODEL`` and ``JARVIS_TEXT_MODEL`` win over the saved models. Nothing here
touches an SDK or the network; providers are created on request.
"""

from dataclasses import dataclass

from services import env
from services.capability_profiles import anthropic_key, model_id, provider_key
from services.tools import ServiceError

BRAIN_MODEL = "claude-sonnet-5-5"
FAST_MODEL = "claude-haiku-5-5"
BRAIN_SETTINGS = ("auto", "claude", "gemini")
CLAUDE_MODELS = (BRAIN_MODEL, FAST_MODEL)
EFFORTS = ("low", "medium", "high")
DEFAULT_EFFORT = "medium"
FAST_EFFORT = "low"
TASKS = ("chat", "fast", "summary", "transcription")

MODEL_LABELS = {
    "claude-sonnet-5-5": "Claude Sonnet 5.5",
    "claude-haiku-5-5": "Claude Haiku 5.5",
}


def _assistant(settings):
    assistant = (settings or {}).get("assistant") if isinstance(settings, dict) else None
    return assistant if isinstance(assistant, dict) else {}


def claude_model_setting(settings):
    """``assistant.claude_model``; a missing or stale value reads as Sonnet 5.5."""
    value = _assistant(settings).get("claude_model")
    return value if value in CLAUDE_MODELS else BRAIN_MODEL


def brain_model(settings=None):
    """The chat model: env ``BRAIN_MODEL`` wins, else ``assistant.claude_model``."""
    return env.getenv("BRAIN_MODEL", "").strip() or claude_model_setting(settings)


def effort_setting(settings):
    """``assistant.effort`` for the Claude brain; a missing or stale value reads as medium."""
    value = _assistant(settings).get("effort")
    return value if value in EFFORTS else DEFAULT_EFFORT


def gemini_model(settings=None):
    """The Gemini chat model: env ``JARVIS_TEXT_MODEL`` wins, else ``assistant.gemini_model``,
    else today's default text model (an empty or non-string saved value never reaches Google)."""
    override = env.getenv("JARVIS_TEXT_MODEL", "").strip()
    if override:
        return override
    value = _assistant(settings).get("gemini_model")
    value = value.strip() if isinstance(value, str) else ""
    return value if value.startswith("gemini-") else model_id("text")


def fast_model():
    return env.getenv("FAST_MODEL", "").strip() or FAST_MODEL


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
    value = _assistant(settings).get("brain", "auto")
    return value if value in BRAIN_SETTINGS else "auto"


def web_search_setting(settings):
    """``assistant.web_search`` (default on): offer Claude web search and web fetch."""
    value = _assistant(settings).get("web_search", True)
    return value if isinstance(value, bool) else True


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
        settings = self.settings()
        if task == "transcription":
            model = model_id("speech")
        else:
            model = gemini_model(settings) if task == "chat" else model_id("text")
        gemini = Route(task, "gemini", model, bool(self._gemini()))
        if task == "transcription":
            return gemini
        choice = brain_setting(settings)
        has_claude = bool(self._anthropic())
        if choice == "gemini" or (choice == "auto" and not has_claude):
            return gemini
        model = brain_model(settings) if task == "chat" else fast_model()
        return Route(task, "claude", model, has_claude)

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

            # Web search is for the brain's own turns only: fast and summary work (call
            # triage, summaries) never offers it; a history that already holds search
            # results still declares the tools so it can replay (llm/claude.py).
            settings = self.settings()
            web = task == "chat" and web_search_setting(settings)
            # The owner's effort is for the brain's chat turns; fast work stays at low.
            effort = effort_setting(settings) if task == "chat" else FAST_EFFORT
            return ClaudeProvider(api_key=key, model=route.model, effort=effort, web_search=web)
        key = self._gemini()
        if not key:
            raise ServiceError(
                "provider_not_configured",
                "Add an Anthropic or Gemini API key in Setup (AI providers) or Preferences "
                "to enable AI conversation.",
            )
        from llm.gemini import GeminiProvider

        # Effort does not apply to Gemini: it manages its own thinking (llm/gemini.py).
        return GeminiProvider(api_key=key, model=route.model)

    def status(self):
        """Content-free summary for the capability center and status events."""
        chat, fast = self.route("chat"), self.route("fast")
        settings = self.settings()
        return {
            "setting": brain_setting(settings),
            # The saved choices, whichever brain is active (effort applies to Claude only).
            "effort": effort_setting(settings),
            "claude_model": brain_model(settings),
            "gemini_model": gemini_model(settings),
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
