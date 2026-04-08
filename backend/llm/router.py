"""
LLM Router — routes tasks to the appropriate provider.

Allows INARA to use different LLMs for different capabilities:
- Gemini for real-time voice (Native Audio)
- Claude for complex reasoning and tool orchestration
- Any provider for simple tasks
"""

from typing import Optional

from .base import BaseLLMProvider, BaseVoiceProvider


class LLMRouter:
    """Routes LLM requests to the appropriate provider based on task type."""

    def __init__(self):
        self._providers: dict[str, BaseLLMProvider] = {}
        self._voice_provider: Optional[BaseVoiceProvider] = None
        self._default_provider: Optional[str] = None

        # Task-to-provider routing
        self._task_routes: dict[str, str] = {}

    def register_provider(self, provider: BaseLLMProvider, default: bool = False):
        """Register an LLM provider."""
        self._providers[provider.name] = provider
        if default or self._default_provider is None:
            self._default_provider = provider.name

    def register_voice_provider(self, provider: BaseVoiceProvider):
        """Register the voice-capable provider."""
        self._voice_provider = provider

    def set_route(self, task: str, provider_name: str):
        """Route a specific task type to a provider.

        Example:
            router.set_route("cad_generation", "gemini")
            router.set_route("complex_reasoning", "claude")
        """
        if provider_name not in self._providers:
            raise ValueError(f"Unknown provider: {provider_name}")
        self._task_routes[task] = provider_name

    def get_provider(self, task: Optional[str] = None) -> BaseLLMProvider:
        """Get the provider for a given task, or the default."""
        if task and task in self._task_routes:
            name = self._task_routes[task]
        else:
            name = self._default_provider

        if name is None or name not in self._providers:
            raise RuntimeError("No LLM provider configured")

        return self._providers[name]

    def get_voice_provider(self) -> BaseVoiceProvider:
        """Get the voice-capable provider."""
        if self._voice_provider is None:
            raise RuntimeError("No voice provider configured")
        return self._voice_provider

    @property
    def default_provider(self) -> Optional[BaseLLMProvider]:
        if self._default_provider:
            return self._providers.get(self._default_provider)
        return None

    @property
    def providers(self) -> dict[str, BaseLLMProvider]:
        return dict(self._providers)

    async def close_all(self):
        """Shut down all providers."""
        for provider in self._providers.values():
            await provider.close()
        if self._voice_provider and hasattr(self._voice_provider, "disconnect_voice"):
            await self._voice_provider.disconnect_voice()
