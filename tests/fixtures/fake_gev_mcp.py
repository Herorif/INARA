"""A fake God's Eye View MCP server for tests/test_world_tools.py (stdlib only, loopback only).

The tests copy this file to <root>/server/mcp/stdio.js and point world.node at the test
interpreter, so JARVIS runs it exactly as it runs GEV's server: ``<node> stdio.js --api-base
http://127.0.0.1:<port>`` with cwd = root. It lists GEV's 30 MCP tools and records each call
(name, arguments and whether the globe at --api-base answered) in <root>/fake-mcp-calls.jsonl.

Answers: get_earthquakes and aircraft_in_area carry ``data.view``; find_infrastructure's view
turns on the cctv layer (a view JARVIS must refuse); get_terrain_height has no view;
show_in_gods_eye_view places "Penang" and "Kuala Lumpur" (other names fail like GEV's) or
takes a camera, a bbox, a lat/lon area or a passed view.
"""

import json
import sys
import threading
import urllib.request
from pathlib import Path

root = Path.cwd()
args = sys.argv[1:]
api_base = args[args.index("--api-base") + 1]
(root / "fake-mcp-argv.json").write_text(json.dumps(sys.argv), encoding="utf-8")
lock = threading.Lock()
PLACES = {"penang": (5.4141, 100.3288), "kuala lumpur": (3.139, 101.6869)}
AREA = {
    "type": "object",
    "properties": {
        "place": {"type": "string", "minLength": 1, "maxLength": 200},
        "bbox": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
        "lat": {"type": "number"}, "lon": {"type": "number"}, "radius_km": {"type": "number"},
    },
    "additionalProperties": False,
}
TOOLS = [
    "get_earthquakes", "get_active_fires", "get_recent_launches", "aircraft_in_area",
    "find_aircraft", "get_aircraft_track", "get_aircraft_info", "vessels_in_area", "find_vessel",
    "get_vessel_track", "next_satellite_pass", "satellites_overhead", "find_cctv_cameras",
    "get_cctv_snapshot", "find_alpr_cameras", "get_traffic_flow", "get_weather_map",
    "get_recent_imagery", "find_submarine_cables", "find_infrastructure", "get_bhote_koshi_flood",
    "get_cyclones", "get_fire_perimeters", "get_terrain_height", "find_military_installations",
    "get_map_features", "situation_brief", "military_awareness", "show_in_gods_eye_view",
    "panel_request",
]
VIEW_PROPERTIES = {
    "view": {"type": "object"}, "area": AREA, "camera": {"type": "object"},
    "layers": {"type": "array", "items": {"type": "string"}}, "style": {"type": "string"},
    "map": {"type": "string"}, "follow": {"type": "object"}, "annotations": {"type": "array"},
}


def listing(name):
    properties = VIEW_PROPERTIES if name == "show_in_gods_eye_view" else {"area": AREA}
    return {
        "name": name,
        "title": name.replace("_", " ").capitalize(),
        "description": f"Fake {name}.",
        "inputSchema": {"type": "object", "properties": properties, "additionalProperties": False},
    }


def send(message):
    with lock:
        sys.stdout.write(json.dumps(message) + "\n")
        sys.stdout.flush()


def globe_answers():
    try:
        with urllib.request.urlopen(f"{api_base}/api/mapillary/status", timeout=2) as response:
            return response.status == 200
    except OSError:
        return False


def view(lat, lon, layers, altitude=60000):
    return {
        "camera": {"lat": lat, "lon": lon, "altitude_m": altitude, "heading_deg": 0, "pitch_deg": -90},
        "layers": layers, "style": None, "map": None, "follow": None, "annotations": [],
    }


def answer(summary, data):
    return {
        "content": [{"type": "text", "text": summary}, {"type": "text", "text": json.dumps(data)}],
        "structuredContent": data,
        "isError": False,
    }


def failure(text):
    return {"content": [{"type": "text", "text": text}],
            "structuredContent": {"error": "invalid_arguments"}, "isError": True}


def place(arguments):
    area = arguments.get("area") or {}
    camera = arguments.get("camera")
    base = arguments.get("view") or {}
    layers = arguments.get("layers", base.get("layers", []))
    if area.get("place"):
        found = PLACES.get(area["place"].lower())
        if found is None:
            return None, f'No place matched "{area["place"]}"; try a more specific name or a bbox'
        return view(*found, layers), None
    if area.get("bbox"):
        west, south, east, north = area["bbox"]
        return view((south + north) / 2, (west + east) / 2, layers, 200000), None
    if "lat" in area:
        return view(area["lat"], area["lon"], layers, 90000), None
    if camera:
        result = view(camera["lat"], camera["lon"], layers, camera.get("altitude_m", 800000))
        return result, None
    if base.get("camera"):
        return {**view(base["camera"]["lat"], base["camera"]["lon"], layers), "camera": base["camera"]}, None
    return None, "Give a view, an area, or a camera with lat and lon"


def call(name, arguments):
    with lock:
        with open(root / "fake-mcp-calls.jsonl", "a", encoding="utf-8") as stream:
            stream.write(json.dumps({"name": name, "arguments": arguments,
                                     "globe": globe_answers()}) + "\n")
    if name == "get_earthquakes":
        return answer("3 earthquakes RESULT-MARKER-QUAKES", {
            "total": 3, "rows": [{"magnitude": 5.1, "place": "RESULT-MARKER-QUAKES"}],
            "view": {**view(0.0, 120.0, ["earthquakes"], 15000000), "url": None},
        })
    if name == "aircraft_in_area":
        return answer("142 aircraft", {
            "total": 142, "rows": [{"callsign": "MAS1"}],
            "view": {**view(3.139, 101.6869, ["flights"]), "url": None},
        })
    if name == "find_infrastructure":
        return answer("2 datacenters", {"view": view(3.1, 101.6, ["local-datacenters", "cctv"])})
    if name == "show_in_gods_eye_view":
        result, error = place(arguments)
        if error:
            return failure(error)
        return answer("Open it", {"url": None, "view": result})
    return answer(f"{name} done", {"rows": []})


def handle(message):
    method, request_id = message.get("method"), message.get("id")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": request_id, "result": {
            "protocolVersion": message["params"]["protocolVersion"],
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "gods-eye-view", "version": "0.0-fake"},
        }})
    elif method == "ping":
        send({"jsonrpc": "2.0", "id": request_id, "result": {}})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": request_id,
              "result": {"tools": [listing(name) for name in TOOLS]}})
    elif method == "tools/call":
        params = message["params"]

        def run():
            result = call(params["name"], params.get("arguments") or {})
            send({"jsonrpc": "2.0", "id": request_id, "result": result})

        threading.Thread(target=run, daemon=True).start()
    elif request_id is not None and method is not None:
        send({"jsonrpc": "2.0", "id": request_id,
              "error": {"code": -32601, "message": "Method not found"}})


for line in sys.stdin:
    if line.strip():
        handle(json.loads(line))
