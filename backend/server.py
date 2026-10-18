import sys
import asyncio

# Fix for asyncio subprocess support on Windows
# MUST BE SET BEFORE OTHER IMPORTS
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import uvicorn
import os
import json
from pathlib import Path
from dotenv import load_dotenv



# Ensure we can import inara
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.tools import ServiceError


def FaceAuthenticator(**kwargs):
    from authenticator import FaceAuthenticator as factory
    return factory(**kwargs)

ACTIVE_RUNTIME = "legacy-desktop-backend"
ACTIVE_ENTRYPOINT = "backend/server.py"

# Global state
authenticator = None
SETTINGS_FILE = os.getenv('INARA_SETTINGS_FILE') or str(Path(__file__).parent / "settings.json")
load_dotenv(Path(__file__).parent.parent / '.env')

backend_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.getenv('INARA_PROJECT_ROOT') or os.path.dirname(backend_dir)
uvicorn_server = None
background_tasks = []

DEFAULT_SETTINGS = {
    "face_auth_enabled": False, # Default OFF as requested
    "tool_permissions": {
        "generate_cad": True,
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
        # Vision
        "describe_camera": True,
        "detect_presence": True,
        "watch_for": True,
        "stop_watching": True,
        "list_watches": True,
        # Devices (unified)
        "list_all_devices": True,
        "control_device": True,
        "get_device_state": True,
    },
    "printers": [], # List of {host, port, name, type}
    "kasa_devices": [], # List of {ip, alias, model}
    "camera_flipped": False # Invert cursor horizontal direction
}

SETTINGS = {**DEFAULT_SETTINGS, "tool_permissions": dict(DEFAULT_SETTINGS["tool_permissions"])}
AI_KEY_PLACEHOLDERS = {
    "your_api_key_here",
    "your_gemini_api_key_here",
    "changeme",
}


def get_gemini_api_key():
    return (os.getenv("GEMINI_API_KEY") or "").strip()


def get_ai_preflight_error():
    api_key = get_gemini_api_key()
    if not api_key:
        return "GEMINI_API_KEY is not set. Update your .env file."
    if api_key.lower() in AI_KEY_PLACEHOLDERS:
        return "GEMINI_API_KEY is still using the placeholder value in .env."
    return None


def is_api_key_error(error):
    message = str(error)
    lowered = message.lower()
    return "API_KEY_INVALID" in message or "api key not valid" in lowered or "invalid api key" in lowered


async def emit_ai_unavailable(sid, reason):
    await sio.emit('status', {'msg': 'AI Unavailable'}, room=sid)
    await sio.emit('error', {'msg': f"AI unavailable: {reason}"}, room=sid)


def get_runtime_summary():
    ai_preflight_error = get_ai_preflight_error()
    reference_image_path = Path(backend_dir) / "reference.jpg"
    face_auth_enabled = SETTINGS.get("face_auth_enabled", False)
    slicer_status = (printer_agent.get_slicer_status() if printer_agent.instance is not None else
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
        "service": "INARA Backend",
        "runtime": ACTIVE_RUNTIME,
        "entrypoint": ACTIVE_ENTRYPOINT,
        "ai_status": ai_status,
        "face_auth_status": face_auth_status,
        "slicer_status": slicer_state,
        "slicer_message": slicer_status["message"],
        "saved_printers": len(SETTINGS.get("printers", [])),
        "text_ready": True,
        "text_model": os.getenv('INARA_TEXT_MODEL', 'gemini-3.8-flash'),
    }


def print_startup_summary():
    summary = get_runtime_summary()
    print("[SERVER] ========================================")
    print(f"[SERVER] Active Runtime : {summary['runtime']}")
    print(f"[SERVER] Entrypoint     : {summary['entrypoint']}")
    print(f"[SERVER] Gemini API     : {summary['ai_status']}")
    print(f"[SERVER] Face Auth      : {summary['face_auth_status']}")
    print(f"[SERVER] Slicer         : {summary['slicer_status']} ({summary['slicer_message']})")
    print(f"[SERVER] Saved Printers : {summary['saved_printers']}")
    print("[SERVER] ========================================")

