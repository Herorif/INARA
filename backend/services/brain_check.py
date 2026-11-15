"""The owner's "Run a check" in Preferences > AI (S1 layer 7, docs/AI_PROVIDERS.md).

``BrainCheck.run(owner)`` sends one short, tool-free prompt through the chat route
(30 s cap) and then looks up the weather for the home town, timing each. It answers
``{ok: True, brain: {...}, weather: {...}}``: ``ok`` says the check ran; each half has its
own ``ok`` and, on failure, a ``code`` and a plain ``message``. The weather half is skipped
with ``code: "need_place"`` when no home town is saved.

It spends a few tokens, so it runs only when the owner presses the button. One
content-free log line records it: provider, model, the two timings and the outcome, never
the prompt, the reply or the place.
"""

import asyncio
import time
import uuid

from llm.base import Message, MessageRole
from llm.router import model_label
from services.log import get_logger
from services.tools import ServiceError
from services.usage import metered_generate

logger = get_logger(__name__)

CHECK_PROMPT = "Reply with the single word: ready."
BRAIN_TIMEOUT_S = 30.0
USAGE_FEATURE = "brain_check"
BRAIN_TIMED_OUT = "The brain did not answer within 30 seconds."
BRAIN_EMPTY = "The brain answered with nothing."
NEED_PLACE = "Set your home town above to include a weather check."
WEATHER_FAILED = "The weather service gave an unexpected answer."


def _ms(started, clock):
    return int((clock() - started) * 1000)


class BrainCheck:
    def __init__(self, router, weather, *, usage=None, project=None, clock=time.monotonic):
        # ``router``: a TaskRouter; ``weather``: a WeatherService (or a fake with ``lookup``);
        # ``usage``/``project``: meter the brain prompt like any other cloud request.
        self.router, self.weather = router, weather
        self.usage, self.project, self.clock = usage, project, clock

    async def run(self, owner):
        brain = await self.brain(owner)
        weather = await self.check_weather()
        if not brain["ok"]:
            outcome = "brain_" + brain["code"]
        elif weather["ok"] or weather.get("skipped"):
            outcome = "ok"
        else:
            outcome = "weather_" + weather["code"]
        logger.info(
            "brain_check provider=%s model=%s brain_ms=%s weather_ms=%s outcome=%s",
            brain.get("provider") or "-", brain.get("model") or "-",
            brain.get("ms", "-"), weather.get("ms", "-"), outcome,
        )
        return {"ok": True, "brain": brain, "weather": weather}

    async def brain(self, owner):
        route = self.router.route("chat")
        result = {"provider": route.provider, "model": route.model, "label": route.label}
        provider = None
        started = self.clock()
        try:
            provider = self.router.provider("chat", web_search=False)
            model = getattr(provider, "_model", None) or route.model
            result.update(model=model, label=model_label(model),
                          effort=getattr(provider, "effort", None)
                          if getattr(provider, "name", None) == "claude" else None)
            generate = metered_generate
            if self.usage is not None and self.project is not None:
                generate = self.usage.operation(
                    owner, self.project(), USAGE_FEATURE, uuid.uuid4()
                ).generate
            async with asyncio.timeout(BRAIN_TIMEOUT_S):
                response = await generate(provider, [Message(MessageRole.USER, CHECK_PROMPT)])
            result["ms"] = _ms(started, self.clock)
            if not getattr(response, "text", None):
                return {**result, "ok": False, "code": "empty_response", "message": BRAIN_EMPTY}
            return {**result, "ok": True}
        except TimeoutError:
            return {**result, "ok": False, "code": "brain_timeout", "message": BRAIN_TIMED_OUT,
                    "ms": _ms(started, self.clock)}
        except ServiceError as exc:
            return {**result, "ok": False, "code": exc.code, "message": str(exc),
                    "ms": _ms(started, self.clock)}
        except Exception as exc:
            from services.conversation import provider_failure

            # Never the SDK's own text: it can carry credentials or request data.
            error = provider_failure(provider, exc)
            return {**result, "ok": False, "code": error.code, "message": str(error),
                    "ms": _ms(started, self.clock)}
        finally:
            if provider is not None:
                try:
                    await provider.close()
                except Exception:
                    logger.warning("AI provider client did not close cleanly")

    async def check_weather(self):
        started = self.clock()
        try:
            found = await self.weather.lookup(None, "now")
        except Exception as exc:  # lookup never raises; a fake or a bug might
            logger.warning("Brain check weather failed (%s)", type(exc).__name__)
            return {"ok": False, "code": "unavailable", "message": WEATHER_FAILED,
                    "ms": _ms(started, self.clock)}
        ms = _ms(started, self.clock)
        if found.get("need_place"):
            return {"ok": False, "skipped": True, "code": "need_place", "message": NEED_PLACE}
        if "error" in found or "place" not in found:
            return {"ok": False, "code": found.get("error") or "unavailable",
                    "message": found.get("message") or WEATHER_FAILED, "ms": ms}
        from services.weather import display_name

        return {"ok": True, "place": display_name(found["place"]), "ms": ms}
