"""Current-user Windows DPAPI storage; no plaintext fallback or dependencies."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path

from .engine import atomic_write


class DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(data: bytes, *, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise ValueError("Las credenciales requieren Windows y su protección DPAPI; no hay almacenamiento en texto plano.")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [ctypes.POINTER(DataBlob), wintypes.LPCWSTR,
        ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob)]
    crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(DataBlob), ctypes.c_void_p,
        ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob)]
    crypt32.CryptProtectData.restype = crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    # Retain input storage until Crypt*Data has returned.
    buffer = ctypes.create_string_buffer(data)
    source = DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = DataBlob()
    operation = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    description = None if decrypt else "emepetres Last.fm"
    # CRYPTPROTECT_UI_FORBIDDEN; deliberately not CRYPTPROTECT_LOCAL_MACHINE.
    if not operation(ctypes.byref(source), description, None, None, None, 1, ctypes.byref(target)):
        raise ValueError("Windows no pudo descifrar las credenciales. Usa la misma cuenta de Windows o vuelve a configurar Last.fm."
                         if decrypt else "Windows no pudo proteger las credenciales; no se ha guardado texto plano.")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(target.pbData, ctypes.c_void_p))


def protect(data: bytes) -> bytes:
    return _crypt(data, decrypt=False)


def unprotect(data: bytes) -> bytes:
    return _crypt(data, decrypt=True)


class Vault:
    def __init__(self, directory: Path):
        self.path = Path(directory) / "credentials.dpapi"

    def load(self) -> dict:
        if not self.path.exists():
            return {}
        if self.path.stat().st_size > 1_000_000:
            raise ValueError("El almacén de credenciales no tiene un formato válido.")
        try:
            value = json.loads(unprotect(self.path.read_bytes()).decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            raise ValueError("El almacén de credenciales no tiene un formato válido.") from None
        if not isinstance(value, dict):
            raise ValueError("El almacén de credenciales no tiene un formato válido.")
        return value

    def save(self, value: dict):
        if not isinstance(value, dict):
            raise ValueError("Las credenciales deben ser un objeto de configuración.")
        # Encrypt before touching the filesystem. There is no plaintext temp file.
        encrypted = protect(json.dumps(value, ensure_ascii=False).encode("utf-8"))
        atomic_write(self.path, encrypted)

    def clear(self):
        self.path.unlink(missing_ok=True)