def load_settings():
    global SETTINGS
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                loaded = json.load(f)
                # Merge with defaults to ensure new keys exist
                # Deep merge for tool_permissions would be better but shallow merge of top keys + tool_permissions check is okay for now
                for k, v in loaded.items():
                    if k == "tool_permissions" and isinstance(v, dict):
                         SETTINGS["tool_permissions"].update(v)
                    else:
                        SETTINGS[k] = v
            print("Loaded local settings.")
        except Exception as e:
            print(f"Error loading settings: {e}")

def save_settings():
    runtime.settings_service.store.save(SETTINGS)

# Load on startup
load_settings()

async def _stop_legacy_media():
    """The root owns media; retain only the pending face-auth compatibility seam."""
    global authenticator
    if authenticator:
        authenticator.stop()
        authenticator = None


def _settings_changed(patch):
    if "tool_permissions" in patch and runtime.workspace.audio:
        runtime.workspace.audio.update_permissions(SETTINGS["tool_permissions"])
    if patch.get("face_auth_enabled") is False and authenticator:
        authenticator.stop()


def _request_exit():
    if uvicorn_server is not None:
        uvicorn_server.should_exit = True


from application import create_application

runtime = create_application(
    settings=SETTINGS, project_root=project_root,
    legacy_data_dir=os.getenv('INARA_LEGACY_DATA_DIR'),
    face_authenticated=lambda: authenticator is not None and authenticator.authenticated,
    stop_legacy=_stop_legacy_media, startup_summary=print_startup_summary,
    status_summary=get_runtime_summary, instance_id=os.getenv("INARA_INSTANCE_ID"),
    settings_path=SETTINGS_FILE, permission_names=DEFAULT_SETTINGS["tool_permissions"],
    settings_changed=_settings_changed,
    request_exit=_request_exit)
# Compatibility aliases for the resident host and unmigrated legacy adapters.
# Extracted transports hold explicit dependencies and never import this facade.
sio, app, app_socketio = runtime.sio, runtime.app, runtime.asgi
database, project_manager = runtime.database, runtime.projects
bus, reminder_store, scheduler_agent = runtime.bus, runtime.reminders, runtime.scheduler
resource_governor, dispatcher = runtime.resources, runtime.dispatcher
client_principals, client_roles = runtime.sessions.principals, runtime.sessions.roles
background_tasks = runtime.tasks
inara, printer_agent, desktop_agent = runtime.inara, runtime.printer, runtime.desktop
vision_loop, vision_agent, device_agent, kasa_agent = runtime.vision_loop, runtime.vision, runtime.devices, runtime.kasa
cad_service, image_service = runtime.cad, runtime.images
cad_transport, image_transport = runtime.cad_transport, runtime.image_transport
conversation_service = runtime.conversation
cad_context = runtime.studio_context
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
startup_event = runtime.start
close_services = runtime.close


def activate_printers():
    runtime.compat_service.activate_printer()
    if runtime.sessions.local_owner:
        runtime.compat_service.start_monitor(runtime.sessions.local_owner)


discover_kasa = runtime.compat_transport.discover_kasa
control_kasa = runtime.compat_transport.control_kasa
discover_printers = runtime.compat_transport.discover_printers
add_printer = runtime.compat_transport.add_printer
get_slicer_profiles = runtime.compat_transport.get_slicer_profiles

