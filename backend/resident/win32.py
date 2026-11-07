"""Small typed Win32 boundary: tray, single instance and owned workspace jobs."""

import ctypes as C
from ctypes import wintypes as W
import json
import os
import queue
import subprocess
import time
from pathlib import Path

from resident.state import TRAY_ICONS
from services.log import get_logger

MF_CHECKED = 0x8
# Tray icons: LoadImageW(IMAGE_ICON, LR_LOADFROMFILE) at the small-icon size SM_CXSMICON.
IMAGE_ICON, LR_LOADFROMFILE, SM_CXSMICON = 1, 0x10, 49
NIM_ADD, NIM_MODIFY, NIM_DELETE, NIM_SETVERSION = 0, 1, 2, 4
NIF_MESSAGE, NIF_ICON, NIF_TIP = 1, 2, 4
WM_SETTINGCHANGE, WM_DISPLAYCHANGE = 0x1A, 0x7E
# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2: the shell gets crisp icons at every scale.
PER_MONITOR_AWARE_V2 = -4
LRESULT = C.c_ssize_t
WPARAM = C.c_size_t
LPARAM = C.c_ssize_t
WNDPROC = C.WINFUNCTYPE(LRESULT, W.HWND, W.UINT, WPARAM, LPARAM)
kernel = C.WinDLL("kernel32", use_last_error=True)
user = C.WinDLL("user32", use_last_error=True)
shell = C.WinDLL("shell32", use_last_error=True)
logger = get_logger(__name__)


def api(library, name, arguments, result):
    function = getattr(library, name)
    function.argtypes, function.restype = arguments, result
    return function


def checked(result):
    if not result:
        raise C.WinError(C.get_last_error())
    return result


close_handle = api(kernel, "CloseHandle", [W.HANDLE], W.BOOL)


def enable_dpi_awareness():
    """Make the process per-monitor DPI aware (v2) before it creates any window, so Windows
    does not stretch its tray icon above 100% scaling. False, silently, where unsupported."""
    try:
        function = api(user, "SetProcessDpiAwarenessContext", [C.c_ssize_t], W.BOOL)
        return bool(function(PER_MONITOR_AWARE_V2))
    except Exception:
        return False


def small_icon_size():
    """The small-icon size (SM_CXSMICON) at the system DPI, for both dimensions."""
    try:
        dpi = api(user, "GetDpiForSystem", [], W.UINT)()
        size = api(user, "GetSystemMetricsForDpi", [C.c_int, W.UINT], C.c_int)(SM_CXSMICON, dpi)
    except (AttributeError, OSError):
        size = 0
    if size <= 0:
        size = api(user, "GetSystemMetrics", [C.c_int], C.c_int)(SM_CXSMICON)
    return size if size > 0 else 16


class Security(C.Structure):
    _fields_ = [("size", W.DWORD), ("descriptor", W.LPVOID), ("inherit", W.BOOL)]


class Startup(C.Structure):
    _fields_ = [
        ("cb", W.DWORD),
        ("reserved", W.LPWSTR),
        ("desktop", W.LPWSTR),
        ("title", W.LPWSTR),
        ("x", W.DWORD),
        ("y", W.DWORD),
        ("width", W.DWORD),
        ("height", W.DWORD),
        ("chars_x", W.DWORD),
        ("chars_y", W.DWORD),
        ("fill", W.DWORD),
        ("flags", W.DWORD),
        ("show", W.WORD),
        ("reserved_size", W.WORD),
        ("reserved_bytes", W.LPVOID),
        ("stdin", W.HANDLE),
        ("stdout", W.HANDLE),
        ("stderr", W.HANDLE),
    ]


class StartupEx(C.Structure):
    _fields_ = [("startup", Startup), ("attributes", W.LPVOID)]


class ProcessInfo(C.Structure):
    _fields_ = [("process", W.HANDLE), ("thread", W.HANDLE), ("pid", W.DWORD), ("tid", W.DWORD)]


class BasicLimit(C.Structure):
    _fields_ = [
        ("process_time", C.c_longlong),
        ("job_time", C.c_longlong),
        ("flags", W.DWORD),
        ("minimum", C.c_size_t),
        ("maximum", C.c_size_t),
        ("active", W.DWORD),
        ("affinity", C.c_size_t),
        ("priority", W.DWORD),
        ("scheduling", W.DWORD),
    ]


