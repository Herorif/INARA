"""``prometheus``: read an exporter's ``/metrics`` text or query a Prometheus server.

``mode`` "exporter" GETs ``path`` (default /metrics) and parses the text exposition format;
"query" GETs ``/api/v1/query?query=<query>`` and reads the vector or scalar result. Then
each ``series`` entry picks samples by metric name and label equality, stores the value as
``as_metric`` and applies its thresholds (``down_below``, ``down_above``, ``warn_below``,
``warn_above``). With ``each_label`` every distinct value of that label is its own entity
(e.g. one per Uptime Kuma monitor); otherwise the system is one entity.
"""

import math
from typing import Annotated, Literal

from pydantic import (
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)

from services.homelab.adapters.common import HttpAdapter, HttpOptions
from services.homelab.adapters.http_json import Kind
from services.homelab.base import AdapterError, MetricName, Strict, worst

LINE_LIMIT = 100_000
ENTITY_LIMIT = 200
MetricId = Annotated[StrictStr, StringConstraints(pattern=r"^[a-zA-Z_:][a-zA-Z0-9_:]{0,199}$")]
LabelName = Annotated[StrictStr, StringConstraints(pattern=r"^[a-zA-Z_][a-zA-Z0-9_]{0,99}$")]
LabelValue = Annotated[StrictStr, StringConstraints(max_length=200)]
Number = StrictInt | StrictFloat


class Series(Strict):
    metric: MetricId | None = None
    labels: dict[LabelName, LabelValue] = Field(default_factory=dict, max_length=16)
    as_metric: MetricName
    down_below: Number | None = None
    down_above: Number | None = None
    warn_below: Number | None = None
    warn_above: Number | None = None

    def state(self, value):
        if value is None:
            return "unknown"
        if (self.down_below is not None and value < self.down_below) or (
            self.down_above is not None and value > self.down_above
        ):
            return "down"
        if (self.warn_below is not None and value < self.warn_below) or (
            self.warn_above is not None and value > self.warn_above
        ):
            return "warn"
        return "ok"

    def matches(self, name, labels):
        if self.metric is not None and name != self.metric:
            return False
        return all(labels.get(key) == value for key, value in self.labels.items())


class PrometheusOptions(HttpOptions):
    mode: Literal["exporter", "query"] = "exporter"
    path: Annotated[StrictStr, StringConstraints(
        max_length=300, pattern=r"^(/[A-Za-z0-9._~/%-]*)?$")] = "/metrics"
    query: Annotated[StrictStr, StringConstraints(
        min_length=1, max_length=1000, pattern=r"^[^\x00-\x1f\x7f]+$")] | None = None
    series: list[Series] = Field(min_length=1, max_length=32)
    each_label: LabelName | None = None
    kind: Kind = "service"

    @model_validator(mode="after")
    def query_mode(self):
        if (self.mode == "query") != (self.query is not None):
            raise ValueError("A query goes with mode 'query' (and only there).")
        return self


# --- the text exposition format -------------------------------------------------------------


def _number(text):
    try:
        value = float(text)
    except ValueError:
        return None
    return value


def _labels(text):
    """``a="x",b="y\\"z"`` -> dict; None when malformed."""
    labels, index, size = {}, 0, len(text)
    while index < size:
        while index < size and text[index] in " ,":
            index += 1
        if index >= size:
            break
        equals = text.find("=", index)
        if equals < 0:
            return None
        name = text[index:equals].strip()
        index = equals + 1
        if index >= size or text[index] != '"':
            return None
        index += 1
        value = []
        while index < size and text[index] != '"':
            char = text[index]
            if char == "\\" and index + 1 < size:
                index += 1
                char = {"n": "\n", "\\": "\\", '"': '"'}.get(text[index], "\\" + text[index])
            value.append(char)
            index += 1
        if index >= size:
            return None
        index += 1  # closing quote
        if not name:
            return None
        labels[name] = "".join(value)
    return labels


