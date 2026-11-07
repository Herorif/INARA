import sys
import asyncio

# Fix for asyncio subprocess support on Windows
# MUST BE SET BEFORE OTHER IMPORTS
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import uvicorn
import os
from pathlib import Path
from dotenv import load_dotenv
from services.capability_profiles import model_id
from services import secrets as provider_secrets
from services import env


# Ensure we can import jarvis
sys.path.append(os.path.dirname(os.path.abspath(__file__)))


ACTIVE_RUNTIME = "legacy-desktop-backend"
ACTIVE_ENTRYPOINT = "backend/server.py"

# Global state
SETTINGS_FILE = env.getenv("SETTINGS_FILE") or str(Path(__file__).parent / "settings.json")
load_dotenv(Path(__file__).parent.parent / '.env')

backend_dir = os.path.dirname(os.path.abspath(__file__))
project_root = env.getenv("PROJECT_ROOT") or os.path.dirname(backend_dir)
uvicorn_server = None

DEFAULT_SETTINGS = {
    "face_auth_enabled": False, # Default OFF as requested
    "tool_permissions": {
        "generate_cad": True,
        # Live design drafting (start/change/undo) only edits an in-memory draft; building it
        # still asks through generate_cad.
        "live_design": False,
        # Legacy AI-written build123d code runs as the user; off unless enabled.
        "legacy_generated_cad": "deny",
        "generate_image": True,
        "run_web_agent": True,
        "write_file": True,
        "read_directory": True,
        "read_file": True,
        "create_project": True,
        "switch_project": True,
        "list_projects": True,
        # Scheduler
        "create_reminder": True,
        "list_reminders": True,
        "cancel_reminder": True,
        "snooze_reminder": True,
        "create_routine": True,
        "list_routines": True,
        # Desktop
        "get_system_info": True,
        "launch_app": True,
        "list_running_apps": True,
        "focus_window": True,
        "take_screenshot": True,
        "search_files": True,
        "read_clipboard": True,
        "write_clipboard": True,
        # Devices (unified)
        "list_all_devices": True,
        "control_device": True,
        "get_device_state": True,
        # Google Calendar (docs/CALENDAR.md): reading never asks; adding an event always
        # asks (calendar_add_event also sets always_ask).
        "calendar_read": False,
        "calendar_write": True,
    },
    "printers": [], # List of {host, port, name, type}
    "kasa_devices": [], # List of {ip, alias, model}
    "camera_flipped": False # Invert cursor horizontal direction
}

SETTINGS = {**DEFAULT_SETTINGS, "tool_permissions": dict(DEFAULT_SETTINGS["tool_permissions"])}


def get_gemini_api_key():
    return provider_secrets.resolve("gemini_api_key") or ""


def get_ai_preflight_error():
    if get_gemini_api_key():
        return None
    if provider_secrets.environment_placeholder("gemini_api_key"):
        return "GEMINI_API_KEY is still using the placeholder value in .env."
    return "No Gemini API key is saved. Add one in Setup or with scripts/jarvis-secrets.py."


def get_anthropic_status():
    return "configured" if provider_secrets.resolve("anthropic_api_key") else "not configured"


def get_runtime_summary():
    ai_preflight_error = get_ai_preflight_error()
    reference_image_path = Path(backend_dir) / "reference.jpg"
    if not reference_image_path.is_file():
        reference_image_path = Path(project_root) / "reference.jpg"
    face_auth_enabled = SETTINGS.get("face_auth_enabled", False)
    slicer_status = (runtime.printer.get_slicer_status() if runtime.printer.instance is not None else
                    {'available': False, 'message': 'Printer capability loads when requested.'})

    if ai_preflight_error:
        ai_status = f"blocked ({ai_preflight_error})"
    else:
        ai_status = "configured"

    if not face_auth_enabled:
        face_auth_status = "disabled"
    elif reference_image_path.exists():
        face_auth_status = f"enabled (reference: {reference_image_path.name})"
    else:
        face_auth_status = f"enabled (missing {reference_image_path.name})"

    slicer_state = "ready" if slicer_status["available"] else "missing"

    return {
        "status": "running",
        "service": "JARVIS Backend",
        "runtime": ACTIVE_RUNTIME,
        "entrypoint": ACTIVE_ENTRYPOINT,
        "ai_status": ai_status,
        "face_auth_status": face_auth_status,
        "slicer_status": slicer_state,
        "slicer_message": slicer_status["message"],
        "saved_printers": len(SETTINGS.get("printers", [])),
        "text_ready": True,
        "text_model": model_id("text"),
    }


