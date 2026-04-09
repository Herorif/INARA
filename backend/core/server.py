"""
INARA Server  - FastAPI + Socket.IO with dependency injection.

This replaces the old server.py. It's a thin relay between the frontend
(Socket.IO) and the backend agents (via EventBus). No global state,
no callback hell, no direct agent coupling.

The old server.py is preserved as server_legacy.py for reference.
"""

import sys
import asyncio
import os
import signal
import json
import base64

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from contextlib import asynccontextmanager

import socketio
import uvicorn
from fastapi import FastAPI

from core.config import Config
from core.event_bus import EventBus, Event, Events
from core.tool_registry import create_default_registry
from llm.router import LLMRouter
from llm.gemini import GeminiProvider, GeminiVoiceProvider
from agents.cad_agent import CadAgent
from agents.web_agent import WebAgent
from agents.kasa_agent import KasaSmartHomeAgent
from agents.printer_agent import PrinterControlAgent
from agents.auth_agent import AuthAgent
from project_manager import ProjectManager


# ---------------------------------------------------------------------------
# App wiring
# ---------------------------------------------------------------------------

config = Config()
bus = EventBus()
tool_registry = create_default_registry()

# LLM providers
router = LLMRouter()
gemini = GeminiProvider(model="gemini-2.5-flash")
router.register_provider(gemini, default=True)

# CAD uses a thinking-capable model
cad_llm = GeminiProvider(model="gemini-2.5-pro")

# Voice provider (will be used when voice pipeline is built)
voice_provider = GeminiVoiceProvider()
router.register_voice_provider(voice_provider)

# Agents
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
project_manager = ProjectManager(project_root)

cad_agent = CadAgent(llm=cad_llm, event_bus=bus)
web_agent = WebAgent(llm=gemini, event_bus=bus)
kasa_agent = KasaSmartHomeAgent(event_bus=bus, known_devices=config.kasa_devices)
printer_agent = PrinterControlAgent(event_bus=bus)
auth_agent = AuthAgent(event_bus=bus)

# Agent registry (name -> agent)
agents = {
    cad_agent.name: cad_agent,
    web_agent.name: web_agent,
    kasa_agent.name: kasa_agent,
    printer_agent.name: printer_agent,
    auth_agent.name: auth_agent,
}

# Socket.IO + FastAPI
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")


@asynccontextmanager
async def lifespan(application):
    print("[INARA] Starting up...")
    await kasa_agent.initialize()
    for p in config.printers:
        printer_agent.inner.add_printer_manually(
            name=p.get("name", p["host"]),
            host=p["host"],
            port=p.get("port", 80),
            printer_type=p.get("type", "moonraker"),
            camera_url=p.get("camera_url"),
        )
    asyncio.create_task(_monitor_printers())
    print("[INARA] Ready.")
    yield


app = FastAPI(lifespan=lifespan)
app_socketio = socketio.ASGIApp(sio, app)


# ---------------------------------------------------------------------------
# Event Bus → Socket.IO bridge
# ---------------------------------------------------------------------------

async def _bridge_event(event: Event):
    """Forward relevant bus events to the frontend via Socket.IO."""
    mapping = {
        Events.CAD_STATUS: "cad_status",
        Events.CAD_THOUGHT: "cad_thought",
        Events.CAD_RESULT: "cad_data",
        Events.WEB_UPDATE: "browser_frame",
        Events.WEB_RESULT: "web_result",
        Events.PRINTER_STATUS: "print_status_update",
        Events.PRINTER_LIST: "printer_list",
        Events.KASA_DEVICES: "kasa_devices",
        Events.KASA_CONTROL_RESULT: "kasa_update",
        Events.AUTH_STATUS: "auth_status",
        Events.AUTH_FRAME: "auth_frame",
        Events.PROJECT_CHANGED: "project_update",
        Events.ERROR: "error",
        Events.STATUS: "status",
        Events.VOICE_TRANSCRIPTION: "transcription",
        Events.VOICE_AUDIO_OUT: "audio_data",
    }
    socket_event = mapping.get(event.type)
    if socket_event:
        await sio.emit(socket_event, event.data)

bus.on_all(_bridge_event)




@app.get("/status")
async def status():
    return {"status": "running", "service": "INARA Backend"}


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------

async def _monitor_printers():
    """Periodically poll printer status."""
    while True:
        try:
            inner = printer_agent.inner
            if not inner.printers:
                await asyncio.sleep(5)
                continue
            tasks = []
            for host, printer in inner.printers.items():
                if printer.printer_type.value != "unknown":
                    tasks.append(inner.get_print_status(host))
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for res in results:
                    if not isinstance(res, Exception) and res:
                        await sio.emit("print_status_update", res.to_dict())
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[INARA] Printer monitor error: {e}")
        await asyncio.sleep(2)


# ---------------------------------------------------------------------------
# Socket.IO events  - thin relay to agents
# ---------------------------------------------------------------------------

