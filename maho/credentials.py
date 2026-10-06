"""API key storage in the current user's Windows Credential Manager."""

import ctypes
import os
from ctypes import wintypes

TARGET = "Maho/AssemblyAI"
OPENAI_TARGET = "Maho/OpenAI"


class Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def _api():
    if os.name != "nt":
        raise RuntimeError("Use ASSEMBLYAI_API_KEY on non-Windows systems.")
    api = ctypes.WinDLL("advapi32", use_last_error=True)
    api.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
    api.CredWriteW.restype = wintypes.BOOL
    api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                             ctypes.POINTER(ctypes.POINTER(Credential))]
    api.CredReadW.restype = wintypes.BOOL
    api.CredFree.argtypes = [ctypes.c_void_p]
    api.CredFree.restype = None
    return api


def save_key(key: str, service="assemblyai") -> None:
    key = key.strip()
    if not key or len(key.encode("utf-8")) > 2560:
        raise ValueError("Enter a valid API key.")
    api = _api()
    blob = (ctypes.c_ubyte * len(key.encode("utf-8"))).from_buffer_copy(key.encode("utf-8"))
    cred = Credential()
    cred.Type = 1  # CRED_TYPE_GENERIC
    cred.TargetName = OPENAI_TARGET if service == "openai" else TARGET
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = blob
    cred.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE (current user)
    cred.UserName = "OpenAI" if service == "openai" else "AssemblyAI"
    if not api.CredWriteW(ctypes.byref(cred), 0):
        raise ctypes.WinError(ctypes.get_last_error())


def get_key(service="assemblyai") -> str:
    variable = "OPENAI_API_KEY" if service == "openai" else "ASSEMBLYAI_API_KEY"
    key = os.environ.get(variable, "").strip()
    if key:
        return key
    if os.name == "nt":
        api = _api()
        pointer = ctypes.POINTER(Credential)()
        target = OPENAI_TARGET if service == "openai" else TARGET
        if api.CredReadW(target, 1, 0, ctypes.byref(pointer)):
            try:
                cred = pointer.contents
                return ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize).decode("utf-8")
            finally:
                api.CredFree(pointer)
        if ctypes.get_last_error() != 1168:  # ERROR_NOT_FOUND
            raise ctypes.WinError(ctypes.get_last_error())
    command = f"maho set-key --service {service}"
    raise RuntimeError(f"No {service} API key configured. Run '{command}' or set {variable}.")