def parse_exposition(text):
    """[(name, labels, value)] from Prometheus text format; bad lines are skipped."""
    samples = []
    for line in text.splitlines()[:LINE_LIMIT]:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        brace = line.find("{")
        space = line.find(" ")
        if brace >= 0 and (space < 0 or brace < space):
            close = line.rfind("}")
            if close < brace:
                continue
            name, labels = line[:brace], _labels(line[brace + 1:close])
            rest = line[close + 1:].split()
        else:
            parts = line.split()
            name, labels, rest = parts[0], {}, parts[1:]
        if labels is None or not rest:
            continue
        value = _number(rest[0])
        if value is not None:
            samples.append((name, labels, value))
    return samples


def parse_query(data):
    """[(name, labels, value)] from an /api/v1/query answer (vector or scalar)."""
    if not isinstance(data, dict) or data.get("status") != "success":
        raise AdapterError("query_failed", "The Prometheus query didn't succeed.")
    body = data.get("data") if isinstance(data.get("data"), dict) else {}
    kind, result = body.get("resultType"), body.get("result")
    samples = []
    if kind == "scalar" and isinstance(result, list) and len(result) == 2:
        value = _number(str(result[1]))
        if value is not None:
            samples.append(("", {}, value))
    elif kind == "vector" and isinstance(result, list):
        for item in result[:LINE_LIMIT]:
            if not isinstance(item, dict):
                continue
            metric = item.get("metric") if isinstance(item.get("metric"), dict) else {}
            pair = item.get("value")
            if not isinstance(pair, list) or len(pair) != 2:
                continue
            value = _number(str(pair[1]))
            if value is None:
                continue
            labels = {str(key): str(val) for key, val in metric.items() if key != "__name__"}
            samples.append((str(metric.get("__name__", "")), labels, value))
    else:
        raise AdapterError("query_failed", "The Prometheus answer wasn't a vector or scalar.")
    return samples


class PrometheusAdapter(HttpAdapter):
    Options = PrometheusOptions

    async def _samples(self):
        if self.options.mode == "query":
            response = await self.request("GET", "/api/v1/query",
                                          params={"query": self.options.query})
        else:
            response = await self.request("GET", self.options.path)
        status = response.status_code
        if self.refused(status):
            raise AdapterError("homelab_refused", "The system refused the saved secret.")
        if not 200 <= status < 300:
            raise AdapterError("http_status", f"Answered HTTP {status}.")
        if self.options.mode == "query":
            return parse_query(self.json_of(response))
        return parse_exposition(response.content.decode("utf-8", errors="replace"))

    def _entities(self, samples):
        groups = {}  # entity key -> {series index: value}
        label = self.options.each_label
        for name, labels, value in samples:
            key = labels.get(label) if label else ""
            if key is None:
                continue
            for index, series in enumerate(self.options.series):
                if series.matches(name, labels):
                    groups.setdefault(key, {}).setdefault(index, value)
        if not label:
            groups.setdefault("", {})
        entities = []
        kind = self.options.kind
        for key, values in list(groups.items())[:ENTITY_LIMIT]:
            metrics, states = {}, []
            for index, series in enumerate(self.options.series):
                value = values.get(index)
                if value is not None and not math.isfinite(value):
                    value = None
                if value is not None:
                    metrics[series.as_metric] = value
                states.append(series.state(value))
            known = [item for item in states if item != "unknown"]
            state = worst(known) if values and known else "unknown"
            detail = "No matching series." if not values else (
                "" if state == "ok" else "A threshold was crossed.")
            if label:
                entities.append(self.entity(f"{kind}:{key[:80]}", kind, key, state, metrics,
                                            detail))
            else:
                entities.append(self.entity("prom", kind, self.config.name, state, metrics,
                                            detail))
        return entities

    async def probe(self):
        try:
            samples = await self._samples()
        except AdapterError as exc:
            state = "down" if exc.code in ("timeout", "unreachable", "http_status") else "unknown"
            return [self.entity("prom", self.options.kind, self.config.name, state, {}, str(exc))]
        return self._entities(samples)
