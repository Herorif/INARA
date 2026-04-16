generate_cad_prototype_tool = {
    "name": "generate_cad_prototype",
    "description": "Generates a 3D wireframe prototype based on a user's description. Use this when the user asks to 'visualize', 'prototype', 'create a wireframe', or 'design' something in 3D.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "prompt": {
                "type": "STRING",
                "description": "The user's description of the object to prototype."
            }
        },
        "required": ["prompt"]
    }
}




write_file_tool = {
    "name": "write_file",
    "description": "Writes content to a file at the specified path. Overwrites if exists.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "path": {
                "type": "STRING",
                "description": "The path of the file to write to."
            },
            "content": {
                "type": "STRING",
                "description": "The content to write to the file."
            }
        },
        "required": ["path", "content"]
    }
}

read_directory_tool = {
    "name": "read_directory",
    "description": "Lists the contents of a directory.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "path": {
                "type": "STRING",
                "description": "The path of the directory to list."
            }
        },
        "required": ["path"]
    }
}

read_file_tool = {
    "name": "read_file",
    "description": "Reads the content of a file.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "path": {
                "type": "STRING",
                "description": "The path of the file to read."
            }
        },
        "required": ["path"]
    }
}

# ---- Scheduler tools ----
create_reminder_tool = {
    "name": "create_reminder",
    "description": "Creates a reminder that fires at a specific time. Pass 'when' as an ISO-8601 datetime string (e.g. '2026-04-12T09:00:00') or a natural-language expression (e.g. 'in 20 minutes', 'tomorrow at 3pm'). For recurring reminders pass 'recurring' as 'daily', 'weekly', or 'weekdays'.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "task":      {"type": "STRING",  "description": "What to remind the user about."},
            "when":      {"type": "STRING",  "description": "When to fire (ISO datetime or natural language)."},
            "recurring": {"type": "STRING",  "description": "Recurrence: 'daily', 'weekly', or 'weekdays'. Omit for one-time."},
        },
        "required": ["task", "when"]
    }
}

list_reminders_tool = {
    "name": "list_reminders",
    "description": "Lists reminders. Use filter='today' for today's reminders, 'overdue' for past-due, or 'all' for everything pending.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "filter": {"type": "STRING", "description": "Filter: 'today', 'overdue', or 'all' (default)."},
        },
    }
}

cancel_reminder_tool = {
    "name": "cancel_reminder",
    "description": "Cancels a reminder so it will not fire.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "reminder_id": {"type": "STRING", "description": "The reminder ID (or first 8 characters of it)."},
        },
        "required": ["reminder_id"]
    }
}

snooze_reminder_tool = {
    "name": "snooze_reminder",
    "description": "Snoozes a reminder, rescheduling it to fire again after the given number of minutes.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "reminder_id": {"type": "STRING",  "description": "The reminder ID (or first 8 characters of it)."},
            "minutes":     {"type": "INTEGER", "description": "How many minutes to snooze for."},
        },
        "required": ["reminder_id", "minutes"]
    }
}

create_routine_tool = {
    "name": "create_routine",
    "description": "Creates a named routine that runs automatically on a trigger. Trigger format: 'greeting:good_morning', 'greeting:im_home', 'greeting:goodnight', or 'greeting:leaving'.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "name":    {"type": "STRING", "description": "A short name for the routine (e.g. 'Morning Routine')."},
            "trigger": {"type": "STRING", "description": "When this routine fires (e.g. 'greeting:good_morning')."},
            "actions": {"type": "STRING", "description": "Comma-separated list of actions for INARA to perform."},
        },
        "required": ["name", "trigger", "actions"]
    }
}

list_routines_tool = {
    "name": "list_routines",
    "description": "Lists all defined routines and whether they are enabled.",
    "parameters": {"type": "OBJECT", "properties": {}},
}

# ---- Desktop tools ----
get_system_info_tool = {
    "name": "get_system_info",
    "description": "Returns current CPU usage, memory, disk space, battery level, and top running processes.",
    "parameters": {"type": "OBJECT", "properties": {}},
}

launch_app_tool = {
    "name": "launch_app",
    "description": "Opens an application by its friendly name (e.g. 'chrome', 'vscode', 'spotify', 'discord', 'terminal').",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "name": {"type": "STRING", "description": "The app to open."},
        },
        "required": ["name"]
    }
}

list_running_apps_tool = {
    "name": "list_running_apps",
    "description": "Lists the top running processes on the machine sorted by memory usage.",
    "parameters": {"type": "OBJECT", "properties": {}},
}

focus_window_tool = {
    "name": "focus_window",
    "description": "Brings an open window to the foreground by its title or app name.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "name": {"type": "STRING", "description": "Window title or app name to focus."},
        },
        "required": ["name"]
    }
}