@sio.event
async def connect(sid, environ):
    print(f"[INARA] Client connected: {sid}")
    await sio.emit("status", {"msg": "Connected to INARA Backend"}, room=sid)

    if config.face_auth_enabled:
        await sio.emit("auth_status", {"authenticated": False}, room=sid)
        await auth_agent.initialize()
        asyncio.create_task(auth_agent.start_auth())
    else:
        await sio.emit("auth_status", {"authenticated": True}, room=sid)


@sio.event
async def disconnect(sid):
    print(f"[INARA] Client disconnected: {sid}")


# --- Audio (placeholder until voice pipeline is built) ---

@sio.event
async def start_audio(sid, data=None):
    """Start voice session. Currently a placeholder for Phase 2 voice pipeline."""
    await sio.emit("status", {"msg": "INARA Started (voice pipeline pending)"})


@sio.event
async def stop_audio(sid):
    await sio.emit("status", {"msg": "INARA Stopped"})


@sio.event
async def pause_audio(sid):
    await sio.emit("status", {"msg": "Audio Paused"})


@sio.event
async def resume_audio(sid):
    await sio.emit("status", {"msg": "Audio Resumed"})


# --- Tool confirmation ---

@sio.event
async def confirm_tool(sid, data):
    request_id = data.get("id")
    confirmed = data.get("confirmed", False)
    print(f"[INARA] Tool confirmation {request_id}: {confirmed}")
    await bus.emit(Event(
        type=Events.TOOL_CALL_CONFIRMED if confirmed else Events.TOOL_CALL_DENIED,
        data={"id": request_id, "confirmed": confirmed},
    ))


# --- CAD ---

@sio.event
async def generate_cad(sid, data):
    prompt = data.get("prompt", "")
    cad_output_dir = str(project_manager.get_current_project_path() / "cad")
    await sio.emit("status", {"msg": "Generating new design..."})

    result = await cad_agent.handle_tool_call(
        "generate_cad", {"prompt": prompt}, output_dir=cad_output_dir
    )
    if result.success and result.data.get("file_path"):
        project_manager.save_cad_artifact(result.data["file_path"], prompt)
        await sio.emit("status", {"msg": "Design generated"})
    elif not result.success:
        await sio.emit("error", {"msg": result.message or "Failed to generate design"})


@sio.event
async def iterate_cad(sid, data):
    prompt = data.get("prompt", "")
    cad_output_dir = str(project_manager.get_current_project_path() / "cad")
    await sio.emit("status", {"msg": "Iterating design..."})

    result = await cad_agent.handle_tool_call(
        "iterate_cad", {"prompt": prompt}, output_dir=cad_output_dir
    )
    if result.success and result.data.get("file_path"):
        project_manager.save_cad_artifact(result.data["file_path"], prompt)
        await sio.emit("status", {"msg": "Design updated"})
    elif not result.success:
        await sio.emit("error", {"msg": result.message or "Failed to update design"})


# --- Web Agent ---

@sio.event
async def prompt_web_agent(sid, data):
    prompt = data.get("prompt", "")
    await sio.emit("status", {"msg": "Web Agent running..."})
    result = await web_agent.handle_tool_call("run_web_agent", {"prompt": prompt})
    await sio.emit("status", {"msg": "Web Agent finished"})


# --- Smart Home ---

@sio.event
async def discover_kasa(sid):
    result = await kasa_agent.handle_tool_call("list_smart_devices", {})
    if result.success:
        # Save discovered devices
        devices = result.data.get("devices", [])
        saved = [{"ip": d["ip"], "alias": d["alias"], "model": d["model"]} for d in devices]
        config.set("kasa_devices", saved)
        await sio.emit("status", {"msg": f"Found {len(devices)} Kasa devices"})


@sio.event
async def control_kasa(sid, data):
    ip = data.get("ip", "")
    action = data.get("action", "")

    if action in ("on", "off"):
        tool_action = f"turn_{action}"
        await kasa_agent.handle_tool_call("control_light", {"target": ip, "action": tool_action})
    elif action == "brightness":
        await kasa_agent.handle_tool_call(
            "control_light", {"target": ip, "action": "set", "brightness": data.get("value")}
        )
    elif action == "color":
        hsv = data.get("value", {})
        h, s, v = hsv.get("h", 0), hsv.get("s", 100), hsv.get("v", 100)
        await kasa_agent.inner.set_color(ip, (h, s, v))


# --- Printers ---

@sio.event
async def discover_printers(sid):
    result = await printer_agent.handle_tool_call("discover_printers", {})
    if not result.success:
        # Fallback: return saved printers
        saved = config.printers
        if saved:
            await sio.emit("printer_list", saved)


