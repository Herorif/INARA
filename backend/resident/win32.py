"""Small typed Win32 boundary: tray, single instance and owned workspace jobs."""

import ctypes as C
from ctypes import wintypes as W
import json
import os
import queue
import subprocess
from pathlib import Path

LRESULT = C.c_ssize_t
WPARAM = C.c_size_t
LPARAM = C.c_ssize_t
WNDPROC = C.WINFUNCTYPE(LRESULT, W.HWND, W.UINT, WPARAM, LPARAM)
kernel = C.WinDLL("kernel32", use_last_error=True)
user = C.WinDLL("user32", use_last_error=True)
shell = C.WinDLL("shell32", use_last_error=True)


def api(library, name, arguments, result):
    function = getattr(library, name)
    function.argtypes, function.restype = arguments, result
    return function


def checked(result):
    if not result:
        raise C.WinError(C.get_last_error())
    return result


close_handle = api(kernel, "CloseHandle", [W.HANDLE], W.BOOL)


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
    """Atomically assign the child to a kill-on-close job, with pipe-only bootstrap."""

    def __init__(self, executable, entrypoint, bootstrap, cwd):
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
            arguments = [str(executable)]
            if Path(executable).name.lower() in {"python.exe", "pythonw.exe"}:
                arguments.append("-B")  # Isolated ._pth ignores PYTHONDONTWRITEBYTECODE.
            arguments.append(str(entrypoint))
            command = C.create_unicode_buffer(subprocess.list2cmdline(arguments))
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
            environment = C.create_unicode_buffer(
                "\0".join(
                    f"{key}={value}"
                    for key, value in sorted(
                        os.environ.items(), key=lambda item: item[0].casefold()
                    )
                    if key.lower() in allowed
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

    def close(self):
        if self.job:
            close_handle(self.job)
            self.job = None
        if self.process:
            close_handle(self.process)
            self.process = None


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

    def __init__(self, key, icon, on_action, on_tick, suppress_notifications=False):
        self.name = f"INARA.Native.{key}"
        self.on_action, self.on_tick = on_action, on_tick
        self.calls = queue.Queue()
        self.suppress_notifications = suppress_notifications
        self.notification_count = 0
        self.window = self.icon = None
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
        self.icon = checked(
            api(
                user,
                "LoadImageW",
                [W.HINSTANCE, W.LPCWSTR, W.UINT, C.c_int, C.c_int, W.UINT],
                W.HANDLE,
            )(None, str(Path(icon).resolve()), 1, 32, 32, 0x10)
        )
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
        self.data.flags, self.data.message, self.data.icon = 1 | 2 | 4, self.NOTIFY, self.icon
        self.data.tip = "INARA · Resident starting"
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
                0, C.byref(self.data)
            )
        )
        self.data.version = 4
        checked(shell.Shell_NotifyIconW(4, C.byref(self.data)))

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

    def notify(self):
        if self.suppress_notifications:
            self.notification_count += 1
            return True
        self.data.flags, self.data.info_flags = 0x10, 1 | 0x80
        self.data.title = "INARA reminder"
        self.data.info = "A reminder is ready. Open the command deck to view it."
        result = bool(shell.Shell_NotifyIconW(1, C.byref(self.data)))
        if result:
            self.notification_count += 1
        return result

    def menu(self):
        menu = checked(api(user, "CreatePopupMenu", [], W.HMENU)())
        append = api(user, "AppendMenuW", [W.HMENU, W.UINT, C.c_size_t, W.LPCWSTR], W.BOOL)
        for index, text in enumerate(
            ("Open INARA", "Toggle gaming mode", "Retry backend", "Quit INARA"), 1
        ):
            checked(append(menu, 0, index, text))
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
        action = {1: "open", 2: "gaming", 3: "retry", 4: "quit"}.get(choice)
        if action:
            self.on_action(action)

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
                self.data.flags = 1 | 2 | 4
                self._add_icon()
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
            shell.Shell_NotifyIconW(2, C.byref(self.data))
            api(user, "DestroyWindow", [W.HWND], W.BOOL)(self.window)
            self.window = None
        if self.icon:
            api(user, "DestroyIcon", [W.HICON], W.BOOL)(self.icon)
            self.icon = None
        if self.mutex:
            close_handle(self.mutex)
            self.mutex = None
