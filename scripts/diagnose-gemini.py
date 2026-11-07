"""Time Gemini chat requests with the owner's saved key (developer diagnostic).

The first live run (7 Nov 2026) showed every chat request to gemini-3.8-flash stalling for
the full 45 s, while Live voice and the key check were fast. This separates the causes:
the network/key (a bare request is slow too) from JARVIS's request (only the one with its
tool list is slow). It prints timings and outcomes only: never the key, never a reply.

Run it from a normal terminal in the project folder (not inside the Claude desktop app,
which sees a private copy of AppData and so not the saved key), with JARVIS quit:

    .venv\\Scripts\\python.exe scripts\\diagnose-gemini.py
"""

import asyncio
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
TIMEOUT = 60.0
PROMPT = "Reply with exactly one word: ready"


def saved_key():
    from services.secrets import SecretStore
    from services.storage import Database

    value, source = SecretStore(Database()).resolve("gemini_api_key")
    return value, source


def tool_declarations():
    """JARVIS's real chat tools, built offline in a throwaway folder (no core, no devices)."""
    from application import create_application
    from llm.gemini import gemini_tools
    from services.storage import Database

    folder = Path(tempfile.mkdtemp(prefix="jarvis-diagnose-"))
    os.environ.setdefault("JARVIS_WAKE_WORD_DIR", str(folder / "no-wake-models"))
    app = create_application(
        settings={"face_auth_enabled": False, "tool_permissions": {}, "kasa_devices": []},
        project_root=folder / "project", legacy_data_dir=folder / "legacy",
        database=Database(folder / "private"),
    )
    schemas = app.dispatcher.schemas()
    return gemini_tools([{"function_declarations": schemas}]), len(schemas)


def outcome(exc):
    code = getattr(exc, "code", None)
    status = getattr(exc, "status", None)
    return " ".join(str(part) for part in (type(exc).__name__, code, status) if part)


async def timed(name, step):
    started = time.perf_counter()
    try:
        detail = await asyncio.wait_for(step(), TIMEOUT)
        result = "ok"
    except TimeoutError:
        detail, result = "", f"no answer within {TIMEOUT:.0f} s"
    except Exception as exc:
        detail, result = "", outcome(exc)
    elapsed = (time.perf_counter() - started) * 1000
    print(f"{name:<44} {elapsed:>9.0f} ms  {result}  {detail}")


async def main():
    from google import genai
    from google.genai import types

    from services.capability_profiles import model_id
    from services.tls import genai_http_options, provider_ssl_context

    key, source = saved_key()
    if not key:
        print("No Gemini key found. Save it in Preferences > AI, or run this outside the Claude app.")
        return 2
    model = model_id("text")
    proxies = [name for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy")
               if os.environ.get(name)]
    provider_ssl_context()
    from services import tls

    print(f"Model {model}; key from {source}; proxy variables: {', '.join(proxies) or 'none'}; "
          f"system certificate store: {tls._cache.get('system_store')}")
    client = genai.Client(api_key=key, http_options=genai_http_options(retry_options={"attempts": 1}))
    low = types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)

    async def list_models():
        count = 0
        async for _ in await client.aio.models.list(config={"page_size": 50}):
            count += 1
            if count >= 50:
                break
        return f"{count} models listed"

    async def bare(config):
        response = await client.aio.models.generate_content(model=model, contents=PROMPT, config=config)
        return f"{len(response.text or '')} characters"

    async def streamed():
        first = None
        started = time.perf_counter()
        chunks = 0
        async for _ in await client.aio.models.generate_content_stream(
            model=model, contents=PROMPT, config=types.GenerateContentConfig(thinking_config=low)
        ):
            chunks += 1
            if first is None:
                first = (time.perf_counter() - started) * 1000
        return f"first chunk after {first or 0:.0f} ms, {chunks} chunks"

    await timed("1. List models (like the key check)", list_models)
    await timed("2. Bare 'ready', LOW thinking", lambda: bare(types.GenerateContentConfig(thinking_config=low)))
    await timed("3. Bare 'ready', default thinking", lambda: bare(types.GenerateContentConfig()))
    await timed("4. Bare 'ready', streamed, LOW thinking", streamed)
    try:
        tools, count = tool_declarations()
    except Exception as exc:
        print(f"5. JARVIS's tools could not be built here: {outcome(exc)}")
        return 0
    with_tools = types.GenerateContentConfig(
        thinking_config=low, tools=tools,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    await timed(f"5. 'ready' with JARVIS's {count} tools, LOW", lambda: bare(with_tools))
    await client.aio.aclose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
