/**
 * Socket.IO event name constants.
 * Mirrors backend Events class in core/event_bus.py + legacy server.py events.
 */

// Incoming (server -> client)
export const CONNECT = 'connect';
export const DISCONNECT = 'disconnect';
export const STATUS = 'status';
export const ERROR = 'error';
export const AUDIO_DATA = 'audio_data';
export const AUTH_STATUS = 'auth_status';
export const AUTH_FRAME = 'auth_frame';
export const SETTINGS = 'settings';
export const CAD_DATA = 'cad_data';
export const CAD_STATUS = 'cad_status';
export const CAD_THOUGHT = 'cad_thought';
export const BROWSER_FRAME = 'browser_frame';
export const TRANSCRIPTION = 'transcription';
export const TOOL_CONFIRMATION_REQUEST = 'tool_confirmation_request';
export const REQUEST_PRINT_WINDOW = 'request_print_window';
export const KASA_DEVICES = 'kasa_devices';
export const KASA_UPDATE = 'kasa_update';
export const PROJECT_UPDATE = 'project_update';
export const PRINTER_LIST = 'printer_list';
export const SLICING_PROGRESS = 'slicing_progress';
export const PRINT_STATUS_UPDATE = 'print_status_update';
export const PRINT_RESULT = 'print_result';

// Outgoing (client -> server)
export const START_AUDIO = 'start_audio';
export const STOP_AUDIO = 'stop_audio';
export const PAUSE_AUDIO = 'pause_audio';
export const RESUME_AUDIO = 'resume_audio';
export const USER_INPUT = 'user_input';
export const VIDEO_FRAME = 'video_frame';
export const GET_SETTINGS = 'get_settings';
export const UPDATE_SETTINGS = 'update_settings';
export const CONFIRM_TOOL = 'confirm_tool';
export const DISCOVER_KASA = 'discover_kasa';
export const CONTROL_KASA = 'control_kasa';
export const DISCOVER_PRINTERS = 'discover_printers';
export const ADD_PRINTER = 'add_printer';
export const GENERATE_CAD = 'generate_cad';
export const ITERATE_CAD = 'iterate_cad';
export const PROMPT_WEB_AGENT = 'prompt_web_agent';
export const UPLOAD_MEMORY = 'upload_memory';
export const SHUTDOWN = 'shutdown';
