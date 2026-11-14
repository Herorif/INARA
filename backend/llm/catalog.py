"""The brain models the owner can choose (S2, docs/AI_PROVIDERS.md "Choosing the brain").

``BrainCatalog.models(settings)`` answers the owner-only ``brain_models`` route:
``{claude: [{id, label, note}], gemini: [{id, label}], efforts: [...]}``.

- Claude: a fixed list (Sonnet 5.5, Haiku 5.5). No network.
- Gemini: the account's ``gemini-*`` text models that support generateContent, from one
  google-genai ``client.aio.models.list`` call, bounded to 10 s and cached for an hour per
  key. Today's default text model and the saved ``assistant.gemini_model`` are always in
  the list; with no Gemini key, or when the call fails, the list is just those two.

The key is never logged or kept: the cache is keyed by a digest of it.
"""

import asyncio
import hashlib
import re
import time

from services.capability_profiles import model_id, provider_key
from services.log import get_logger

from .router import BRAIN_MODEL, EFFORTS, FAST_MODEL, gemini_model, model_label

logger = get_logger(__name__)

CLAUDE_CHOICES = (
    {"id": BRAIN_MODEL, "label": model_label(BRAIN_MODEL), "note": "Smartest"},
    {"id": FAST_MODEL, "label": model_label(FAST_MODEL), "note": "Fastest, cheapest"},
)
GEMINI_ID = re.compile(r"^gemini-[A-Za-z0-9._-]+$")
# Models that answer generateContent but are not chat text models.
NOT_TEXT = ("tts", "live", "embedding", "image", "audio")
CACHE_SECONDS = 3600.0
# A failed listing is retried after this, so a settings page does not wait 10 s each open.
FAILURE_SECONDS = 300.0
LIST_TIMEOUT = 10.0
MAX_MODELS = 500


def text_model_id(model):
    """The bare id of a listed google-genai ``Model`` when it is a Gemini chat text model."""
    name = getattr(model, "name", None)
    if not isinstance(name, str):
        return None
    model_id_ = name.removeprefix("models/")
    actions = getattr(model, "supported_actions", None) or ()
    if (
        len(model_id_) > 80
        or not GEMINI_ID.match(model_id_)
        or "generateContent" not in actions
        or any(word in model_id_ for word in NOT_TEXT)
    ):
        return None
    return model_id_


def _saved_gemini(settings):
    assistant = (settings or {}).get("assistant") if isinstance(settings, dict) else None
    value = assistant.get("gemini_model") if isinstance(assistant, dict) else None
    if isinstance(value, str) and len(value) <= 80 and GEMINI_ID.match(value):
        return value
    return None


def default_client(key):
    from google import genai

    from services.tls import genai_http_options

    return genai.Client(
        api_key=key,
        http_options=genai_http_options(
            timeout=int(LIST_TIMEOUT * 1000), retry_options={"attempts": 1}
        ),
    )


class BrainCatalog:
    def __init__(self, key=provider_key, client_factory=default_client, clock=time.monotonic):
        self._key, self._client_factory, self._clock = key, client_factory, clock
        self._cache = None  # (key digest, expires at, tuple of ids or None on failure)
        self._lock = asyncio.Lock()

    async def models(self, settings):
        fetched = await self.gemini_ids()
        ids = set(fetched or ())
        ids.add(model_id("text"))
        ids.add(gemini_model(settings))
        saved = _saved_gemini(settings)
        if saved:
            ids.add(saved)
        return {
            "claude": [dict(choice) for choice in CLAUDE_CHOICES],
            "gemini": [{"id": item, "label": model_label(item)} for item in sorted(ids)],
            "efforts": list(EFFORTS),
        }

    async def gemini_ids(self):
        """The account's Gemini text model ids (cached), or None without a key or on failure."""
        key = self._key()
        if not key:
            return None
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        async with self._lock:
            cached = self._cache
            if cached and cached[0] == digest and self._clock() < cached[1]:
                return cached[2]
            try:
                ids = await asyncio.wait_for(self._list(key), LIST_TIMEOUT)
            except Exception as exc:
                logger.warning("Gemini model list unavailable (%s)", type(exc).__name__)
                self._cache = (digest, self._clock() + FAILURE_SECONDS, None)
                return None
            self._cache = (digest, self._clock() + CACHE_SECONDS, ids)
            return ids

    async def _list(self, key):
        client = self._client_factory(key)
        ids = []
        try:
            pager = await client.aio.models.list(config={"page_size": 100})
            count = 0
            async for model in pager:
                count += 1
                if count > MAX_MODELS:
                    break
                found = text_model_id(model)
                if found and found not in ids:
                    ids.append(found)
        finally:
            close = getattr(client.aio, "aclose", None)
            if close is not None:
                try:
                    await close()
                except Exception:
                    pass
        return tuple(ids)
