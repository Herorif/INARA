"""Weather (S1, docs/WEATHER.md): Open-Meteo parsing, the cache, the brain's weather tool,
assistant.home_place and the owner-only weather_home_set route.

Fake HTTP only (httpx.MockTransport): no network.
"""

import httpx
import pytest
from pydantic import ValidationError

from services.settings import AssistantSettings, HomePlace, SettingsPatch, home_place
from services.weather import (
    UNKNOWN_CONDITION,
    WMO_CODES,
    WeatherQuery,
    condition,
    parse_forecast,
    summary_line,
)

GEOCODE_KL = {
    "results": [{
        "id": 1735161, "name": "Kuala Lumpur", "latitude": 3.1412, "longitude": 101.68653,
        "country_code": "MY", "timezone": "Asia/Kuala_Lumpur", "country": "Malaysia",
        "admin1": "Kuala Lumpur",
    }],
    "generationtime_ms": 0.08,
}
# Shaped like the real answer (14 Nov 2026), trimmed.
FORECAST = {
    "latitude": 3.1282952, "longitude": 101.68548, "timezone": "Asia/Kuala_Lumpur",
    "current_units": {
        "time": "iso8601", "interval": "seconds", "temperature_2m": "°C",
        "apparent_temperature": "°C", "relative_humidity_2m": "%", "precipitation": "mm",
        "weather_code": "wmo code", "wind_speed_10m": "km/h",
    },
    "current": {
        "time": "2026-11-14T19:45", "interval": 900, "temperature_2m": 31.2,
        "apparent_temperature": 36.4, "relative_humidity_2m": 70, "precipitation": 0.2,
        "weather_code": 61, "wind_speed_10m": 1.9,
    },
    "daily_units": {"time": "iso8601", "weather_code": "wmo code"},
    "daily": {
        "time": ["2026-11-14", "2026-11-15", "2026-11-16", "2026-11-17", "2026-11-18",
                 "2026-11-19", "2026-11-20"],
        "weather_code": [61, 80, 95, 95, 81, 81, 55],
        "temperature_2m_max": [33.2, 30.8, 31.0, 31.1, 30.6, 31.1, 31.6],
        "temperature_2m_min": [24.9, 24.2, 24.4, 24.0, 23.5, 23.2, 23.5],
        "precipitation_probability_max": [70, 100, 60, 98, 40, 97, 92],
    },
}


