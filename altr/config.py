"""Carga y validación del config.toml (independiente de la plataforma).

Los valores por defecto salen del propio config.default.toml: ese archivo es la
única fuente de verdad (y también la plantilla comentada que se le da al usuario).
"""
from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path

from .hotkeys import HotkeyError, parse_hotkey

APP_DIR_NAME = "AltR"
PROVIDERS = ("edge", "openai", "command")


class ConfigError(ValueError):
    """Config inválido; el mensaje está pensado para mostrárselo al usuario."""


def _resource_dir() -> Path:
    # Congelado con PyInstaller los datos viven en sys._MEIPASS/altr.
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) / "altr" if base else Path(__file__).resolve().parent


DEFAULT_CONFIG_PATH = _resource_dir() / "config.default.toml"


def app_dir() -> Path:
    """Carpeta de datos del usuario (config y log)."""
    override = os.environ.get("ALTR_HOME")
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_DIR_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_DIR_NAME.lower()


def default_config_path() -> Path:
    return app_dir() / "config.toml"


def ensure_config(path: Path) -> bool:
    """Crea el config comentado si no existe. Devuelve True si lo creó."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(DEFAULT_CONFIG_PATH.read_bytes())
    return True


class Section:
    """Acceso por atributo a una sección del config."""

    def __init__(self, name: str, data: dict):
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_data", data)

    def __getattr__(self, key):
        try:
            return self._data[key]
        except KeyError:
            raise AttributeError(f"[{self._name}] no tiene '{key}'") from None

    def __setattr__(self, key, value):
        raise AttributeError("Config es de sólo lectura")

    def as_dict(self) -> dict:
        return dict(self._data)

    def __repr__(self):
        return f"Section({self._name}, {self._data!r})"


class Config:
    def __init__(self, data: dict, warnings: list[str], path: Path | None = None):
        self.data = data
        self.warnings = warnings
        self.path = path
        self.general = Section("general", data["general"])
        self.text = Section("text", data["text"])
        self.tts = Section("tts", data["tts"])
        self.edge = Section("edge", data["edge"])
        self.openai = Section("openai", data["openai"])
        self.command = Section("command", data["command"])
        self.lexicon: dict[str, str] = data["lexicon"]


def _load_defaults() -> dict:
    with open(DEFAULT_CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


def _type_name(v) -> str:
    return {bool: "true/false", int: "un número entero", float: "un número",
            str: "un texto entre comillas", list: "una lista"}.get(type(v), type(v).__name__)


def _coerce(section: str, key: str, value, default):
    """Chequea el tipo contra el valor por defecto; int acepta float y al revés."""
    if isinstance(default, bool):
        ok = isinstance(value, bool)
    elif isinstance(default, (int, float)):
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        if ok and isinstance(default, float):
            value = float(value)
    elif isinstance(default, str):
        ok = isinstance(value, str)
    elif isinstance(default, list):
        ok = isinstance(value, list) and all(isinstance(x, str) for x in value)
    else:
        ok = True
    if not ok:
        raise ConfigError(f"[{section}] {key}: tiene que ser {_type_name(default)}, "
                          f"y encontré {value!r}.")
    return value


def parse_config(raw: dict, path: Path | None = None) -> Config:
    defaults = _load_defaults()
    warnings: list[str] = []
    data: dict = {}
    for section, dsec in defaults.items():
        user = raw.get(section, {})
        if not isinstance(user, dict):
            raise ConfigError(f"[{section}] tiene que ser una sección, no un valor suelto.")
        if section == "lexicon":
            for k, v in user.items():
                if not isinstance(v, str):
                    raise ConfigError(f"[lexicon] {k}: el reemplazo tiene que ser un texto entre comillas.")
            data[section] = {str(k).lower(): v for k, v in user.items()}
            continue
        merged = dict(dsec)
        for k, v in user.items():
            if k not in dsec:
                warnings.append(f"[{section}] '{k}' no existe; se ignora.")
                continue
            merged[k] = _coerce(section, k, v, dsec[k])
        data[section] = merged
    for section in raw:
        if section not in defaults:
            warnings.append(f"Sección [{section}] desconocida; se ignora.")

    g, t = data["general"], data["tts"]
    try:
        parse_hotkey(g["hotkey"])
    except HotkeyError as e:
        raise ConfigError(f"[general] hotkey: {e}") from None
    if g["stop_hotkey"].strip():
        try:
            parse_hotkey(g["stop_hotkey"])
        except HotkeyError as e:
            raise ConfigError(f"[general] stop_hotkey: {e}") from None
        if g["stop_hotkey"].strip().lower() == g["hotkey"].strip().lower():
            raise ConfigError("[general] hotkey y stop_hotkey no pueden ser el mismo atajo.")
    if t["provider"] not in PROVIDERS:
        raise ConfigError(f"[tts] provider: '{t['provider']}' no existe. Opciones: "
                          + ", ".join(PROVIDERS) + ".")
    if not 0.25 <= t["speed"] <= 4.0:
        raise ConfigError("[tts] speed: tiene que estar entre 0.25 y 4.0.")
    if not 0 <= t["volume"] <= 100:
        raise ConfigError("[tts] volume: tiene que estar entre 0 y 100.")
    if data["text"]["max_chars"] < 1:
        raise ConfigError("[text] max_chars: tiene que ser al menos 1.")
    if t["provider"] == "openai":
        if data["openai"]["response_format"] not in ("mp3", "wav"):
            raise ConfigError('[openai] response_format: usá "mp3" o "wav".')
    if t["provider"] == "command":
        c = data["command"]
        if not c["args"]:
            raise ConfigError("[command] args está vacío: poné el programa a ejecutar "
                              "(hay un ejemplo con Piper en el config).")
        if c["output_ext"] not in ("wav", "mp3"):
            raise ConfigError('[command] output_ext: usá "wav" o "mp3".')
    return Config(data, warnings, path)


def load_config(path: Path | None = None) -> Config:
    path = Path(path) if path else default_config_path()
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError:
        raise ConfigError(f"No encuentro el config: {path}") from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"El config tiene un error de sintaxis ({path.name}): {e}") from None
    return parse_config(raw, path)