class IO(C.Structure):
    _fields_ = [
        (name, C.c_ulonglong)
        for name in (
            "read_ops",
            "write_ops",
            "other_ops",
            "read_bytes",
            "write_bytes",
            "other_bytes",
        )
    ]


class ExtendedLimit(C.Structure):
    _fields_ = [
        ("basic", BasicLimit),
        ("io", IO),
        ("process_memory", C.c_size_t),
        ("job_memory", C.c_size_t),
        ("peak_process_memory", C.c_size_t),
        ("peak_job_memory", C.c_size_t),
    ]


class WorkspaceProcess:
    """Atomically assign the child to a kill-on-close job, with pipe-only bootstrap.

    ``arguments`` replaces the default ``executable [-B] entrypoint`` command line
    and ``environment`` adds variables to the filtered environment (for example
    a credential that must not appear on the command line). ``bootstrap=None``
    writes nothing to the child's stdin pipe.
    """

    def __init__(self, executable, entrypoint, bootstrap, cwd, *, arguments=None,
                 environment=None):
        self.process = self.job = None
        read, write, null = W.HANDLE(), W.HANDLE(), None
        attributes = None
        attributes_initialized = False
        information = ProcessInfo()
        security = Security(C.sizeof(Security), None, True)
        try:
            self.job = checked(
                api(kernel, "CreateJobObjectW", [W.LPVOID, W.LPCWSTR], W.HANDLE)(None, None)
            )
            limits = ExtendedLimit()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            checked(
                api(
                    kernel,
                    "SetInformationJobObject",
                    [W.HANDLE, C.c_int, W.LPVOID, W.DWORD],
                    W.BOOL,
                )(self.job, 9, C.byref(limits), C.sizeof(limits))
            )
            checked(
                api(
                    kernel,
                    "CreatePipe",
                    [C.POINTER(W.HANDLE), C.POINTER(W.HANDLE), C.POINTER(Security), W.DWORD],
                    W.BOOL,
                )(C.byref(read), C.byref(write), C.byref(security), 4096)
            )
            checked(
                api(kernel, "SetHandleInformation", [W.HANDLE, W.DWORD, W.DWORD], W.BOOL)(
                    write, 1, 0
                )
            )
            null = checked(
                api(
                    kernel,
                    "CreateFileW",
                    [W.LPCWSTR, W.DWORD, W.DWORD, C.POINTER(Security), W.DWORD, W.DWORD, W.HANDLE],
                    W.HANDLE,
                )("NUL", 0x40000000, 3, C.byref(security), 3, 0x80, None)
            )
            if null == C.c_void_p(-1).value:
                null = None
                raise C.WinError(C.get_last_error())
            size = C.c_size_t()
            initialize = api(
                kernel,
                "InitializeProcThreadAttributeList",
                [W.LPVOID, W.DWORD, W.DWORD, C.POINTER(C.c_size_t)],
                W.BOOL,
            )
            initialize(None, 2, 0, C.byref(size))
            attributes = C.create_string_buffer(size.value)
            checked(initialize(attributes, 2, 0, C.byref(size)))
            attributes_initialized = True
            update = api(
                kernel,
                "UpdateProcThreadAttribute",
                [W.LPVOID, W.DWORD, C.c_size_t, W.LPVOID, C.c_size_t, W.LPVOID, W.LPVOID],
                W.BOOL,
            )
            inherited = (W.HANDLE * 2)(read.value, null)
            jobs = (W.HANDLE * 1)(self.job)
            checked(update(attributes, 0, 0x20002, inherited, C.sizeof(inherited), None, None))
            checked(update(attributes, 0, 0x2000D, jobs, C.sizeof(jobs), None, None))
            startup = StartupEx()
            startup.startup.cb = C.sizeof(startup)
            startup.startup.flags = 0x101  # STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW
            startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = read, null, null
            startup.attributes = C.cast(attributes, W.LPVOID)
            if arguments is None:
                arguments = [str(executable)]
                if Path(executable).name.lower() in {"python.exe", "pythonw.exe"}:
                    arguments.append("-B")  # Isolated ._pth ignores PYTHONDONTWRITEBYTECODE.
                arguments.append(str(entrypoint))
            command = C.create_unicode_buffer(
                subprocess.list2cmdline([str(item) for item in arguments])
            )
            allowed = {
                "systemroot",
                "systemdrive",
                "programdata",
                "programfiles",
                "programfiles(x86)",
                "programw6432",
                "commonprogramfiles",
                "commonprogramfiles(x86)",
                "commonprogramw6432",
                "public",
                "allusersprofile",
                "windir",
                "path",
                "temp",
                "tmp",
                "appdata",
                "localappdata",
                "userprofile",
                "username",
                "os",
                "homedrive",
                "homepath",
                "processor_architecture",
                "number_of_processors",
                "pythondontwritebytecode",
                "comspec",
                "pathext",
            }
            variables = {key: value for key, value in os.environ.items() if key.lower() in allowed}
            for key, value in (environment or {}).items():
                for existing in [name for name in variables if name.casefold() == key.casefold()]:
                    del variables[existing]
                variables[key] = value
            environment = C.create_unicode_buffer(
                "\0".join(
                    f"{key}={value}"
                    for key, value in sorted(variables.items(), key=lambda item: item[0].casefold())
                )
                + "\0\0"
            )
            checked(
                api(
                    kernel,
                    "CreateProcessW",
                    [
                        W.LPCWSTR,
                        W.LPWSTR,
                        W.LPVOID,
                        W.LPVOID,
                        W.BOOL,
                        W.DWORD,
                        W.LPVOID,
                        W.LPCWSTR,
                        C.POINTER(StartupEx),
                        C.POINTER(ProcessInfo),
                    ],
                    W.BOOL,
                )(
                    str(executable),
                    command,
                    None,
                    None,
                    True,
                    0x80000 | 0x4 | 0x400 | 0x08000000,
                    environment,
                    str(cwd),
                    C.byref(startup),
                    C.byref(information),
                )
            )
            self.process, self.pid = information.process, information.pid
            if bootstrap is not None:
                data = json.dumps(bootstrap).encode()
                if len(data) > 4096:
                    raise ValueError("Workspace bootstrap exceeds pipe limit")
                written = W.DWORD()
                checked(
                    api(
                        kernel,
                        "WriteFile",
                        [W.HANDLE, W.LPCVOID, W.DWORD, C.POINTER(W.DWORD), W.LPVOID],
                        W.BOOL,
                    )(write, data, len(data), C.byref(written), None)
                )
                if written.value != len(data):
                    raise OSError("Workspace bootstrap write was incomplete")
            close_handle(write)
            write = W.HANDLE()
            if api(kernel, "ResumeThread", [W.HANDLE], W.DWORD)(information.thread) == 0xFFFFFFFF:
                raise C.WinError(C.get_last_error())
        except BaseException:
            self.close()
            raise
        finally:
            for handle in (read.value, write.value, null, information.thread):
                if handle:
                    close_handle(handle)
            if attributes_initialized:
                api(kernel, "DeleteProcThreadAttributeList", [W.LPVOID], None)(attributes)

    def alive(self):
        return bool(
            self.process
            and api(kernel, "WaitForSingleObject", [W.HANDLE, W.DWORD], W.DWORD)(self.process, 0)
            == 0x102
        )

    def exit_code(self):
        value = W.DWORD()
        checked(
            api(kernel, "GetExitCodeProcess", [W.HANDLE, C.POINTER(W.DWORD)], W.BOOL)(
                self.process, C.byref(value)
            )
        )
        return value.value

    def active_processes(self):
        """Number of processes still running anywhere in the owned job tree."""
        if not self.job:
            return 0
        info = BasicAccounting()
        checked(
            api(
                kernel,
                "QueryInformationJobObject",
                [W.HANDLE, C.c_int, W.LPVOID, W.DWORD, W.LPVOID],
                W.BOOL,
            )(self.job, 1, C.byref(info), C.sizeof(info), None)
        )
        return info.active

    def terminate(self, timeout=5.0):
        """Kill the whole job tree and wait until no process in it remains.

        Returns True only after the root and every descendant have exited;
        the handles are closed either way.
        """
        try:
            if self.job:
                api(kernel, "TerminateJobObject", [W.HANDLE, W.UINT], W.BOOL)(self.job, 1)
            deadline = time.monotonic() + timeout
            while True:
                if not self.alive() and self.active_processes() == 0:
                    return True
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.01)
        finally:
            self.close()

    def close(self):
        if self.job:
            close_handle(self.job)
            self.job = None
        if self.process:
            close_handle(self.process)
            self.process = None


