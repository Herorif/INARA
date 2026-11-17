"""A small local BM25 index over the brain's tools (S5.1, docs/AI_PROVIDERS.md "Tool search").

Claude searches its deferred tools server-side; Gemini has no equivalent, so a turn with more
than ``TOOL_SEARCH_THRESHOLD`` tools (services/tool_groups.py) sends the core set plus the
tools whose name and description best match the owner's request, ranked here with BM25:

- the documents are the model-visible tool schemas: name (counted twice), description and
  argument names and descriptions, lower-cased and split on anything that isn't a letter or
  digit (``print_stl`` -> ``print``, ``stl``), with a light suffix strip so "printer",
  "printing" and "prints" all match "print";
- the index is cached and rebuilt only when the dispatcher's tool set (names, descriptions,
  argument names) changes;
- ``select_for_request`` returns the core set, then the world group when the world gate
  allows it, then the top ``TOP_MATCHES`` matches, never more than ``MAX_TOOLS`` in all.

Pure Python, no I/O and no logging: the request text never leaves this module.
"""

import math
import re

from services.tool_groups import CORE_TOOLS, in_world_group

TOP_MATCHES = 8
MAX_TOOLS = 30
K1 = 1.5
B = 0.75
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
# Words too common in requests and tool descriptions to tell tools apart.
STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with", "is", "are", "be",
    "it", "its", "this", "that", "my", "me", "i", "you", "your", "can", "please", "what",
    "whats", "how", "do", "does", "from", "at", "by", "as", "if", "into", "use", "when",
    "s", "jarvis", "tool",
})
_SUFFIXES = ("ings", "ing", "ers", "er", "ed", "es", "s")


def stem(word):
    """A light suffix strip, the same on both sides: printers/printing/prints -> print."""
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def tokens(text):
    """Lower-cased word stems of ``text`` without stop words."""
    if not isinstance(text, str):
        return []
    return [
        stem(word) for word in (match.group(0).lower() for match in _TOKEN.finditer(text))
        if word not in STOP_WORDS
    ]


def _argument_text(parameters):
    parts = []
    properties = parameters.get("properties") if isinstance(parameters, dict) else None
    for name, value in (properties or {}).items():
        parts.append(str(name))
        if isinstance(value, dict) and isinstance(value.get("description"), str):
            parts.append(value["description"])
    return " ".join(parts)


def document(schema):
    """The words a tool is found by: name twice, description, argument names and descriptions."""
    name = str(schema.get("name") or "")
    return [
        *tokens(name), *tokens(name),
        *tokens(schema.get("description") or ""),
        *tokens(_argument_text(schema.get("parameters"))),
    ]


def signature(schemas):
    """What the index depends on; a change rebuilds it."""
    return tuple(
        (
            str(item.get("name")), str(item.get("description") or ""),
            tuple(sorted(((item.get("parameters") or {}).get("properties") or {}).keys())),
        )
        for item in schemas
    )


class ToolIndex:
    """BM25 over tool schemas (``ToolDispatcher.schemas()`` shape)."""

    def __init__(self, schemas):
        self.names = [str(item.get("name")) for item in schemas]
        self.documents = [document(item) for item in schemas]
        self.lengths = [len(words) for words in self.documents]
        count = len(self.documents)
        self.average = (sum(self.lengths) / count) if count else 0.0
        self.frequencies = []
        frequency = {}
        for words in self.documents:
            counts = {}
            for word in words:
                counts[word] = counts.get(word, 0) + 1
            self.frequencies.append(counts)
            for word in counts:
                frequency[word] = frequency.get(word, 0) + 1
        # BM25 idf with the +1 that keeps it positive for words in most documents.
        self.idf = {
            word: math.log(1 + (count - seen + 0.5) / (seen + 0.5))
            for word, seen in frequency.items()
        }

    def scores(self, query):
        """``{name: score}`` for every tool with a positive BM25 score for ``query``."""
        words = set(tokens(query))
        result = {}
        if not words or not self.average:
            return result
        for name, counts, length in zip(self.names, self.frequencies, self.lengths, strict=True):
            score = 0.0
            for word in words:
                seen = counts.get(word)
                if not seen:
                    continue
                norm = seen + K1 * (1 - B + B * length / self.average)
                score += self.idf[word] * seen * (K1 + 1) / norm
            if score > 0:
                result[name] = score
        return result

    def search(self, query, limit=TOP_MATCHES, exclude=()):
        """The best ``limit`` tool names for ``query``: highest score first, ties by name."""
        excluded = set(exclude)
        ranked = sorted(
            ((score, name) for name, score in self.scores(query).items() if name not in excluded),
            key=lambda item: (-item[0], item[1]),
        )
        return [name for _, name in ranked[: max(0, int(limit))]]


_cache = {"signature": None, "index": None}


def index_for(schemas):
    """The cached index for ``schemas``, rebuilt when the tool set changes."""
    key = signature(schemas)
    if _cache["signature"] != key or _cache["index"] is None:
        _cache["index"] = ToolIndex(schemas)
        _cache["signature"] = key
    return _cache["index"]


def select_for_request(schemas, text, *, world, core=CORE_TOOLS, limit=TOP_MATCHES,
                       cap=MAX_TOOLS):
    """``(declared schemas in dispatcher order, names left out)`` for a narrowed turn.

    Declared: the core set (never a world tool), then the world group if ``world`` allows
    it, then the top ``limit`` BM25 matches for ``text`` among the rest; at most ``cap``."""
    eligible = [item for item in schemas if world or not in_world_group(item.get("name"))]
    names = [str(item.get("name")) for item in eligible]
    chosen = [name for name in names if name in core and not in_world_group(name)]
    if world:
        chosen += [name for name in names if in_world_group(name) and name not in chosen]
    matches = index_for(schemas).search(text, limit=len(names), exclude=chosen)
    allowed = set(names)
    chosen += [name for name in matches if name in allowed][:max(0, int(limit))]
    keep = set(chosen[:max(0, int(cap))])
    declared = [item for item in schemas if item.get("name") in keep]
    hidden = frozenset(
        str(item.get("name")) for item in schemas if item.get("name") not in keep
    )
    return declared, hidden
