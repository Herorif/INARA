"""Current-Windows-account checkpoint protection. Not a hardware rollback counter."""

import ctypes as c
from ctypes import wintypes as w
import sys

MAX_BYTES = 1_048_576
ENTROPY = b"INARA:managed-checkpoint:v1"


class Blob(c.Structure):
    _fields_ = [("size", w.DWORD), ("data", c.c_void_p)]


def convert(raw, decrypt=False):
    if sys.platform != "win32" or not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_BYTES:
        raise ValueError("Checkpoint protection requires bounded bytes and Windows")
    crypt = c.WinDLL("crypt32.dll", winmode=0x800, use_last_error=True)
    kernel = c.WinDLL("kernel32.dll", winmode=0x800, use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [
        c.POINTER(Blob),
        c.c_void_p,
        c.POINTER(Blob),
        c.c_void_p,
        c.c_void_p,
        w.DWORD,
        c.POINTER(Blob),
    ]
    function.restype = w.BOOL
    kernel.LocalFree.argtypes, kernel.LocalFree.restype = [c.c_void_p], c.c_void_p
    buffer, entropy = c.create_string_buffer(raw), c.create_string_buffer(ENTROPY)
    source = Blob(len(raw), c.cast(buffer, c.c_void_p))
    context = Blob(len(ENTROPY), c.cast(entropy, c.c_void_p))
    output = Blob()
    try:
        # UI_FORBIDDEN only; deliberately NOT LOCAL_MACHINE.
        if not function(c.byref(source), None, c.byref(context), None, None, 1, c.byref(output)):
            raise ValueError("Original-account checkpoint protection refused")
        if not output.data or not 1 <= output.size <= MAX_BYTES:
            raise ValueError("Invalid protected checkpoint size")
        return c.string_at(output.data, output.size)
    finally:
        if output.data:
            kernel.LocalFree(output.data)


def seal(raw):
    return convert(raw)


def open_sealed(raw):
    return convert(raw, True)