class BasicAccounting(C.Structure):
    _fields_ = [
        ("user_time", C.c_longlong),
        ("kernel_time", C.c_longlong),
        ("period_user_time", C.c_longlong),
        ("period_kernel_time", C.c_longlong),
        ("page_faults", W.DWORD),
        ("total", W.DWORD),
        ("active", W.DWORD),
        ("terminated", W.DWORD),
    ]


class WindowClass(C.Structure):
    _fields_ = [
        ("size", W.UINT),
        ("style", W.UINT),
        ("procedure", WNDPROC),
        ("class_extra", C.c_int),
        ("window_extra", C.c_int),
        ("instance", W.HINSTANCE),
        ("icon", W.HICON),
        ("cursor", W.HANDLE),
        ("brush", W.HBRUSH),
        ("menu", W.LPCWSTR),
        ("name", W.LPCWSTR),
        ("small_icon", W.HICON),
    ]


class GUID(C.Structure):
    _fields_ = [("a", W.DWORD), ("b", W.WORD), ("c", W.WORD), ("d", C.c_ubyte * 8)]


class NotifyData(C.Structure):
    _fields_ = [
        ("size", W.DWORD),
        ("window", W.HWND),
        ("id", W.UINT),
        ("flags", W.UINT),
        ("message", W.UINT),
        ("icon", W.HICON),
        ("tip", W.WCHAR * 128),
        ("state", W.DWORD),
        ("state_mask", W.DWORD),
        ("info", W.WCHAR * 256),
        ("version", W.UINT),
        ("title", W.WCHAR * 64),
        ("info_flags", W.DWORD),
        ("guid", GUID),
        ("balloon_icon", W.HICON),
    ]