class FakeMeteo:
    def __init__(self):
        self.requests = []
        self.geocode = GEOCODE_KL
        self.forecast = FORECAST
        self.error = None

    def __call__(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        if request.url.host == "geocoding-api.open-meteo.com":
            assert request.url.path == "/v1/search"
            return httpx.Response(200, json=self.geocode)
        if request.url.host == "api.open-meteo.com":
            assert request.url.path == "/v1/forecast"
            return httpx.Response(200, json=self.forecast)
        return httpx.Response(404, json={})

    def hosts(self):
        return [request.url.host for request in self.requests]


@pytest.fixture
def meteo():
    return FakeMeteo()


@pytest.fixture
def app(application_factory, meteo):
    app = application_factory()
    app.settings["tool_permissions"]["weather"] = False
    app.sessions.principals.update({"client": "owner", "other": "intruder"})
    app.sessions.roles.update({"client": "renderer", "other": "renderer"})
    app.sessions.local_owner = "owner"
    app.weather.transport = httpx.MockTransport(meteo)
    return app


def tool_context(app):
    return app.sessions.context("client").tools()


async def call_tool(app, **arguments):
    return await app.dispatcher.dispatch("owner", "weather", arguments, tool_context(app))


async def rpc(app, name, data=None, sid="client"):
    return await app.sio.handlers["/"][name](sid, data)


def emitted(app, event):
    return [call.args[1] for call in app.sio.emit.await_args_list if call.args[0] == event]


# --- parsing --------------------------------------------------------------------------------
def test_wmo_codes_map_to_plain_words():
    assert condition(0) == "clear sky"
    assert condition(61) == "light rain"
    assert condition(95) == "thunderstorms"
    assert condition(99) == "thunderstorms with heavy hail"
    assert condition(3.0) == "overcast"
    for value in (4, 100, None, "61", True):
        assert condition(value) == UNKNOWN_CONDITION
    # Every code Open-Meteo documents (WMO 4677 subset) is mapped.
    assert set(WMO_CODES) == {
        0, 1, 2, 3, 45, 48, 51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 71, 73, 75, 77,
        80, 81, 82, 85, 86, 95, 96, 99,
    }


def test_parse_forecast_reads_current_and_daily_fields():
    parsed = parse_forecast(FORECAST)
    assert parsed["now"] == {
        "temp": 31.2, "feels_like": 36.4, "humidity": 70, "precipitation": 0.2,
        "condition": "light rain", "wind_kmh": 1.9,
    }
    assert len(parsed["days"]) == 7
    assert parsed["days"][0] == {
        "date": "2026-11-14", "condition": "light rain", "min": 24.9, "max": 33.2,
        "rain_chance": 70,
    }
    assert parsed["units"]["temperature"] == "°C" and parsed["units"]["wind"] == "km/h"


async def test_lookup_geocodes_then_reads_the_forecast(app, meteo):
    result = await app.weather.lookup("Kuala Lumpur", "today")
    assert result["place"] == {
        "name": "Kuala Lumpur", "country": "Malaysia", "lat": 3.1412, "lon": 101.68653,
    }
    assert result["source"] == "Open-Meteo" and result["when"] == "today"
    assert result["now"]["condition"] == "light rain"
    assert [day["date"] for day in result["days"]] == ["2026-11-14"]
    geocode, forecast = meteo.requests
    assert geocode.url.params["name"] == "Kuala Lumpur"
    assert geocode.url.params["count"] == "1" and geocode.url.params["language"] == "en"
    params = forecast.url.params
    assert params["latitude"] == "3.1412" and params["timezone"] == "auto"
    assert "weather_code" in params["current"] and "wind_speed_10m" in params["current"]
    assert "precipitation_probability_max" in params["daily"]


@pytest.mark.parametrize(
    "when, dates",
    [
        ("now", []),
        ("today", ["2026-11-14"]),
        ("tomorrow", ["2026-11-15"]),
        ("week", FORECAST["daily"]["time"]),
    ],
)
async def test_when_limits_the_days(app, when, dates):
    result = await app.weather.lookup("Kuala Lumpur", when)
    assert [day["date"] for day in result["days"]] == dates
    assert result["now"]["temp"] == 31.2


async def test_answers_are_cached_per_place_and_coordinates(app, meteo):
    clock = [1000.0]
    app.weather.clock = lambda: clock[0]
    await app.weather.lookup("Kuala Lumpur", "today")
    await app.weather.lookup("kuala  lumpur", "week")
    assert meteo.hosts() == ["geocoding-api.open-meteo.com", "api.open-meteo.com"]
    clock[0] += 601  # past ten minutes: asked again
    await app.weather.lookup("Kuala Lumpur", "now")
    assert len(meteo.requests) == 4


async def test_network_failure_is_unavailable_not_raised(app, meteo):
    meteo.error = httpx.ConnectError("boom https://geocoding-api.open-meteo.com/?name=secret")
    result = await app.weather.lookup("Kuala Lumpur", "today")
    assert result == {"error": "unavailable", "message": "The weather service couldn't be reached."}
    meteo.error = httpx.ReadTimeout("slow")
    assert (await app.weather.lookup("Penang"))["error"] == "unavailable"


async def test_bad_status_or_body_is_unavailable(app, meteo):
    meteo.forecast = {"current": {}, "daily": {}}
    result = await app.weather.lookup("Kuala Lumpur")
    assert result["error"] == "unavailable"
    assert result["message"] == "The weather service gave an unexpected answer."


async def test_unknown_place_is_not_found(app, meteo):
    meteo.geocode = {"generationtime_ms": 0.1}  # the real answer when nothing matches
    result = await app.weather.lookup("Zzqxqx", "today")
    assert result["error"] == "not_found" and "Zzqxqx" in result["message"]
    assert meteo.hosts() == ["geocoding-api.open-meteo.com"]


# --- the brain tool -------------------------------------------------------------------------
def test_tool_is_registered_model_visible_and_never_asks(app):
    spec = app.dispatcher.tools["weather"]
    assert spec.model_visible is True and spec.always_ask is False
    assert spec.execution_timeout == 10
    assert spec.arguments is WeatherQuery
    assert "home town" in spec.description
    import server

    assert server.DEFAULT_SETTINGS["tool_permissions"]["weather"] is False


async def test_tool_without_place_or_home_needs_a_place(app, meteo):
    result = await call_tool(app)
    assert result["need_place"] is True
    assert "remember_as_home=true" in result["message"]
    assert meteo.requests == []


async def test_tool_remember_as_home_saves_the_place(app, meteo):
    result = await call_tool(app, place="Kuala Lumpur", when="now", remember_as_home=True)
    assert result["home_saved"] == "Kuala Lumpur, Malaysia"
    assert app.settings["assistant"]["home_place"] == {
        "name": "Kuala Lumpur, Malaysia", "lat": 3.1412, "lon": 101.68653,
    }
    assert emitted(app, "settings")  # the owner's renderer sees the new setting
    # Later calls without a place use it, with no geocoding.
    meteo.requests.clear()
    app.weather.cache.clear()
    later = await call_tool(app, when="tomorrow")
    assert later["place"]["name"] == "Kuala Lumpur, Malaysia"
    assert meteo.hosts() == ["api.open-meteo.com"]


async def test_tool_does_not_save_an_unknown_place(app, meteo):
    meteo.geocode = {}
    result = await call_tool(app, place="Nowhere", remember_as_home=True)
    assert result["error"] == "not_found"
    assert app.settings.get("assistant", {}).get("home_place") is None


def test_tool_arguments_are_checked():
    with pytest.raises(ValidationError):
        WeatherQuery.model_validate({"when": "yesterday"})
    with pytest.raises(ValidationError):
        WeatherQuery.model_validate({"place": "x" * 121})
    with pytest.raises(ValidationError):
        WeatherQuery.model_validate({"place": "KL", "extra": 1})
    assert WeatherQuery.model_validate({"place": "  Kuala   Lumpur "}).place == "Kuala Lumpur"


# --- summary_line ---------------------------------------------------------------------------
async def test_summary_line_today(app):
    result = await app.weather.lookup("Kuala Lumpur", "today")
    assert summary_line(result) == (
        "Kuala Lumpur: 31°C, feels like 36, light rain; today 25 to 33 with a 70% chance of rain."
    )


async def test_summary_line_other_whens(app):
    assert summary_line(await app.weather.lookup("Kuala Lumpur", "now")) == (
        "Kuala Lumpur: 31°C, feels like 36, light rain."
    )
    assert summary_line(await app.weather.lookup("Kuala Lumpur", "tomorrow")) == (
        "Kuala Lumpur: 31°C, feels like 36, light rain; tomorrow light rain showers, 24 to 31 "
        "with a 100% chance of rain."
    )
    week = summary_line(await app.weather.lookup("Kuala Lumpur", "week"))
    assert week == (
        "Kuala Lumpur: 31°C, feels like 36, light rain. The next 7 days range from 23 to 33, "
        "with rain most likely on Sunday (100%)."
    )


def test_summary_line_errors_read_plainly():
    assert summary_line({"error": "unavailable", "message": "The weather service couldn't be reached."}) \
        == "The weather service couldn't be reached."
    assert "home town" in summary_line({"need_place": True, "message": "x"})


# --- the setting ----------------------------------------------------------------------------
def test_home_place_setting_is_validated():
    assert AssistantSettings.model_validate(
        {"home_place": {"name": "Kuala Lumpur, Malaysia", "lat": 3.14, "lon": 101}}
    ).home_place.lon == 101
    assert AssistantSettings.model_validate({"home_place": None}).home_place is None
    for bad in (
        {"name": "KL", "lat": 91, "lon": 0},
        {"name": "KL", "lat": -90.5, "lon": 0},
        {"name": "KL", "lat": 0, "lon": 181},
        {"name": "KL", "lat": 0, "lon": -180.01},
        {"name": "KL", "lat": "3.1", "lon": 0},
        {"name": "KL", "lat": True, "lon": 0},
        {"name": "KL", "lat": float("nan"), "lon": 0},
        {"name": "x" * 121, "lat": 0, "lon": 0},
        {"name": "  ", "lat": 0, "lon": 0},
        {"name": "<KL>", "lat": 0, "lon": 0},
        {"name": "KL", "lat": 0},
        {"name": "KL", "lat": 0, "lon": 0, "extra": 1},
    ):
        with pytest.raises(ValidationError):
            SettingsPatch.model_validate({"assistant": {"home_place": bad}})


def test_home_place_reads_null_for_missing_or_stale_values():
    assert home_place({}) is None
    assert home_place({"assistant": {"home_place": None}}) is None
    assert home_place({"assistant": {"home_place": {"name": "KL", "lat": 99, "lon": 0}}}) is None
    assert home_place({"assistant": {"home_place": {"name": "KL", "lat": 3, "lon": 101}}}) == {
        "name": "KL", "lat": 3, "lon": 101,
    }
    assert HomePlace(name=" Kuala  Lumpur ", lat=1.0, lon=2.0).name == "Kuala Lumpur"


async def test_update_settings_keeps_other_assistant_fields(app):
    app.settings_service.apply(SettingsPatch.model_validate({"assistant": {"owner_name": "Tony"}}))
    app.settings_service.apply(SettingsPatch.model_validate(
        {"assistant": {"home_place": {"name": "Penang", "lat": 5.4, "lon": 100.3}}}
    ))
    assert app.settings["assistant"]["owner_name"] == "Tony"
    assert app.settings["assistant"]["home_place"]["name"] == "Penang"
    app.settings_service.apply(SettingsPatch.model_validate({"assistant": {"home_place": None}}))
    assert app.settings["assistant"]["home_place"] is None


# --- weather_home_set -----------------------------------------------------------------------
async def test_weather_home_set_geocodes_and_saves(app, meteo):
    reply = await rpc(app, "weather_home_set", {"place": "Kuala Lumpur"})
    assert reply == {
        "ok": True,
        "home_place": {"name": "Kuala Lumpur, Malaysia", "lat": 3.1412, "lon": 101.68653},
    }
    assert app.settings["assistant"]["home_place"]["name"] == "Kuala Lumpur, Malaysia"
    assert meteo.hosts() == ["geocoding-api.open-meteo.com"]
    assert emitted(app, "settings")[-1]["assistant"]["home_place"]["lat"] == 3.1412


async def test_weather_home_set_clears_with_null(app, meteo):
    await rpc(app, "weather_home_set", {"place": "Kuala Lumpur"})
    reply = await rpc(app, "weather_home_set", {"place": None})
    assert reply == {"ok": True, "home_place": None}
    assert app.settings["assistant"]["home_place"] is None


async def test_weather_home_set_failures_are_plain(app, meteo):
    meteo.geocode = {}
    reply = await rpc(app, "weather_home_set", {"place": "Nowhere"})
    assert reply["ok"] is False and reply["code"] == "not_found"
    meteo.error = httpx.ConnectError("down")
    reply = await rpc(app, "weather_home_set", {"place": "Elsewhere"})
    assert reply["ok"] is False and reply["code"] == "weather_unavailable"
    for bad in ({}, {"place": ""}, {"place": "   "}, {"place": 5}, {"place": "x" * 121},
                {"place": "KL", "extra": True}):
        reply = await rpc(app, "weather_home_set", bad)
        assert reply["ok"] is False and reply["code"] == "invalid_arguments", bad
    assert app.settings.get("assistant", {}).get("home_place") is None


async def test_weather_home_set_is_owner_only(app, meteo):
    reply = await rpc(app, "weather_home_set", {"place": "Kuala Lumpur"}, sid="other")
    assert reply["ok"] is False
    assert meteo.requests == []
