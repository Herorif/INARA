"""Tool groups: which optional groups of brain tools a turn declares (S1.3, docs/WORLD_VIEW.md
"When the brain is offered the globe").

The **world group** is ``world_show``, ``world_tour`` and every God's Eye View tool
(``mcp__gev__*``). A turn declares it only when

- the request mentions the globe (a whole word from ``WORLD_WORDS``, any case, or "show me"
  followed by a place-like phrase), or
- the owner's World page is open, or
- the previous assistant turn of this conversation used a world tool (a follow-up such as
  "now zoom closer").

A plain weather question ("what's the weather in KL", "cuaca hari ini") never brings it in:
the weather tool answers those. Tools outside the group are always declared. Everything here
is pure: no I/O, no logging (the request text is never logged).
"""

import re

WORLD_GROUP = "world"
WORLD_TOOLS = frozenset({"world_show", "world_tour"})
WORLD_PREFIX = "mcp__gev__"
# Whole words that bring in the world group (matched case-insensitively, with a plural "s").
WORLD_WORDS = (
    "globe", "world", "map", "flights", "flight", "planes", "aircraft", "ships", "vessels",
    "satellites", "satellite", "earthquake", "quake", "wildfire", "fires", "tour",
    # Malay: globe/world, map, earthquake, ship, satellite, flight.
    "dunia", "peta", "gempa", "kapal", "satelit", "penerbangan",
)
# "show me" + a place-like phrase: the phrase leads with one of these...
PLACE_LEADS = frozenset({"where", "around", "over", "near", "above", "across"})
# ...or with a capitalised name ("Penang", "KL", "the Strait of Malacca"), or holds one of
# these words; never when it leads with one of NOT_PLACES or names the weather.
PLACE_WORDS = frozenset({
    "city", "town", "country", "island", "coast", "beach", "strait", "sea", "ocean", "bay",
    "river", "lake", "mountain", "volcano", "airport", "port", "harbour", "harbor", "border",
    "continent", "capital", "peninsula", "region",
})
NOT_PLACES = frozenset({
    "my", "your", "our", "his", "her", "their", "this", "that", "these", "those", "it", "them",
    "how", "what", "why", "when", "who", "which", "a", "an", "some", "all", "any", "more",
})
WEATHER_WORDS = frozenset({
    "weather", "forecast", "rain", "raining", "rainy", "temperature", "humidity", "humid",
    "sunny", "cuaca", "hujan", "ramalan", "suhu",
})

_WORLD = re.compile(
    r"\b(?:" + "|".join(re.escape(word) for word in WORLD_WORDS) + r")s?\b", re.IGNORECASE
)
_SHOW_ME = re.compile(r"\bshow\s+me\b([^.?!;,\n]*)", re.IGNORECASE)
_WORD = re.compile(r"[^\W\d_][\w'-]*")


def in_world_group(name):
    """True for ``world_show``, ``world_tour`` and every ``mcp__gev__*`` tool."""
    return isinstance(name, str) and (name in WORLD_TOOLS or name.startswith(WORLD_PREFIX))


def _place_like(phrase, shouting):
    words = _WORD.findall(phrase)
    lowered = [word.lower() for word in words]
    if any(word in WEATHER_WORDS for word in lowered):
        return False
    if lowered and lowered[0] == "the":
        words, lowered = words[1:], lowered[1:]
    if not words:
        return False
    first = lowered[0]
    if first in PLACE_LEADS:
        return len(words) > 1
    if first in NOT_PLACES:
        return False
    if words[0][0].isupper() and not shouting:
        return True
    return any(word in PLACE_WORDS or word.removesuffix("s") in PLACE_WORDS for word in lowered)


def mentions_world(text):
    """True when the request asks about or to see the globe (see the module docstring)."""
    if not isinstance(text, str) or not text:
        return False
    if _WORLD.search(text):
        return True
    shouting = text.upper() == text
    return any(_place_like(match.group(1), shouting) for match in _SHOW_ME.finditer(text))


def _entry_used_world(entry):
    if WORLD_GROUP in (entry.get("tool_groups") or ()):
        return True
    # Claude turns keep their exact messages: look for a world tool_use among them.
    for message in entry.get("claude") or ():
        content = message.get("content") if isinstance(message, dict) else None
        for block in content if isinstance(content, list) else ():
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_use"
                and in_world_group(block.get("name"))
            ):
                return True
    return False


def used_world_last(history):
    """True when the conversation's last assistant entry used a world tool."""
    for entry in reversed(history or ()):
        if isinstance(entry, dict) and entry.get("role") == "assistant":
            return _entry_used_world(entry)
    return False


def offer_world(text, *, page_open=False, history=()):
    """Whether this turn declares the world group."""
    return bool(page_open) or mentions_world(text) or used_world_last(history)


def select_tools(schemas, *, world):
    """``(declared schemas, names left out)`` for a turn: without ``world`` the world group's
    tools are left out, every other tool is kept in its order."""
    if world:
        return list(schemas), frozenset()
    kept, hidden = [], set()
    for schema in schemas:
        if in_world_group(schema.get("name")):
            hidden.add(schema["name"])
        else:
            kept.append(schema)
    return kept, frozenset(hidden)


def groups_used(tool_names):
    """The tool groups among ``tool_names`` (stored on the assistant entry for follow-ups)."""
    return [WORLD_GROUP] if any(in_world_group(name) for name in tool_names) else []
