"""Parseo de atajos tipo "ctrl+alt+r" a (modificadores, código de tecla virtual).

Los valores son los de la API de Windows (RegisterHotKey), pero el parseo no
toca ninguna API: se puede probar en cualquier sistema.
"""
from __future__ import annotations

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

_MODS = {
    "alt": MOD_ALT, "ctrl": MOD_CONTROL, "control": MOD_CONTROL,
    "shift": MOD_SHIFT, "win": MOD_WIN, "windows": MOD_WIN, "super": MOD_WIN,
}

_NAMED = {
    "space": 0x20, "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
    "backspace": 0x08, "delete": 0x2E, "del": 0x2E, "insert": 0x2D, "ins": 0x2D,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "pause": 0x13, "printscreen": 0x2C,
}
# Teclas de puntuación por su nombre (para no depender del teclado del usuario).
_NAMED.update({"comma": 0xBC, "period": 0xBE, "minus": 0xBD, "plus": 0xBB,
               "semicolon": 0xBA, "slash": 0xBF})


class HotkeyError(ValueError):
    pass


def parse_hotkey(text: str) -> tuple[int, int]:
    parts = [p.strip().lower() for p in text.split("+") if p.strip()]
    if not parts:
        raise HotkeyError("está vacío")
    *mod_names, key = parts
    mods = 0
    for m in mod_names:
        if m not in _MODS:
            raise HotkeyError(f"'{m}' no es un modificador válido (usá alt, ctrl, shift o win)")
        mods |= _MODS[m]
    if key in _MODS:
        raise HotkeyError("falta la tecla final (por ejemplo \"alt+r\")")
    if len(key) == 1 and key.isascii() and key.isalpha():
        vk = ord(key.upper())
    elif len(key) == 1 and key.isascii() and key.isdigit():
        vk = ord(key)
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    elif key in _NAMED:
        vk = _NAMED[key]
    else:
        raise HotkeyError(f"no conozco la tecla '{key}'")
    if mods == 0 and not (key.startswith("f") and key[1:].isdigit()):
        raise HotkeyError("necesita al menos un modificador (alt, ctrl, shift o win)")
    return mods, vk
