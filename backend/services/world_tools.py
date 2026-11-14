"""World tools and tours (W3b, W4; docs/WORLD_VIEW.md "Tools and tours").

``GevServer`` is the built-in MCP server ``gev`` (docs/MCP.md "Built-in servers"): God's Eye
View's own stdio MCP server, ``<world.node> <world.root>\\server\\mcp\\stdio.js --api-base
http://127.0.0.1:<world.port>`` with cwd ``world.root``. World view owns it: it is enabled only
while World view is installed and turned on, its tools reach the brain as ``mcp__gev__<tool>``
with fixed default policies (``DEFAULT_POLICY``), and before every call the globe sidecar is
started and awaited (``WorldView.ensure_ready``). Each gev tool gets an optional ``show``
argument (default true): when an answer carries ``data.view``, JARVIS shows it on the World
page itself (``WorldView.show_view``, in the background) without waiting for the brain.

``WorldTools`` registers the brain's own tools:
- ``world_show`` (permission ``world_show``, default False: never asks) shows an area, a camera
  or a followed aircraft or satellite. GEV turns the fields into a full view
  (``show_in_gods_eye_view``, called by the core only: the brain can't call it);
- ``world_tour`` (permission ``world_tour``, default False) plays 1 to 8 steps: show_view, then
  the tour bar's caption, then the step's seconds. One tour at a time: a new tour, Stop tour,
  the owner barging in on voice, a new request, or the globe stopping ends it. In a voice
  conversation the tool returns the captions so the voice speaks them.

Boundaries: the CCTV and licence-plate camera layers and tools stay off (deny policies, the
layer check here and in ``check_view``); no tracking of named private individuals and no face
recognition (the tool descriptions; follow takes only an ICAO address or a NORAD number). Logs
carry codes and counts only, never arguments, captions or results.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from services.log import get_logger
from services.mcp_registry import BuiltinServer
from services.settings import EmptyRequest, McpServerConfig
from services.tools import ServiceError, ToolSpec
from services.world_view import (
    CAPTION_CHARS,
    NOT_INSTALLED,
    PRIVATE_LAYERS,
    SYSTEM_CA,
    TITLE_CHARS,
    WorldView,
    check_view,
    clean_text,
)

logger = get_logger(__name__)

SERVER_ID, SERVER_NAME = "gev", "God's Eye View"
SHOW, TOUR = "world_show", "world_tour"
# God's Eye View's tools, as its MCP server lists them (GEV docs/TOOLS.md).
DENY = (
    "get_cctv_snapshot", "find_cctv_cameras", "find_alpr_cameras",
    # The panel's own loader, and GEV's link/panel view: JARVIS shows views itself.
    "panel_request", "show_in_gods_eye_view",
    # A bundled demo scene under a non-commercial licence (CC BY-NC 4.0).
    "get_bhote_koshi_flood",
)
ASK = ("military_awareness", "find_military_installations")
DEFAULT_POLICY = {**{name: "deny" for name in DENY}, **{name: "ask" for name in ASK}}
GEV_TIMEOUT = 60
# The view fields God's Eye View's embed takes (src/view/index.js createView).
VIEW_KEYS = ("camera", "layers", "style", "map", "follow", "annotations")
# GEV's REGISTERED_LAYER_IDS at the pinned commit (scripts/install-world-view.ps1).
LAYERS = (
    "air-quality", "ais-live-vessels", "alpr-cameras", "bhote-koshi-2026",
    "bhote-koshi-locator", "bikeshare", "cctv", "directions", "drone-airspace", "earthquakes",
    "fire-perimeters", "flights", "gnss-integrity", "local-dams", "local-datacenters",
    "local-firms", "military", "military-awareness", "military-installations", "radio",
    "recent-imagery", "rocket-launches", "s2-ghostmaps", "satellites", "sea-marks",
    "ski-pistes", "street-level", "telegeography-submarine-cables", "traffic", "transit",
    "weather-cyclones", "weather-lightning", "weather-radar", "weather-satellite",
    "wildlife-sightings", "wind",
)
OFFERED_LAYERS = tuple(layer for layer in LAYERS if layer not in PRIVATE_LAYERS)
PRIVATE_MESSAGE = "World view keeps the CCTV and licence-plate camera layers off."
SHOW_NOTE = (
    " JARVIS shows the answer's view on the World globe unless show is false; pass show: "
    "false while gathering data for world_tour."
)
SHOW_PROPERTY = {
    "type": "boolean",
    "description": (
        "Show this answer's view on the owner's World globe (default true). False while "
        "gathering data for world_tour."
    ),
}
PLACE_FALLBACK = (
    "If God's Eye View can't place a name (its place search may be off), give lat and lon "
    "with radius_km instead. "
)
BOUNDARIES = (
    "Boundaries: never track or locate a named private individual (aircraft and ships are "
    "fine by callsign, registration, MMSI or name of the vessel), never attempt face "
    "recognition, and the CCTV and licence-plate camera layers and tools stay off."
)
SHOW_DESCRIPTION = (
    "Show a place on the owner's World globe (Studio > World: God's Eye View, a live 3D globe "
    "on this PC). Give an area framed from above (a place name such as \"Penang\", a bbox "
    "[west, south, east, north], or lat and lon with radius_km) or an exact camera, plus data "
    "layers (for example flights, ais-live-vessels, satellites, earthquakes, local-firms, "
    "weather-radar), a visual style, marks on the map, or one aircraft (ICAO address) or "
    "satellite (NORAD number) to follow. Use it for 'show me ...' requests. To answer a "
    "question about the world (flights, ships, satellites, earthquakes, fires), call the God's "
    "Eye View tools (mcp__gev__...) first: their answers already show on the globe. For a "
    "plain weather question use the weather tool. Use the globe only when the owner asks to "
    "see something. " + PLACE_FALLBACK + BOUNDARIES
)
TOUR_DESCRIPTION = (
    "Give the owner a guided tour on the World globe: 1 to 8 steps (2 to 8 for a real tour), "
    "each a view (the data.view of a God's Eye View answer, or an area or camera with layers "
    "and an aircraft or satellite to follow), a caption of at most 200 characters and 3 to 30 "
    "seconds on screen. For 'give me a tour of ...', first gather live data with the God's "
    "Eye View tools (show: false while gathering), then call world_tour once with the steps "
    "in order. Captions are what JARVIS says, in the Classic JARVIS voice with real numbers "
    "from the data, for example 'Over 140 aircraft within 50 kilometres, sir, most of them "
    "bound for KLIA.' One tour plays at a time; a new tour, Stop tour, the owner speaking or "
    "a new request ends it. In a voice conversation the result lists the captions: speak "
    "them in order as your answer. " + PLACE_FALLBACK + BOUNDARIES
)

# --- arguments --------------------------------------------------------------------------------
Number = Annotated[StrictFloat, Field(allow_inf_nan=False)]
Latitude = Annotated[StrictFloat, Field(ge=-90, le=90, allow_inf_nan=False)]
Longitude = Annotated[StrictFloat, Field(ge=-180, le=180, allow_inf_nan=False)]
Layer = Annotated[StrictStr, Field(json_schema_extra={"enum": list(OFFERED_LAYERS)})]


class Area(EmptyRequest):
    """Exactly one of place, bbox, or lat and lon with radius_km (GEV's area argument)."""

    place: StrictStr | None = Field(
        default=None, min_length=1, max_length=200, description='A place name, such as "Penang".'
    )
    bbox: list[Number] | None = Field(
        default=None, min_length=4, max_length=4,
        description="[west, south, east, north] in degrees.",
    )
    lat: Latitude | None = None
    lon: Longitude | None = None
    radius_km: Annotated[StrictFloat, Field(ge=0.1, le=2000, allow_inf_nan=False)] | None = None

    @model_validator(mode="after")
    def one_kind(self):
        given = [name for name in ("place", "bbox", "lat") if getattr(self, name) is not None]
        if len(given) != 1:
            raise ValueError("Give exactly one of place, bbox, or lat with lon and radius_km.")
        point = (self.lat, self.lon, self.radius_km)
        if any(value is not None for value in point) and None in point:
            raise ValueError("An area with lat also needs lon and radius_km.")
        if self.bbox is not None:
            west, south, east, north = self.bbox
            if abs(west) > 180 or abs(east) > 180 or abs(south) > 90 or abs(north) > 90:
                raise ValueError("bbox is [west, south, east, north] in degrees.")
            if south >= north:
                raise ValueError("bbox needs south below north.")
        return self


class Camera(EmptyRequest):
    lat: Latitude
    lon: Longitude
    altitude_m: Annotated[StrictFloat, Field(ge=50, le=20_000_000, allow_inf_nan=False)] | None = None
    heading_deg: Annotated[StrictFloat, Field(ge=0, le=360, allow_inf_nan=False)] | None = None
    pitch_deg: Annotated[StrictFloat, Field(ge=-90, le=0, allow_inf_nan=False)] | None = None


class Follow(EmptyRequest):
    kind: Literal["aircraft", "military_aircraft", "satellite"]
    id: Annotated[StrictStr, StringConstraints(pattern=r"^[0-9A-Za-z~_-]{1,16}$")] = Field(
        description="An aircraft's ICAO 24-bit address, or a satellite's NORAD number."
    )
    cockpit: StrictBool | None = None

    @model_validator(mode="after")
    def cockpit_for_aircraft(self):
        if self.cockpit and self.kind == "satellite":
            raise ValueError("Only an aircraft has a cockpit view.")
        return self


class Point(EmptyRequest):
    latitude: Latitude
    longitude: Longitude


class Annotation(EmptyRequest):
    type: Literal["pin", "highlight", "area", "arrow", "route", "label"]
    target: StrictStr | None = Field(default=None, min_length=1, max_length=200)
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    toLatitude: Latitude | None = None  # GEV's field names
    toLongitude: Longitude | None = None
    points: list[Point] | None = Field(default=None, min_length=2, max_length=12)
    label: StrictStr | None = Field(default=None, max_length=120)
    color: Literal["primary", "amber", "cyan", "green", "red"] | None = None

    @model_validator(mode="after")
    def placed(self):
        pair = (self.latitude is None) == (self.longitude is None)
        if not pair or (self.toLatitude is None) != (self.toLongitude is None):
            raise ValueError("Give latitude and longitude together.")
        if self.target is None and self.points is None and self.latitude is None:
            raise ValueError("A mark needs a target, a point or a route.")
        return self


def known_layers(value):
    if value is not None and any(layer not in LAYERS for layer in value):
        raise ValueError("Use layer names God's Eye View knows.")
    return value


class ViewFields(EmptyRequest):
    area: Area | None = None
    camera: Camera | None = None
    layers: list[Layer] | None = Field(default=None, max_length=len(LAYERS))
    follow: Follow | None = None

    @field_validator("layers")
    @classmethod
    def known(cls, value):
        return known_layers(value)

    def view_fields(self):
        """The fields for GEV's view resolver, without JARVIS's own."""
        return self.model_dump(
            exclude_none=True, exclude={"title", "caption", "seconds"}
        )


class WorldShow(ViewFields):
    style: Literal["normal", "retro", "surveillance", "thermal", "anime", "noir"] | None = None
    annotations: list[Annotation] | None = Field(default=None, max_length=24)
    title: StrictStr | None = Field(
        default=None, max_length=TITLE_CHARS, description="A short title for what is shown."
    )

    @model_validator(mode="after")
    def something_to_show(self):
        if self.area is not None and self.camera is not None:
            raise ValueError("Give an area or a camera, not both.")
        if self.area is None and self.camera is None and self.follow is None:
            raise ValueError("Give an area, a camera or something to follow.")
        return self


class TourStep(ViewFields):
    view: dict[str, Any] | None = Field(
        default=None, description="The data.view of a God's Eye View answer, shown as it is."
    )
    caption: StrictStr = Field(min_length=1, max_length=200, description="What JARVIS says.")
    seconds: StrictInt = Field(ge=3, le=30, description="How long this step stays on screen.")

    @model_validator(mode="after")
    def something_to_show(self):
        if self.area is not None and self.camera is not None:
            raise ValueError("Give an area or a camera, not both.")
        if all(getattr(self, name) is None for name in ("view", "area", "camera", "follow")):
            raise ValueError("Each step needs a view, an area, a camera or something to follow.")
        if clean_text(self.caption, CAPTION_CHARS) is None:
            raise ValueError("Each step needs a caption.")
        return self


class WorldTour(EmptyRequest):
    title: StrictStr = Field(min_length=1, max_length=TITLE_CHARS)
    steps: list[TourStep] = Field(min_length=1, max_length=8)


# --- helpers ----------------------------------------------------------------------------------
def view_of(data):
    """The view in a GEV answer's data (``data.view``), with only the embed's fields."""
    view = data.get("view") if isinstance(data, dict) else None
    if not isinstance(view, dict) or not isinstance(view.get("camera"), dict):
        return None
    return {key: view[key] for key in VIEW_KEYS if key in view}


def refuse_private(fields):
    layers = list(fields.get("layers") or ())
    view = fields.get("view")
    if isinstance(view, dict) and isinstance(view.get("layers"), list):
        layers += view["layers"]
    if PRIVATE_LAYERS & {layer for layer in layers if isinstance(layer, str)}:
        raise ServiceError("world_view_private", PRIVATE_MESSAGE)


def world_problem(values):
    """(code, message) when World view can't run, else None."""
    reason = WorldView.install_problem(values)
    if reason is None and not (Path(values["root"]) / "server" / "mcp" / "stdio.js").is_file():
        reason = "dist_missing"
    if reason:
        return "world_not_installed", f"{NOT_INSTALLED[reason]} Set it up from Studio > World."
    if not values["enabled"]:
        return "world_disabled", "World view is turned off in settings."
    return None


# --- the built-in God's Eye View server -------------------------------------------------------
class GevServer(BuiltinServer):
    id, owner = SERVER_ID, "world"

    def __init__(self, tools):
        self.tools = tools

    @property
    def world(self):
        return self.tools.app.world

    def config(self):
        values = self.world.settings()
        root = Path(values["root"])
        enabled = world_problem(values) is None
        return McpServerConfig(
            id=SERVER_ID,
            name=SERVER_NAME,
            command=[
                str(values["node"]), str(root / "server" / "mcp" / "stdio.js"),
                "--api-base", f"http://127.0.0.1:{values['port']}",
            ],
            cwd=str(root),
            # Its sources fetch HTTPS feeds too (as the sidecar does: world_view.SYSTEM_CA).
            env=dict(SYSTEM_CA),
            enabled=enabled,
            # Lists its tools at startup so the brain sees them; idles out like the globe.
            autostart=enabled,
            timeout_s=GEV_TIMEOUT,
            idle_timeout_s=values["idle_minutes"] * 60,
            default_policy="never_ask",
            policy=dict(DEFAULT_POLICY),
        )

    def disabled_message(self):
        problem = world_problem(self.world.settings())
        return problem[1] if problem else "World view isn't available right now."

    async def before_call(self, tool):
        # Every gev tool reads the running globe's /api routes.
        await self.world.ensure_ready()

    def tool_schema(self, tool, schema):
        properties = schema.get("properties")
        if isinstance(properties, dict) and "show" not in properties:
            schema = {**schema, "properties": {**properties, "show": dict(SHOW_PROPERTY)}}
        return schema

    def tool_description(self, tool, description):
        return description.rstrip() + SHOW_NOTE

    def split_arguments(self, tool, arguments):
        show = arguments.pop("show", True)
        if not isinstance(show, bool):
            raise ServiceError("invalid_arguments", "show must be true or false.")
        return arguments, {"show": show}

    async def after_call(self, tool, title, raw, extras):
        if not extras.get("show") or raw.get("isError") is True:
            return None
        view = view_of(raw.get("structuredContent"))
        if view is None:
            return None
        try:
            view = check_view(view)
        except ServiceError as exc:
            return {"world_view": f"Not shown on the globe: {exc}"}
        self.tools.show_soon(view, clean_text(title, TITLE_CHARS))
        return {"world_view": "JARVIS is showing this on the World globe."}


# --- tours ------------------------------------------------------------------------------------
@dataclass
class Tour:
    title: str
    steps: list  # [(view, caption, seconds)]
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    task: asyncio.Task | None = None


class WorldTools:
    def __init__(self, app, *, sleep=asyncio.sleep):
        self.app, self.sleep = app, sleep
        self.current = None
        self.tasks = set()
        self.shows = set()
        self.gev = GevServer(self)
        app.mcp.add_builtin(self.gev)
        app.world.on_tour_stop = self.tour_stopped
        app.dispatcher.register(
            ToolSpec(SHOW, SHOW_DESCRIPTION, WorldShow, self._show, execution_timeout=150)
        )
        app.dispatcher.register(
            ToolSpec(
                TOUR, TOUR_DESCRIPTION, WorldTour, self._tour, execution_timeout=240,
                long_running=True,
            )
        )

    @property
    def world(self):
        return self.app.world

    def spawn(self, coroutine, bucket=None):
        task = asyncio.ensure_future(coroutine)
        for target in (self.tasks, bucket) if bucket is not None else (self.tasks,):
            target.add(task)
            task.add_done_callback(target.discard)
        return task

    def require_world(self):
        problem = world_problem(self.world.settings())
        if problem:
            raise ServiceError(*problem)

    def page_open(self, _owner=None):
        """True while the owner's World page is open: the conversation then offers the
        world tools on every turn (ConversationService.world_page_open)."""
        return bool(self.world.open_pages())

    def speaking(self, principal):
        """True while the owner has a live voice session (its answers are spoken)."""
        voice = getattr(self.app, "voice", None)
        session = voice.sessions.get(principal) if voice is not None else None
        return session is not None and not session.closed

    async def resolve(self, fields):
        """A full, checked view from view fields: God's Eye View places the area, frames the
        camera and bounds every field (its show_in_gods_eye_view, a core-only call)."""
        refuse_private(fields)
        if "view" in fields:
            check_view(fields["view"])
        raw = await self.app.mcp.call_tool(SERVER_ID, "show_in_gods_eye_view", fields)
        if raw.get("isError") is True:
            text = next(
                (item.get("text") for item in raw.get("content") or ()
                 if isinstance(item, dict) and isinstance(item.get("text"), str)),
                None,
            )
            reason = clean_text(text, 200) or "it gave no reason"
            raise ServiceError("world_view_unresolved", f"God's Eye View couldn't place that: {reason}")
        view = view_of(raw.get("structuredContent"))
        if view is None:
            raise ServiceError("world_view_unresolved", "God's Eye View returned no view.")
        return check_view(view)

    # --- automatic views from gev answers ---------------------------------------------------
    def show_soon(self, view, title):
        self.spawn(self.auto_show(view, title), self.shows)

    async def auto_show(self, view, title):
        try:
            await self.world.show_view(view, title=title)
        except ServiceError as exc:
            logger.info("World view answer not shown (%s)", exc.code)
        except Exception as exc:  # a background task: never an unhandled error
            logger.warning("World view answer not shown (%s)", type(exc).__name__)

    def cancel_shows(self):
        for task in tuple(self.shows):
            task.cancel()

    # --- world_show -------------------------------------------------------------------------
    async def _show(self, args, context):
        self.app.authorize_owner(context)
        self.require_world()
        # Before resolve: placing the view is a gev call, which starts the globe.
        self.world.require_window()
        view = await self.resolve(args.view_fields())
        self.cancel_shows()
        result = await self.world.show_view(view, title=args.title)
        failed = [step["step"] for step in result.get("steps", []) if not step.get("ok")]
        return {
            "shown": result.get("ok") is True,
            "camera": view["camera"],
            "layers": view.get("layers", []),
            **({"failed_steps": failed} if failed else {}),
        }

    # --- world_tour -------------------------------------------------------------------------
    async def _tour(self, args, context):
        self.app.authorize_owner(context)
        self.require_world()
        self.world.require_window()
        title = clean_text(args.title, TITLE_CHARS) or "World"

        async def place(index, step):
            try:
                return await self.resolve(step.view_fields())
            except ServiceError as exc:
                raise ServiceError(exc.code, f"Step {index + 1}: {exc}") from None

        views = await asyncio.gather(*(place(i, step) for i, step in enumerate(args.steps)))
        steps = [
            (view, clean_text(step.caption, CAPTION_CHARS), step.seconds)
            for view, step in zip(views, args.steps, strict=True)
        ]
        await self.stop_tour("replaced")
        self.cancel_shows()
        tour = Tour(title, steps)
        self.current = tour
        try:
            await self.world.show_view(steps[0][0], title=title)
            if self.current is not tour:
                raise ServiceError("world_tour_stopped", "The tour was stopped.")
            await self.world.set_tour(True, title=title, caption=steps[0][1])
        except BaseException:
            if self.current is tour:
                self.current = None
            raise
        tour.task = self.spawn(self.play(tour))
        logger.info("World tour started (%d steps)", len(steps))
        reply = {
            "started": True,
            "title": title,
            "steps": len(steps),
            "seconds": sum(item[2] for item in steps),
        }
        if self.speaking(context.get("principal")):
            reply["speak"] = [item[1] for item in steps]
            reply["note"] = (
                "Voice conversation: say these captions in order as your whole answer, in "
                "your own voice. The tour bar shows each one as its step plays."
            )
        else:
            reply["note"] = "The tour bar on the World page shows each caption. Reply in one short line."
        return reply

    async def play(self, tour):
        """Step 1 is on screen already: wait, then each next step (view, caption, wait)."""
        try:
            for index, (view, caption, seconds) in enumerate(tour.steps):
                if index:
                    # The globe stopped (Stop, idle, gaming mode) or the bar was closed.
                    if not self.world.tour["active"]:
                        return
                    await self.world.show_view(view, title=tour.title)
                    await self.world.set_tour(True, title=tour.title, caption=caption)
                await self.sleep(seconds)
        except ServiceError as exc:
            logger.info("World tour ended early (%s)", exc.code)
        finally:
            if self.current is tour:
                self.current = None
                if self.world.tour["active"]:
                    await self.world.set_tour(False)

    async def stop_tour(self, reason):
        """End the tour that is playing, if any; True when one was."""
        tour, self.current = self.current, None
        if tour is None:
            return False
        if tour.task is not None and tour.task is not asyncio.current_task():
            tour.task.cancel()
            await asyncio.gather(tour.task, return_exceptions=True)
        if self.world.tour["active"]:
            await self.world.set_tour(False)
        logger.info("World tour stopped (%s)", reason)
        return True

    async def tour_stopped(self):
        """The World page's Stop tour (WorldView.on_tour_stop)."""
        await self.stop_tour("stop tour")

    def interrupt(self, reason):
        """The owner barged in on voice, or a new request started: end the tour."""
        if self.current is not None:
            self.spawn(self.stop_tour(reason))

    def new_request(self, _owner=None):
        self.interrupt("new request")

    # --- lifetimes --------------------------------------------------------------------------
    async def settings_changed(self):
        """world.* changed: the gev server follows (tools listed or removed)."""
        await self.app.mcp.sync_builtin(SERVER_ID)

    async def close(self):
        await self.stop_tour("shutdown")
        tasks = tuple(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
