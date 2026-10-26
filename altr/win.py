"""Capa de Windows (ctypes, sin dependencias): portapapeles, teclas, atajos globales,
reproducción MCI, instancia única y arranque con Windows.

Sólo se importa en Windows. No se pudo probar en Windows al escribirla: los tests de
tests/test_win.py corren en el CI (windows-latest).
"""
from __future__ import annotations

import ctypes
import itertools
import logging
import os
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Callable

from .hotkeys import parse_hotkey

log = logging.getLogger("altr")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
winmm = ctypes.WinDLL("winmm")

# ---------------------------------------------------------------- firmas ctypes
LPVOID = ctypes.c_void_p
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL
user32.CloseClipboard.restype = wintypes.BOOL
user32.EmptyClipboard.restype = wintypes.BOOL
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = LPVOID
user32.SetClipboardData.argtypes = [wintypes.UINT, LPVOID]
user32.SetClipboardData.restype = LPVOID
user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = LPVOID
kernel32.GlobalLock.argtypes = [LPVOID]
kernel32.GlobalLock.restype = LPVOID
kernel32.GlobalUnlock.argtypes = [LPVOID]
kernel32.GlobalUnlock.restype = wintypes.BOOL
kernel32.GlobalFree.argtypes = [LPVOID]
kernel32.GlobalFree.restype = LPVOID
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CreateMutexW.argtypes = [LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = ctypes.c_int
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT,
                                wintypes.UINT, wintypes.UINT]
user32.PeekMessageW.restype = wintypes.BOOL
winmm.mciSendStringW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.UINT, wintypes.HANDLE]
winmm.mciSendStringW.restype = wintypes.DWORD
winmm.mciGetErrorStringW.argtypes = [wintypes.DWORD, wintypes.LPWSTR, wintypes.UINT]
winmm.mciGetErrorStringW.restype = wintypes.BOOL

# ----------------------------------------------------------------- teclas
VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN = 0x10, 0x11, 0x12, 0x5B, 0x5C
VK_C, VK_MASK = 0x43, 0xE8  # 0xE8: tecla "sin asignar", sirve de máscara del menú Alt
KEYEVENTF_KEYUP = 0x0002
INPUT_KEYBOARD = 1


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT


def _key(vk: int, up: bool) -> _INPUT:
    i = _INPUT(type=INPUT_KEYBOARD)
    i.ki = _KEYBDINPUT(wVk=vk, wScan=0, dwFlags=KEYEVENTF_KEYUP if up else 0, time=0, dwExtraInfo=0)
    return i


def send_keys(events: list[tuple[int, bool]]) -> None:
    """events: [(vk, es_soltar)] enviados de una vez, en orden."""
    arr = (_INPUT * len(events))(*[_key(vk, up) for vk, up in events])
    user32.SendInput(len(events), arr, ctypes.sizeof(_INPUT))


def _is_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


# ------------------------------------------------------------ portapapeles
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def _open_clipboard(retries: int = 15) -> bool:
    for _ in range(retries):
        if user32.OpenClipboard(None):
            return True
        time.sleep(0.02)
    return False


def clipboard_sequence() -> int:
    return int(user32.GetClipboardSequenceNumber())


def get_clipboard_text() -> str | None:
    """Texto del portapapeles, o None si está vacío / no es texto."""
    if not _open_clipboard():
        return None
    try:
        if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        p = kernel32.GlobalLock(h)
        if not p:
            return None
        try:
            return ctypes.wstring_at(p)
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


def set_clipboard_text(text: str) -> bool:
    data = (text + "\0").encode("utf-16-le")
    if not _open_clipboard():
        return False
    try:
        user32.EmptyClipboard()
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not h:
            return False
        p = kernel32.GlobalLock(h)
        if not p:
            kernel32.GlobalFree(h)
            return False
        ctypes.memmove(p, data, len(data))
        kernel32.GlobalUnlock(h)
        if not user32.SetClipboardData(CF_UNICODETEXT, h):
            kernel32.GlobalFree(h)
            return False
        return True  # el sistema es dueño del bloque desde acá
    finally:
        user32.CloseClipboard()


def foreground_process_name() -> str:
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
    if not pid.value:
        return ""
    h = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        kernel32.CloseHandle(h)


def capture_selection(restore: bool = True, fallback: bool = True,
                      clipboard_only_apps: list[str] | tuple = ()) -> str:
    """Devuelve el texto seleccionado en la ventana activa (Ctrl+C simulado).

    Si no hay selección (o la app activa está en clipboard_only_apps, donde Ctrl+C
    podría interrumpir un programa) y `fallback`, devuelve el portapapeles actual.
    """
    only = {a.lower() for a in clipboard_only_apps}
    old_text = get_clipboard_text()
    if foreground_process_name() in only:
        return (old_text or "") if fallback else ""

    # Si el usuario todavía tiene Alt apretado, Windows abriría el menú de la ventana al
    # soltarlo: una tecla intermedia "sin asignar" lo evita.
    send_keys([(VK_MASK, False), (VK_MASK, True)])
    deadline = time.monotonic() + 1.0
    mods = (VK_MENU, VK_SHIFT, VK_CONTROL, VK_LWIN, VK_RWIN)
    while time.monotonic() < deadline and any(_is_down(m) for m in mods):
        time.sleep(0.01)
    held = [m for m in mods if _is_down(m)]
    if held:  # no los soltó a tiempo: simulamos que los suelta para que no se mezclen con Ctrl+C
        send_keys([(m, True) for m in held])

    before = clipboard_sequence()
    send_keys([(VK_CONTROL, False), (VK_C, False), (VK_C, True), (VK_CONTROL, True)])
    t_end = time.monotonic() + 0.5
    while time.monotonic() < t_end and clipboard_sequence() == before:
        time.sleep(0.01)
    if clipboard_sequence() == before:
        return (old_text or "") if fallback else ""
    time.sleep(0.03)  # que la app termine de escribir
    new_text = get_clipboard_text() or ""
    if restore and old_text is not None:
        set_clipboard_text(old_text)
    return new_text


