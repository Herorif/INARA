"""Which microphone Windows uses by default, read without PortAudio and without opening audio.

PortAudio (sounddevice) reads the device list once, when it is initialised, and the core
re-initialises it only with no stream open (``AudioDevices.refresh``). While "Hey Jarvis"
listens its microphone is always open, so PortAudio alone never notices a new Windows
default or a plugged-in microphone. ``fingerprint()`` asks Windows Core Audio directly
(``IMMDeviceEnumerator``, through ctypes; no extra package): the endpoint ids of the default
capture device (console and multimedia roles) and of every active capture device. It only
reads ids: no device is activated, opened or recorded. A changed fingerprint tells the wake
listener to release its stream, let PortAudio re-read the devices, and reopen
(services/wake_listening.py).

Off Windows, or when Core Audio cannot answer, ``fingerprint()`` returns None and nothing
follows the default (sessions still resolve it when they open).
"""

import ctypes
import sys

from services.log import get_logger

logger = get_logger(__name__)

CLSID_MM_DEVICE_ENUMERATOR = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
IID_IMM_DEVICE_ENUMERATOR = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
CLSCTX_INPROC_SERVER = 0x1
COINIT_MULTITHREADED = 0x0
E_CAPTURE = 1  # EDataFlow eCapture
ROLES = (0, 1)  # ERole eConsole, eMultimedia (Sound settings sets both together)
DEVICE_STATE_ACTIVE = 0x1
S_OK, S_FALSE = 0, 1
RPC_E_CHANGED_MODE = -2147417850  # 0x80010106: COM already set up differently on this thread
E_NOTFOUND = -2147023728  # 0x80070490: no capture device
# Vtable slots (IUnknown takes 0-2).
ENUM_AUDIO_ENDPOINTS, GET_DEFAULT_AUDIO_ENDPOINT = 3, 4  # IMMDeviceEnumerator
COLLECTION_GET_COUNT, COLLECTION_ITEM = 3, 4  # IMMDeviceCollection
DEVICE_GET_ID = 5  # IMMDevice
RELEASE = 2


class _GUID(ctypes.Structure):
    _fields_ = [
        ("data1", ctypes.c_uint32),
        ("data2", ctypes.c_uint16),
        ("data3", ctypes.c_uint16),
        ("data4", ctypes.c_ubyte * 8),
    ]


class _Com:
    """The few ole32 functions and a vtable caller; built only on Windows."""

    def __init__(self):
        ole32 = ctypes.WinDLL("ole32")
        self.ole32 = ole32
        ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        ole32.CoInitializeEx.restype = ctypes.c_long
        ole32.CoUninitialize.argtypes = []
        ole32.CoUninitialize.restype = None
        ole32.CLSIDFromString.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(_GUID)]
        ole32.CLSIDFromString.restype = ctypes.c_long
        ole32.CoCreateInstance.argtypes = [
            ctypes.POINTER(_GUID),
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(_GUID),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        ole32.CoCreateInstance.restype = ctypes.c_long
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        ole32.CoTaskMemFree.restype = None

    def guid(self, text):
        value = _GUID()
        _check(self.ole32.CLSIDFromString(text, ctypes.byref(value)), "CLSIDFromString")
        return value

    @staticmethod
    def call(pointer, slot, restype, argtypes, *args):
        """``pointer->lpVtbl[slot](pointer, *args)``."""
        table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        prototype = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
        return prototype(table[slot])(pointer, *args)

    def release(self, pointer):
        if pointer:
            self.call(pointer, RELEASE, ctypes.c_ulong, ())

    def device_id(self, device):
        text = ctypes.c_void_p()
        _check(
            self.call(device, DEVICE_GET_ID, ctypes.c_long, (ctypes.POINTER(ctypes.c_void_p),),
                      ctypes.byref(text)),
            "IMMDevice::GetId",
        )
        try:
            return ctypes.wstring_at(text.value) if text.value else ""
        finally:
            self.ole32.CoTaskMemFree(text)

    def default_id(self, enumerator, role):
        device = ctypes.c_void_p()
        result = self.call(
            enumerator, GET_DEFAULT_AUDIO_ENDPOINT, ctypes.c_long,
            (ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)),
            E_CAPTURE, role, ctypes.byref(device),
        )
        if result == E_NOTFOUND:
            return None
        _check(result, "GetDefaultAudioEndpoint")
        try:
            return self.device_id(device)
        finally:
            self.release(device)

    def active_ids(self, enumerator):
        collection = ctypes.c_void_p()
        _check(
            self.call(
                enumerator, ENUM_AUDIO_ENDPOINTS, ctypes.c_long,
                (ctypes.c_int, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)),
                E_CAPTURE, DEVICE_STATE_ACTIVE, ctypes.byref(collection),
            ),
            "EnumAudioEndpoints",
        )
        try:
            count = ctypes.c_uint()
            _check(
                self.call(collection, COLLECTION_GET_COUNT, ctypes.c_long,
                          (ctypes.POINTER(ctypes.c_uint),), ctypes.byref(count)),
                "IMMDeviceCollection::GetCount",
            )
            ids = []
            for index in range(min(count.value, 256)):
                device = ctypes.c_void_p()
                _check(
                    self.call(collection, COLLECTION_ITEM, ctypes.c_long,
                              (ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)),
                              index, ctypes.byref(device)),
                    "IMMDeviceCollection::Item",
                )
                try:
                    ids.append(self.device_id(device))
                finally:
                    self.release(device)
            return tuple(sorted(ids))
        finally:
            self.release(collection)


def _check(result, what):
    if result < 0:
        raise OSError(f"{what} failed (0x{result & 0xFFFFFFFF:08X})")


_com = None


def fingerprint():
    """(default capture ids per role, active capture ids), or None off Windows.

    Any thread: COM is entered (multithreaded) and left around each call. Raises OSError
    when Core Audio refuses (the caller stops following the default).
    """
    global _com
    if sys.platform != "win32":
        return None
    if _com is None:
        _com = _Com()
    com = _com
    started = com.ole32.CoInitializeEx(None, COINIT_MULTITHREADED)
    if started < 0 and started != RPC_E_CHANGED_MODE:
        _check(started, "CoInitializeEx")
    try:
        enumerator = ctypes.c_void_p()
        _check(
            com.ole32.CoCreateInstance(
                ctypes.byref(com.guid(CLSID_MM_DEVICE_ENUMERATOR)),
                None,
                CLSCTX_INPROC_SERVER,
                ctypes.byref(com.guid(IID_IMM_DEVICE_ENUMERATOR)),
                ctypes.byref(enumerator),
            ),
            "CoCreateInstance(MMDeviceEnumerator)",
        )
        try:
            defaults = tuple(com.default_id(enumerator, role) for role in ROLES)
            return defaults, com.active_ids(enumerator)
        finally:
            com.release(enumerator)
    finally:
        if started in (S_OK, S_FALSE):
            com.ole32.CoUninitialize()