def print_startup_summary():
    summary = get_runtime_summary()
    print("[SERVER] ========================================")
    print(f"[SERVER] Active Runtime : {summary['runtime']}")
    print(f"[SERVER] Entrypoint     : {summary['entrypoint']}")
    print(f"[SERVER] Gemini API     : {summary['ai_status']}")
    print(f"[SERVER] Anthropic API  : {get_anthropic_status()}")
    print(f"[SERVER] Face Auth      : {summary['face_auth_status']}")
    print(f"[SERVER] Slicer         : {summary['slicer_status']} ({summary['slicer_message']})")
    print(f"[SERVER] Saved Printers : {summary['saved_printers']}")
    print("[SERVER] ========================================")

def load_settings():
    # A corrupt file is backed up and saves are blocked until restart (see
    # services.settings.load_settings_file); the process runs on defaults.
    from services.settings import load_settings_file
    if os.path.exists(SETTINGS_FILE) and load_settings_file(SETTINGS_FILE, SETTINGS):
        print("Loaded local settings.")


# Load on startup
load_settings()


def _request_exit():
    if uvicorn_server is not None:
        uvicorn_server.should_exit = True


from application import create_application  # noqa: E402 - settings load first

runtime = create_application(
    settings=SETTINGS, project_root=project_root,
    legacy_data_dir=env.getenv("LEGACY_DATA_DIR"),
    startup_summary=print_startup_summary,
    status_summary=get_runtime_summary, instance_id=env.getenv("INSTANCE_ID"),
    settings_path=SETTINGS_FILE, permission_names=DEFAULT_SETTINGS["tool_permissions"],
    request_exit=_request_exit)
# Compatibility aliases for the resident host and unmigrated legacy adapters.
# Extracted transports hold explicit dependencies and never import this facade.
sio, app, app_socketio = runtime.sio, runtime.app, runtime.asgi
resource_governor, dispatcher = runtime.resources, runtime.dispatcher
reminder_store, cad_service = runtime.reminders, runtime.cad
confirm_tool = runtime.confirmation_transport.confirm_tool
client_principals, client_roles = runtime.sessions.principals, runtime.sessions.roles
# Named facade methods remain for local adapters and existing launch scripts.
user_input = runtime.conversation_transport.user_input
resume_conversation = runtime.conversation_transport.resume_conversation
create_reminder = runtime.reminder_transport.create_reminder
snooze_reminder = runtime.reminder_transport.snooze_reminder
cancel_reminder = runtime.reminder_transport.cancel_reminder
acknowledge_reminder = runtime.reminder_transport.acknowledge_reminder
dismiss_reminder = runtime.reminder_transport.dismiss_reminder
get_reminders = runtime.reminder_transport.get_reminders
refresh_reminders = runtime.reminder_transport.refresh_reminders
deliver_reminders_once = runtime.delivery.deliver_reminders_once
close_services = runtime.close


discover_kasa = runtime.compat_transport.discover_kasa
control_kasa = runtime.compat_transport.control_kasa
discover_printers = runtime.compat_transport.discover_printers
add_printer = runtime.compat_transport.add_printer
get_slicer_profiles = runtime.compat_transport.get_slicer_profiles

# Connection/face hydration and tasks are owned by the injected application.
connect = runtime.connection.connect
disconnect = runtime.connection.disconnect


set_resource_state = runtime.lifecycle.set_resource_state
desktop_control = runtime.lifecycle.desktop_control
shutdown = runtime.lifecycle.shutdown
get_settings = runtime.settings_transport.get_settings
update_settings = runtime.settings_transport.update_settings
get_tool_permissions = runtime.settings_transport.get_tool_permissions
update_tool_permissions = runtime.settings_transport.update_tool_permissions


# Compatible wire names; ownership, validation and lifetime live in the root.
save_memory = runtime.workspace_transport.save_memory
generate_cad = runtime.workspace_transport.generate_cad
iterate_cad = runtime.workspace_transport.iterate_cad
prompt_web_agent = runtime.workspace_transport.prompt_web_agent


# Compatible names; registration and execution are owned by the injected transport.
control_device = runtime.local_transport.control_device
launch_app = runtime.local_transport.launch_app
take_screenshot = runtime.local_transport.take_screenshot
read_clipboard = runtime.local_transport.read_clipboard
list_all_devices = runtime.local_transport.list_all_devices
get_system_info = runtime.local_transport.get_system_info


print_stl = runtime.compat_transport.print_stl

if __name__ == "__main__":
    from services.log import configure_logging
    configure_logging()
    # Fail closed: a bare dev start gets a per-launch token in .runtime/ (never printed).
    from transport.session_token import ensure_session_token
    ensure_session_token()
    uvicorn_server = uvicorn.Server(uvicorn.Config(app_socketio, host="127.0.0.1", port=8000, loop="asyncio"))
    uvicorn_server.run()