# ------------------------------------------------------------- atajos globales
WM_HOTKEY, WM_APP, WM_QUIT = 0x0312, 0x8000, 0x0012
MOD_NOREPEAT = 0x4000
ERROR_HOTKEY_ALREADY_REGISTERED = 1409


class HotkeyManager:
    """Registra atajos globales en un hilo propio con su bucle de mensajes.

    bindings: {nombre: "alt+r"}. Al dispararse llama on_trigger(nombre) en otro hilo.
    """

    def __init__(self, on_trigger: Callable[[str], None],
                 on_error: Callable[[str], None] | None = None):
        self.on_trigger = on_trigger
        self.on_error = on_error or (lambda m: None)
        self._thread: threading.Thread | None = None
        self._tid = 0
        self._pending: dict[str, str] = {}
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._names: dict[int, str] = {}

    def start(self, bindings: dict[str, str]) -> None:
        self._pending = dict(bindings)
        self._thread = threading.Thread(target=self._run, name="altr-hotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(5)

    def reload(self, bindings: dict[str, str]) -> None:
        with self._lock:
            self._pending = dict(bindings)
        user32.PostThreadMessageW(self._tid, WM_APP, 0, 0)

    def stop(self) -> None:
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
        if self._thread:
            self._thread.join(2)

    def _register_all(self) -> None:
        for hid in list(self._names):
            user32.UnregisterHotKey(None, hid)
        self._names.clear()
        with self._lock:
            bindings = dict(self._pending)
        for n, (name, text) in enumerate(bindings.items(), start=1):
            if not text.strip():
                continue
            mods, vk = parse_hotkey(text)
            if user32.RegisterHotKey(None, n, mods | MOD_NOREPEAT, vk):
                self._names[n] = name
            else:
                err = ctypes.get_last_error()
                why = ("otro programa ya usa ese atajo" if err == ERROR_HOTKEY_ALREADY_REGISTERED
                       else f"error {err}")
                self.on_error(f"No pude registrar el atajo {text} ({why}). "
                              "Cambialo en el config.toml.")

    def _run(self) -> None:
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, WM_APP, WM_APP, 0)  # crea la cola
        self._tid = int(kernel32.GetCurrentThreadId())
        try:
            self._register_all()
        finally:
            self._ready.set()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                name = self._names.get(int(msg.wParam))
                if name:
                    threading.Thread(target=self.on_trigger, args=(name,), daemon=True).start()
            elif msg.message == WM_APP:
                self._register_all()
        for hid in list(self._names):
            user32.UnregisterHotKey(None, hid)


# ------------------------------------------------------------ reproducción (MCI)
_alias_counter = itertools.count(1)


def _mci(cmd: str) -> tuple[int, str]:
    buf = ctypes.create_unicode_buffer(256)
    err = int(winmm.mciSendStringW(cmd, buf, 255, None))
    return err, buf.value


def _mci_error(err: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    winmm.mciGetErrorStringW(err, buf, 255)
    return buf.value or f"error MCI {err}"


class MciBackend:
    """Reproduce mp3/wav con la API multimedia de Windows (sin instalar nada)."""

    def play(self, path: Path, volume: int, cancel: threading.Event) -> None:
        alias = f"altr{next(_alias_counter)}"
        kind = " type mpegvideo" if str(path).lower().endswith(".mp3") else ""
        err, _ = _mci(f'open "{path}"{kind} alias {alias}')
        if err:
            raise RuntimeError(_mci_error(err))
        try:
            _mci(f"setaudio {alias} volume to {max(0, min(100, volume)) * 10}")  # si falla, sin volumen
            _, length = _mci(f"status {alias} length")
            limit = (int(length) / 1000 if length.isdigit() else 600) + 10
            err, _ = _mci(f"play {alias}")
            if err:
                raise RuntimeError(_mci_error(err))
            t_end = time.monotonic() + limit
            while time.monotonic() < t_end:
                if cancel.wait(0.03):
                    _mci(f"stop {alias}")
                    return
                err, mode = _mci(f"status {alias} mode")
                if err or mode == "stopped":
                    return
        finally:
            _mci(f"close {alias}")


# ----------------------------------------------------------- sistema / extras
_mutex_handle = None


def single_instance() -> bool:
    """True si somos la única instancia."""
    global _mutex_handle
    _mutex_handle = kernel32.CreateMutexW(None, False, "Local\\AltR-single-instance")
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


def open_path(path: Path) -> None:
    os.startfile(str(path))  # noqa: S606 - abre con el programa asociado


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "AltR"


def _launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    return f'"{pyw if pyw.exists() else exe}" -m altr'


def autostart_enabled() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_NAME)
            return True
    except FileNotFoundError:
        return False


def set_autostart(enabled: bool) -> None:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, _launch_command())
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except FileNotFoundError:
                pass