@sio.event
async def add_printer(sid, data):
    raw_host = data.get("host", "")
    name = data.get("name") or raw_host
    ptype = data.get("type", "moonraker")
    camera_url = data.get("camera_url")

    host, port = raw_host, 80
    if ":" in raw_host:
        host, port_str = raw_host.split(":")
        port = int(port_str)

    printer_agent.inner.add_printer_manually(
        name=name, host=host, port=port,
        printer_type=ptype, camera_url=camera_url,
    )

    # Save to config (avoid duplicates)
    printers = config.printers
    if not any(p["host"] == host and p.get("port", 80) == port for p in printers):
        printers.append({"name": name, "host": host, "port": port, "type": ptype, "camera_url": camera_url})
        config.set("printers", printers)

    # Refresh list
    printer_list = [p.to_dict() for p in printer_agent.inner.printers.values()]
    await sio.emit("printer_list", printer_list)
    await sio.emit("status", {"msg": f"Added printer: {name}"})


@sio.event
async def print_stl(sid, data):
    stl_path = data.get("stl_path", "current")
    printer_name = data.get("printer")
    profile = data.get("profile")

    if not printer_name:
        await sio.emit("error", {"msg": "No printer specified"})
        return

    project_path = str(project_manager.get_current_project_path())

    # Preview STL in CAD viewer
    resolved = printer_agent.inner._resolve_file_path(stl_path, project_path)
    if resolved and os.path.exists(resolved):
        with open(resolved, "rb") as f:
            stl_b64 = base64.b64encode(f.read()).decode("utf-8")
        await sio.emit("cad_data", {"format": "stl", "data": stl_b64, "filename": os.path.basename(resolved)})

    async def on_progress(percent, message):
        await sio.emit("slicing_progress", {"printer": printer_name, "percent": percent, "message": message})

    try:
        result = await printer_agent.inner.print_stl(
            stl_path, printer_name, profile,
            progress_callback=on_progress, root_path=project_path,
        )
        await sio.emit("print_result", result)
    except Exception as e:
        await sio.emit("error", {"msg": f"Print Failed: {e}"})


@sio.event
async def get_slicer_profiles(sid):
    try:
        profiles = printer_agent.inner.get_available_profiles()
        await sio.emit("slicer_profiles", profiles)
    except Exception as e:
        await sio.emit("error", {"msg": f"Failed to get profiles: {e}"})


# --- Settings ---

@sio.event
async def get_settings(sid):
    await sio.emit("settings", config.all)


@sio.event
async def update_settings(sid, data):
    if "tool_permissions" in data:
        config.update({"tool_permissions": data["tool_permissions"]})
    if "face_auth_enabled" in data:
        config.set("face_auth_enabled", data["face_auth_enabled"])
        if not data["face_auth_enabled"]:
            await sio.emit("auth_status", {"authenticated": True})
            auth_agent.stop_auth()
    if "camera_flipped" in data:
        config.set("camera_flipped", data["camera_flipped"])
    await sio.emit("settings", config.all)


@sio.event
async def get_tool_permissions(sid):
    await sio.emit("tool_permissions", config.tool_permissions)


@sio.event
async def update_tool_permissions(sid, data):
    config.update({"tool_permissions": data})
    await sio.emit("tool_permissions", config.tool_permissions)


# --- User text input (placeholder for voice pipeline) ---

@sio.event
async def user_input(sid, data):
    text = data.get("text", "")
    if text:
        project_manager.log_chat("User", text)
        # TODO: Route to LLM when voice pipeline is built
        await sio.emit("status", {"msg": "Text input received (voice pipeline pending)"})


@sio.event
async def video_frame(sid, data):
    # TODO: Route to voice provider when pipeline is built
    pass


# --- Memory ---

@sio.event
async def save_memory(sid, data):
    from pathlib import Path
    from datetime import datetime as dt

    messages = data.get("messages", [])
    if not messages:
        return

    memory_dir = Path("long_term_memory")
    memory_dir.mkdir(exist_ok=True)

    name = data.get("filename")
    if name:
        if not name.endswith(".txt"):
            name += ".txt"
        filepath = memory_dir / Path(name).name
    else:
        filepath = memory_dir / f"memory_{dt.now().strftime('%Y%m%d_%H%M%S')}.txt"

    with open(filepath, "w", encoding="utf-8") as f:
        for msg in messages:
            f.write(f"{msg.get('sender', 'Unknown')}: {msg.get('text', '')}\n")

    await sio.emit("status", {"msg": "Memory Saved Successfully"})


@sio.event
async def upload_memory(sid, data):
    memory_text = data.get("memory", "")
    if not memory_text:
        return
    # TODO: Send to LLM context when voice pipeline is built
    await sio.emit("status", {"msg": "Memory Loaded into Context"})


# --- Shutdown ---

@sio.event
async def shutdown(sid, data=None):
    print("[INARA] Shutdown signal received")
    auth_agent.stop_auth()
    await router.close_all()
    os._exit(0)


def _signal_handler(sig, frame):
    print(f"\n[INARA] Signal {sig} caught. Exiting...")
    os._exit(0)


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(
        "core.server:app_socketio",
        host="127.0.0.1",
        port=8000,
        reload=False,
        loop="asyncio",
    )