@sio.event
async def connect(sid, environ, auth=None):
    if not runtime.sessions.accept(sid, auth, os.getenv('INARA_SESSION_TOKEN')):
        return False
    principal = client_principals[sid]
    print(f"Client connected: {sid}")
    await sio.emit('status', {'msg': 'Connected to INARA Backend'}, room=sid)
    await sio.emit('text_ready', {'model': os.getenv('INARA_TEXT_MODEL', 'gemini-3.8-flash')}, room=sid)
    await sio.emit('resource_state', resource_governor.snapshot(), room=sid)
    await sio.emit('printer_list', SETTINGS.get('printers', []), room=sid)
    await sio.emit('project_update', {'project': project_manager.current_project}, room=sid)

    global authenticator
    face_auth_enabled = SETTINGS.get("face_auth_enabled", False)
    
    # Callback for Auth Status
    async def on_auth_status(is_auth):
        print(f"[SERVER] Auth status change: {is_auth}")
        await runtime.delivery.publish_job('auth_status', principal, {'authenticated': is_auth})

    # Callback for Auth Camera Frames
    async def on_auth_frame(frame_b64):
        await runtime.delivery.publish_job('auth_frame', principal, {'image': frame_b64})

    if face_auth_enabled:
        # Initialize Authenticator if not already done
        if authenticator is None:
            authenticator = FaceAuthenticator(
                reference_image_path="reference.jpg",
                on_status_change=on_auth_status,
                on_frame=on_auth_frame
            )

        # Check if already authenticated or needs to start
        if authenticator.authenticated:
            await sio.emit('auth_status', {'authenticated': True})
        else:
            await sio.emit('auth_status', {'authenticated': False})
            # Start the auth loop in background
            asyncio.create_task(authenticator.start_authentication_loop())
    else:
        print("Face Auth Disabled. Auto-authenticating.")
        await sio.emit('auth_status', {'authenticated': True})

    # Startup hydration — push current state to new client
    pending = [r.to_dict() for r in reminder_store.list_reminders(filter="all") if r.status == "pending"]
    if runtime.reminder_transport.can_read(sid):
        await sio.emit('reminder_list', pending, room=sid)
        await sio.emit('reminder_deliveries', reminder_store.open_deliveries(principal), room=sid)
    watches = vision_loop.list_watches() if hasattr(vision_loop, 'list_watches') else []
    await sio.emit('vision_watches', {"watches": watches}, room=sid)

@sio.event
async def disconnect(sid):
    await runtime.disconnect(sid)
    print(f"Client disconnected: {sid}")


set_resource_state = runtime.lifecycle.set_resource_state
desktop_control = runtime.lifecycle.desktop_control
shutdown = runtime.lifecycle.shutdown
get_settings = runtime.settings_transport.get_settings
update_settings = runtime.settings_transport.update_settings
get_tool_permissions = runtime.settings_transport.get_tool_permissions
update_tool_permissions = runtime.settings_transport.update_tool_permissions


# Compatible wire names; ownership, validation and lifetime live in the root.
start_audio = runtime.workspace_transport.start_audio
stop_audio = runtime.workspace_transport.stop_audio
pause_audio = runtime.workspace_transport.pause_audio
resume_audio = runtime.workspace_transport.resume_audio
video_frame = runtime.workspace_transport.video_frame
save_memory = runtime.workspace_transport.save_memory
upload_memory = runtime.workspace_transport.upload_memory
generate_cad = runtime.workspace_transport.generate_cad
iterate_cad = runtime.workspace_transport.iterate_cad
prompt_web_agent = runtime.workspace_transport.prompt_web_agent


@sio.event
async def confirm_tool(sid, data):
    data = await runtime.local_transport.validate_confirmation(sid, data)
    if data is None:
        return
    principal = client_principals.get(sid, sid)
    if dispatcher.resolve(principal, data["id"], data["confirmed"]):
        return
    try:
        runtime.workspace.resolve_confirmation(sid, data["id"], data["confirmed"])
    except ServiceError:
        await sio.emit('error', {'msg': 'Unauthorized confirmation.', 'code': 'permission_denied'}, room=sid)


# Compatible names; registration and execution are owned by the injected transport.
control_device = runtime.local_transport.control_device
stop_watching = runtime.local_transport.stop_watching
launch_app = runtime.local_transport.launch_app
take_screenshot = runtime.local_transport.take_screenshot
read_clipboard = runtime.local_transport.read_clipboard
list_all_devices = runtime.local_transport.list_all_devices
get_system_info = runtime.local_transport.get_system_info


print_stl = runtime.compat_transport.print_stl

if __name__ == "__main__":
    uvicorn_server = uvicorn.Server(uvicorn.Config(app_socketio, host="127.0.0.1", port=8000, loop="asyncio"))
    uvicorn_server.run()
