"""Twilio request signatures (``X-Twilio-Signature``).

Twilio's algorithm: take the full URL exactly as Twilio requested it (scheme,
host, path and query), append every POST parameter sorted by name as
``name + value``, HMAC-SHA1 the UTF-8 string with the account Auth Token and
base64 the digest. Like Twilio's own helper libraries, the URL is checked with
and without the scheme's default port because Twilio is not consistent about
including it. Comparison is constant time.
"""

import base64
import hashlib
import hmac
from urllib.parse import urlsplit, urlunsplit

DEFAULT_PORTS = {"https": 443, "wss": 443, "http": 80, "ws": 80}


def compute_signature(auth_token, url, params=None):
    """Base64 HMAC-SHA1 of ``url`` + sorted ``name+value`` pairs.

    ``params`` is a mapping or a sequence of ``(name, value)`` pairs. Repeated
    names contribute each distinct value in sorted order (Twilio's libraries).
    """
    if not isinstance(auth_token, str) or not auth_token:
        raise ValueError("An Auth Token is required.")
    grouped = {}
    items = params.items() if hasattr(params, "items") else (params or ())
    for name, value in items:
        grouped.setdefault(str(name), set()).add(str(value))
    data = url + "".join(
        name + value for name in sorted(grouped) for value in sorted(grouped[name])
    )
    digest = hmac.new(auth_token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


def url_variants(url):
    """The URL as given, without its default port, and with it."""
    parts = urlsplit(url)
    default = DEFAULT_PORTS.get(parts.scheme)
    host = parts.hostname or ""
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    userinfo = parts.netloc.rpartition("@")[0]
    prefix = userinfo + "@" if userinfo else ""
    variants = [url]
    if default is not None and host:
        port = parts.port
        if port is None or port == default:
            for netloc in (prefix + host, f"{prefix}{host}:{default}"):
                candidate = urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
                if candidate not in variants:
                    variants.append(candidate)
    return variants


def valid_signature(auth_token, urls, params, signature):
    """True when ``signature`` matches any accepted spelling of any of ``urls``."""
    if not isinstance(signature, str) or not signature or len(signature) > 128:
        return False
    if not isinstance(auth_token, str) or not auth_token:
        return False
    provided = signature.strip().encode("ascii", "replace")
    matched = False
    for url in urls:
        for candidate in url_variants(url):
            expected = compute_signature(auth_token, candidate, params).encode("ascii")
            # Evaluate every candidate so timing does not reveal which spelling matched.
            matched |= hmac.compare_digest(expected, provided)
    return matched