class Tray:
    OPEN, QUIT, CALL, NOTIFY = 0x8001, 0x8002, 0x8003, 0x8004

    def __init__(self, key, icons, on_action, on_tick, suppress_notifications=False,
                 icon_state="paused"):
        """``icons``: the assets/icons folder (tray/jarvis-<state>.ico, jarvis.ico fallback);
        ``icon_state``: the first state icon shown (resident/state.py's ``tray_icon``)."""
        self.name = f"JARVIS.Native.{key}"
        self.on_action, self.on_tick = on_action, on_tick
        self.talking = False  # a tray voice session is on: the menu offers Stop talking
        self.wake_word = False  # voice.wake_word is on: Listen for "Hey Jarvis" is checked
        self.calls = queue.Queue()
        self.suppress_notifications = suppress_notifications
        self.notification_count = 0
        self.window = self.icon = None
        self.icon_folder = Path(icons)
        self.icons = {}
        self.icon_state = icon_state if icon_state in TRAY_ICONS else "ready"
        self.mutex = checked(
            api(kernel, "CreateMutexW", [W.LPVOID, W.BOOL, W.LPCWSTR], W.HANDLE)(
                None, False, f"Local\\{self.name}"
            )
        )
        self.secondary = C.get_last_error() == 183
        if self.secondary:
            window = api(user, "FindWindowW", [W.LPCWSTR, W.LPCWSTR], W.HWND)(self.name, self.name)
            if window:
                api(user, "PostMessageW", [W.HWND, W.UINT, WPARAM, LPARAM], W.BOOL)(
                    window, self.OPEN, 0, 0
                )
            return
        self.procedure = WNDPROC(self._message)
        instance = api(kernel, "GetModuleHandleW", [W.LPCWSTR], W.HMODULE)(None)
        self.icons = self.load_icons()
        self.icon = self.icons[self.icon_state]
        self.window_class = WindowClass()
        self.window_class.size, self.window_class.instance = C.sizeof(WindowClass), instance
        self.window_class.procedure, self.window_class.name = self.procedure, self.name
        checked(
            api(user, "RegisterClassExW", [C.POINTER(WindowClass)], W.ATOM)(
                C.byref(self.window_class)
            )
        )
        self.window = checked(
            api(
                user,
                "CreateWindowExW",
                [
                    W.DWORD,
                    W.LPCWSTR,
                    W.LPCWSTR,
                    W.DWORD,
                    C.c_int,
                    C.c_int,
                    C.c_int,
                    C.c_int,
                    W.HWND,
                    W.HMENU,
                    W.HINSTANCE,
                    W.LPVOID,
                ],
                W.HWND,
            )(0, self.name, self.name, 0, 0, 0, 0, 0, None, None, instance, None)
        )
        self.taskbar_message = api(user, "RegisterWindowMessageW", [W.LPCWSTR], W.UINT)(
            "TaskbarCreated"
        )
        self.data = NotifyData()
        self.data.size, self.data.window, self.data.id = C.sizeof(NotifyData), self.window, 1
        self.data.flags, self.data.message, self.data.icon = (
            NIF_MESSAGE | NIF_ICON | NIF_TIP, self.NOTIFY, self.icon
        )
        self.data.tip = "JARVIS · Resident starting"
        self._add_icon()
        self.hotkey = bool(
            api(user, "RegisterHotKey", [W.HWND, C.c_int, W.UINT, W.UINT], W.BOOL)(
                self.window, 1, 0x4000 | 2 | 4, 0x20
            )
        )
        checked(
            api(user, "SetTimer", [W.HWND, C.c_size_t, W.UINT, W.LPVOID], C.c_size_t)(
                self.window, 1, 1000, None
            )
        )

    def _add_icon(self):
        checked(
            api(shell, "Shell_NotifyIconW", [W.DWORD, C.POINTER(NotifyData)], W.BOOL)(
                NIM_ADD, C.byref(self.data)
            )
        )
        self.data.version = 4
        checked(shell.Shell_NotifyIconW(NIM_SETVERSION, C.byref(self.data)))

    # --- state icons -----------------------------------------------------------------------

    def load_icons(self):
        """{state: HICON} for the five state icons at the small-icon size. If any fails to
        load, every state uses assets/icons/jarvis.ico instead (logged in one line)."""
        size = small_icon_size()
        load = api(
            user, "LoadImageW", [W.HINSTANCE, W.LPCWSTR, W.UINT, C.c_int, C.c_int, W.UINT], W.HANDLE
        )

        def image(path):
            return checked(load(None, str(path.resolve()), IMAGE_ICON, size, size, LR_LOADFROMFILE))

        icons = {}
        try:
            for name in TRAY_ICONS:
                icons[name] = image(self.icon_folder / "tray" / f"jarvis-{name}.ico")
            return icons
        except OSError as exc:
            self.destroy_icons(icons)
            logger.warning("Tray state icons could not load (%s); using jarvis.ico", type(exc).__name__)
        fallback = image(self.icon_folder / "jarvis.ico")
        return dict.fromkeys(TRAY_ICONS, fallback)

    @staticmethod
    def destroy_icons(icons):
        destroy = api(user, "DestroyIcon", [W.HICON], W.BOOL)
        for handle in set(icons.values()):
            if handle:
                destroy(handle)

    def show_icon(self, name):
        """Switch to the ``name`` state icon; NIM_MODIFY (NIF_ICON) only when it changes."""
        if name not in TRAY_ICONS or name == self.icon_state or not self.icons:
            return False
        self.icon_state, self.icon = name, self.icons[name]
        self.data.icon, self.data.flags = self.icon, NIF_ICON
        shell.Shell_NotifyIconW(NIM_MODIFY, C.byref(self.data))
        return True

    def reload_icons(self, add=False):
        """Reload the icons at the current small-icon size (display or DPI change, or a new
        taskbar), show the current state's, then destroy the old handles. ``add``: the
        taskbar was recreated, so the icon is added again rather than modified."""
        old, reloaded = self.icons, True
        try:
            self.icons = self.load_icons()
        except OSError:
            logger.warning("Tray icons could not reload; keeping the current ones")
            old, reloaded = {}, False
        self.icon = self.icons[self.icon_state]
        self.data.icon = self.icon
        if add:
            self.data.flags = NIF_MESSAGE | NIF_ICON | NIF_TIP
            self._add_icon()
        else:
            self.data.flags = NIF_ICON
            shell.Shell_NotifyIconW(NIM_MODIFY, C.byref(self.data))
        self.destroy_icons(old)
        return reloaded

    def post(self, callback):
        self.calls.put(callback)
        checked(
            api(user, "PostMessageW", [W.HWND, W.UINT, WPARAM, LPARAM], W.BOOL)(
                self.window, self.CALL, 0, 0
            )
        )

    def tooltip(self, value):
        self.data.tip, self.data.flags = value[:127], 4
        shell.Shell_NotifyIconW(1, C.byref(self.data))

    def notify(self, title="JARVIS reminder",
               info="A reminder is ready. Open the command deck to view it."):
        if self.suppress_notifications:
            self.notification_count += 1
            return True
        self.data.flags, self.data.info_flags = 0x10, 1 | 0x80
        self.data.title = title[:63]
        self.data.info = info[:255]
        result = bool(shell.Shell_NotifyIconW(1, C.byref(self.data)))
        if result:
            self.notification_count += 1
        return result

    def menu_items(self):
        talk = ("stop_talking", "Stop talking") if self.talking else ("talk", "Talk to JARVIS")
        return (
            ("open", "Open JARVIS"),
            ("quick", "Quick assistant"),
            talk,
            ("wake_word", 'Listen for "Hey Jarvis"'),
            ("gaming", "Toggle gaming mode"),
            ("retry", "Retry backend"),
            ("quit", "Quit JARVIS"),
        )

    def menu_flags(self, action):
        """MF_CHECKED (0x8) on Listen for "Hey Jarvis" while it is on; else MF_STRING."""
        return MF_CHECKED if action == "wake_word" and getattr(self, "wake_word", False) else 0

    def menu(self):
        menu = checked(api(user, "CreatePopupMenu", [], W.HMENU)())
        append = api(user, "AppendMenuW", [W.HMENU, W.UINT, C.c_size_t, W.LPCWSTR], W.BOOL)
        items = self.menu_items()
        for index, (action, text) in enumerate(items, 1):
            checked(append(menu, self.menu_flags(action), index, text))
        position = W.POINT()
        api(user, "GetCursorPos", [C.POINTER(W.POINT)], W.BOOL)(C.byref(position))
        api(user, "SetForegroundWindow", [W.HWND], W.BOOL)(self.window)
        choice = api(
            user,
            "TrackPopupMenu",
            [W.HMENU, W.UINT, C.c_int, C.c_int, C.c_int, W.HWND, W.LPVOID],
            W.UINT,
        )(menu, 0x100 | 2, position.x, position.y, 0, self.window, None)
        api(user, "DestroyMenu", [W.HMENU], W.BOOL)(menu)
        if 1 <= choice <= len(items):
            self.on_action(items[choice - 1][0])

    def _message(self, window, message, wparam, lparam):
        try:
            if message == self.OPEN or message == 0x312:
                self.on_action("quick" if message == 0x312 else "open")
            elif message == self.QUIT:
                self.on_action("quit")
            elif message == self.CALL:
                while not self.calls.empty():
                    self.calls.get_nowait()()
            elif message == self.NOTIFY:
                event = lparam & 0xFFFF
                if event in (0x202, 0x400, 0x405):
                    self.on_action("open")
                elif event in (0x205, 0x7B):
                    self.menu()
            elif message == 0x113:
                self.on_tick()
            elif message == getattr(self, "taskbar_message", None):
                self.reload_icons(add=True)
            elif message in (WM_DISPLAYCHANGE, WM_SETTINGCHANGE):
                self.reload_icons()
            elif message == 0x10:
                self.on_action("quit")
            elif message == 0x2:
                api(user, "PostQuitMessage", [C.c_int], None)(0)
            else:
                return api(user, "DefWindowProcW", [W.HWND, W.UINT, WPARAM, LPARAM], LRESULT)(
                    window, message, wparam, lparam
                )
        except Exception:
            # Never unwind a Python exception through a native window procedure.
            self.on_action("failed")
        return 0

    def run(self):
        message = W.MSG()
        get = api(user, "GetMessageW", [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT], W.BOOL)
        while True:
            result = get(C.byref(message), None, 0, 0)
            if result == -1:
                raise C.WinError(C.get_last_error())
            if result == 0:
                break
            api(user, "TranslateMessage", [C.POINTER(W.MSG)], W.BOOL)(C.byref(message))
            api(user, "DispatchMessageW", [C.POINTER(W.MSG)], LRESULT)(C.byref(message))

    def close(self):
        if self.window:
            api(user, "UnregisterHotKey", [W.HWND, C.c_int], W.BOOL)(self.window, 1)
            api(user, "KillTimer", [W.HWND, C.c_size_t], W.BOOL)(self.window, 1)
            shell.Shell_NotifyIconW(NIM_DELETE, C.byref(self.data))
            api(user, "DestroyWindow", [W.HWND], W.BOOL)(self.window)
            self.window = None
        if self.icons:
            self.destroy_icons(self.icons)
            self.icons, self.icon = {}, None
        if self.mutex:
            close_handle(self.mutex)
            self.mutex = None
