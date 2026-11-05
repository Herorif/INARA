"""TLS verification for outbound AI/telephony provider calls only.

Antivirus HTTPS scanning and corporate proxies re-sign traffic with a root that
Windows trusts but certifi does not, so provider calls verify against the OS
certificate store through an explicit ``truststore.SSLContext``.

Nothing global is patched (``truststore.inject_into_ssl`` is deliberately not
used): JARVIS's own pinned contexts, such as the mobile companion's
``ssl.create_default_context(cadata=...)`` and its TLS listener, keep standard
behaviour.

Usage at provider call sites:
  - httpx / Anthropic SDK: ``httpx.Client(verify=provider_ssl_context())`` or
    ``anthropic.AsyncAnthropic(http_client=httpx.AsyncClient(verify=ctx))``
  - google-genai: ``genai.Client(api_key=..., http_options=genai_http_options())``
"""

import logging
import ssl
import sys
import threading

_lock = threading.Lock()
_cache = {}


def provider_ssl_context():
    """Cached client context verifying against the Windows store (certifi fallback)."""
    with _lock:
        context = _cache.get("context")
        if context is None:
            try:
                import truststore

                context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                _cache["system_store"] = True
            except Exception as exc:  # ImportError or an unsupported platform/Python
                message = (
                    "System certificate store unavailable (%s); provider HTTPS uses "
                    "Python's bundled roots." % type(exc).__name__
                )
                logging.getLogger("jarvis.tls").warning(message)
                print(f"[TLS] {message}", file=sys.stderr)
                context = ssl.create_default_context()
                _cache["system_store"] = False
            _cache["context"] = context
        return context


def uses_system_store():
    provider_ssl_context()
    return _cache["system_store"]


def genai_http_options(**options):
    """google-genai HttpOptions mapping carrying the provider context.

    ``client_args.verify`` covers the sync httpx client; ``async_client_args``
    ``verify`` covers async httpx and ``ssl`` covers aiohttp and the Live API
    websocket (google-genai drops keys an httpx client does not accept).
    """
    context = provider_ssl_context()
    values = dict(options)
    values["client_args"] = {**values.get("client_args", {}), "verify": context}
    values["async_client_args"] = {
        **values.get("async_client_args", {}),
        "verify": context,
        "ssl": context,
    }
    return values