take_screenshot_tool = {
    "name": "take_screenshot",
    "description": "Takes a screenshot of the current screen and uses vision AI to describe what is visible. Use when the user asks what's on screen or wants to debug a UI issue.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "prompt": {"type": "STRING", "description": "Optional specific question about the screen."},
        },
    }
}

search_files_tool = {
    "name": "search_files",
    "description": "Searches for files matching a name pattern on the user's machine. Returns up to 20 matching paths.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query":     {"type": "STRING", "description": "Filename or glob pattern (e.g. 'resume*.docx', '*.pdf')."},
            "directory": {"type": "STRING", "description": "Directory to search in. Defaults to user home folder."},
        },
        "required": ["query"]
    }
}

read_clipboard_tool = {
    "name": "read_clipboard",
    "description": "Reads and returns the current text content of the system clipboard.",
    "parameters": {"type": "OBJECT", "properties": {}},
}

write_clipboard_tool = {
    "name": "write_clipboard",
    "description": "Writes text to the system clipboard.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "text": {"type": "STRING", "description": "The text to place in the clipboard."},
        },
        "required": ["text"]
    }
}

# ---- Vision tools ----
describe_camera_tool = {
    "name": "describe_camera",
    "description": "Takes the current camera frame and describes what INARA sees. Use when the user asks 'What do you see?' or 'Look at this'. Optionally pass a focused question.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "question": {"type": "STRING", "description": "Optional specific question about the scene."},
        },
    }
}

detect_presence_tool = {
    "name": "detect_presence",
    "description": "Checks whether any person is visible in the current camera view. Returns True/False and an approximate count if multiple people are present.",
    "parameters": {"type": "OBJECT", "properties": {}},
}

watch_for_tool = {
    "name": "watch_for",
    "description": "Starts continuously monitoring the camera for a specific event or object. INARA alerts the user when the condition is detected. Examples: 'package delivery', 'person at the door', 'cat on desk'.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "description": {"type": "STRING", "description": "What to watch for."},
            "watch_id":    {"type": "STRING", "description": "A short identifier for this watch (e.g. 'door'). Used to cancel it later."},
        },
        "required": ["description"]
    }
}

stop_watching_tool = {
    "name": "stop_watching",
    "description": "Stops a previously registered camera watch condition.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "watch_id": {"type": "STRING", "description": "The watch ID to remove."},
        },
        "required": ["watch_id"]
    }
}

list_watches_tool = {
    "name": "list_watches",
    "description": "Lists all active camera watch conditions.",
    "parameters": {"type": "OBJECT", "properties": {}},
}

# ---- Unified device tools ----
list_all_devices_tool = {
    "name": "list_all_devices",
    "description": "Lists all smart home devices across all connected protocols (TP-Link Kasa and Home Assistant). Use this before controlling a device to get the correct device ID.",
    "parameters": {"type": "OBJECT", "properties": {}},
}

control_device_tool = {
    "name": "control_device",
    "description": "Controls a smart home device by ID. Actions: 'turn_on', 'turn_off', 'toggle', 'set'. For 'set', pass brightness (0-100) and/or color (name or 'warm').",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "device_id":   {"type": "STRING",  "description": "Device ID or IP from list_all_devices."},
            "action":      {"type": "STRING",  "description": "Action: 'turn_on', 'turn_off', 'toggle', or 'set'."},
            "brightness":  {"type": "INTEGER", "description": "Brightness 0-100 (optional, for lights)."},
            "color":       {"type": "STRING",  "description": "Color name or 'warm' (optional, for lights)."},
            "temperature": {"type": "NUMBER",  "description": "Target temperature for climate devices."},
        },
        "required": ["device_id", "action"]
    }
}

get_device_state_tool = {
    "name": "get_device_state",
    "description": "Returns the current state and attributes of a specific device.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "device_id": {"type": "STRING", "description": "Device ID or IP."},
        },
        "required": ["device_id"]
    }
}

tools_list = [{"function_declarations": [
    generate_cad_prototype_tool,
    write_file_tool,
    read_directory_tool,
    read_file_tool,
    # Scheduler
    create_reminder_tool,
    list_reminders_tool,
    cancel_reminder_tool,
    snooze_reminder_tool,
    create_routine_tool,
    list_routines_tool,
    # Desktop
    get_system_info_tool,
    launch_app_tool,
    list_running_apps_tool,
    focus_window_tool,
    take_screenshot_tool,
    search_files_tool,
    read_clipboard_tool,
    write_clipboard_tool,
    # Vision
    describe_camera_tool,
    detect_presence_tool,
    watch_for_tool,
    stop_watching_tool,
    list_watches_tool,
    # Devices (unified)
    list_all_devices_tool,
    control_device_tool,
    get_device_state_tool,
]}]


