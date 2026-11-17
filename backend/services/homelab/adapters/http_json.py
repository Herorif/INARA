"""``http_json``: GET a JSON endpoint, map fields to metrics and decide the state by rules.

- ``fields`` maps a metric name to a dotted path ("disk_used_pct": "fs.0.used_pct").
- ``ok_when`` is a list of comparisons (``base.Comparison``), all of which must hold for ok;
  otherwise the entity is ``fail_state`` (down by default). Rules are data, never code.
- ``each`` (a dotted path to a list) turns every list item into its own entity, named by
  ``name_field`` and identified by ``id_field``; fields and rules apply per item.
- A 401/403 means the saved secret was refused: the state is unknown, not down.
"""

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from services.homelab.adapters.common import HttpAdapter, HttpOptions
from services.homelab.base import (
    AdapterError,
    Comparison,
    DottedPath,
    MetricName,
    lookup,
    evaluate,
)

EACH_LIMIT = 200
Kind = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,23}$")]


class HttpJsonOptions(HttpOptions):
    fields: dict[MetricName, DottedPath] = Field(default_factory=dict, max_length=32)
    ok_when: list[Comparison] = Field(default_factory=list, max_length=16)
    fail_state: Literal["down", "warn"] = "down"
    kind: Kind = "service"
    each: DottedPath | None = None
    id_field: DottedPath | None = None
    name_field: DottedPath | None = None

    @model_validator(mode="after")
    def item_fields(self):
        if self.each is None and (self.id_field or self.name_field):
            raise ValueError("id_field and name_field go with each.")
        if self.each is not None and self.id_field is None:
            raise ValueError("Say which field identifies each item (id_field).")
        return self


def _item_id(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, str)):
        text = " ".join(str(value).split())[:80]
        return text or None
    return None


class HttpJsonAdapter(HttpAdapter):
    Options = HttpJsonOptions

    def _state(self, data):
        return "ok" if evaluate(data, self.options.ok_when) else self.options.fail_state

    def _metrics(self, data):
        return {name: lookup(data, path) for name, path in self.options.fields.items()}

    async def probe(self):
        kind = self.options.kind
        whole = f"{kind}" if self.options.each is None else "http"
        try:
            response = await self.request("GET", self.options.path)
        except AdapterError as exc:
            state = "unknown" if exc.code in ("homelab_secret_missing", "too_large") else "down"
            return [self.entity(whole, kind, self.config.name, state, {}, str(exc))]
        status = response.status_code
        if self.refused(status):
            return [self.entity(whole, kind, self.config.name, "unknown", {},
                                "The system refused the saved secret.")]
        if not 200 <= status < 300:
            return [self.entity(whole, kind, self.config.name, "down", {"http_status": status},
                                f"Answered HTTP {status}.")]
        try:
            data = self.json_of(response)
        except AdapterError as exc:
            return [self.entity(whole, kind, self.config.name, "warn", {}, str(exc))]
        if self.options.each is None:
            state = self._state(data)
            return [self.entity(whole, kind, self.config.name, state, self._metrics(data),
                                "" if state == "ok" else "A health rule didn't hold.")]
        items = lookup(data, self.options.each)
        if not isinstance(items, list):
            return [self.entity(whole, kind, self.config.name, "warn", {},
                                "The list wasn't found in the answer.")]
        entities, seen = [], set()
        for item in items[:EACH_LIMIT]:
            item_id = _item_id(lookup(item, self.options.id_field))
            if item_id is None or item_id in seen:
                continue
            seen.add(item_id)
            name = _item_id(lookup(item, self.options.name_field)) if self.options.name_field \
                else None
            state = self._state(item)
            entities.append(self.entity(
                f"{kind}:{item_id}", kind, name or item_id, state, self._metrics(item),
                "" if state == "ok" else "A health rule didn't hold.",
            ))
        return entities
