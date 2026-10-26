"""Ventana de Configuración (Qt/QML): otra vista en el mismo QApplication que el overlay.

`SettingsController` es el modelo que ve QML (contexto `ctl`): los valores del formulario, la
validación (con altr/config.py), el guardado en el config.toml PRESERVANDO sus comentarios
(tomlkit: sólo se tocan las claves que el usuario cambió) y la recarga en caliente (`on_saved`).
`SettingsWindow` es la ventana (sin marco, con el estilo del overlay: qml/settings/Settings.qml).

Se abre desde el menú de la bandeja ("Configuración…") o con `AltR --settings`. Si ya hay un AltR
residente, `--settings` le pide por un archivo que abra la ventana en SU proceso (así guarda y
recarga ahí mismo); si no, abre la ventana sola.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import tomllib
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Property, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QSurfaceFormat
from PySide6.QtQuick import QQuickView

from . import __version__, secrets, updates
from .config import ConfigError, OVERLAY_POSITIONS, ensure_config, load_config, parse_config
from .hotkeys import HotkeyError, parse_hotkey

log = logging.getLogger("altr")

QML_FILE = Path(__file__).resolve().parent / "qml" / "settings" / "Settings.qml"
SECTIONS = ("atajos", "voz", "api", "overlay", "general")

# clave plana "sección.clave" -> lo que edita el formulario (todo lo demás del config.toml no se toca)
FIELDS = (
    "general.hotkey", "general.stop_hotkey", "general.clipboard_fallback",
    "general.restore_clipboard", "general.notifications", "general.check_updates",
    "text.strip_markdown", "text.read_urls",
    "overlay.enabled", "overlay.position", "overlay.monitor", "overlay.opacity", "overlay.font_size",
    "tts.provider", "tts.speed", "tts.volume",
    "edge.voice", "openai.base_url", "openai.model", "openai.voice", "openai.api_key_env",
    "openai.instructions", "openai.response_format", "command.voice",
)
AUTOSTART = "app.autostart"   # no vive en el config.toml: es la clave Run del registro

_FLOATS = {"overlay.opacity": 3, "tts.speed": 2}
_INTS = {"overlay.font_size", "tts.volume"}

# teclas de Qt (Qt.Key_*) -> nombre que entiende hotkeys.parse_hotkey
_QT_NAMED = {
    0x20: "space", 0x01000004: "enter", 0x01000005: "enter", 0x01000001: "tab",
    0x01000003: "backspace", 0x01000007: "delete", 0x01000006: "insert",
    0x01000010: "home", 0x01000011: "end", 0x01000016: "pageup", 0x01000017: "pagedown",
    0x01000012: "left", 0x01000013: "up", 0x01000014: "right", 0x01000015: "down",
    0x01000008: "pause", 0x01000009: "printscreen",
    0x2C: "comma", 0x2E: "period", 0x2D: "minus", 0x2B: "plus", 0x3B: "semicolon", 0x2F: "slash",
}
_QT_MODIFIER_KEYS = {0x01000020, 0x01000021, 0x01000022, 0x01000023, 0x01001103, 0x01000024,
                     0x01000025, 0x01000026, 0x01000053, 0x01000054}
_MOD_CTRL, _MOD_SHIFT, _MOD_ALT, _MOD_META = 0x04000000, 0x02000000, 0x08000000, 0x10000000

SAMPLES = {
    "es": "Hola, así suena esta voz.", "en": "Hello, this is how this voice sounds.",
    "pt": "Olá, é assim que esta voz soa.", "fr": "Bonjour, voici comment sonne cette voix.",
    "de": "Hallo, so klingt diese Stimme.", "it": "Ciao, ecco come suona questa voce.",
}

# lista de ejemplo para la captura de pantalla y los tests (sin internet)
SAMPLE_VOICES = [
    {"name": n, "gender": g, "locale": n.rsplit("-", 1)[0]} for n, g in (
        ("es-AR-ElenaNeural", "Female"), ("es-AR-TomasNeural", "Male"),
        ("es-CO-GonzaloNeural", "Male"), ("es-CO-SalomeNeural", "Female"),
        ("es-ES-AlvaroNeural", "Male"), ("es-ES-ElviraNeural", "Female"),
        ("es-MX-DaliaNeural", "Female"), ("es-MX-JorgeNeural", "Male"),
        ("es-US-PalomaNeural", "Female"), ("en-US-AvaMultilingualNeural", "Female"),
        ("en-US-AndrewNeural", "Male"), ("en-GB-SoniaNeural", "Female"),
        ("pt-BR-FranciscaNeural", "Female"), ("fr-FR-DeniseNeural", "Female"),
        ("de-DE-KatjaNeural", "Female"), ("it-IT-ElsaNeural", "Female"))
]


def request_file() -> Path:
    from .config import app_dir
    return app_dir() / "settings.request"


def request_open(section: str | None = None) -> None:
    """Le pide al AltR residente que abra la ventana (lo lee UiHost cada segundo)."""
    path = request_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((section or "") + "\n", encoding="utf-8")


def take_request() -> str | None:
    """Si hay un pedido de abrir la ventana lo consume y devuelve la sección ("" = la de siempre)."""
    path = request_file()
    try:
        text = path.read_text(encoding="utf-8").strip()
        path.unlink()
    except OSError:
        return None
    return text if text in SECTIONS else ""


def qt_key_name(key: int) -> str | None:
    """Nombre de hotkeys.py para una tecla de Qt, o None si no sirve para un atajo."""
    if 0x41 <= key <= 0x5A:                       # A-Z
        return chr(key).lower()
    if 0x30 <= key <= 0x39:                       # 0-9
        return chr(key)
    if 0x01000030 <= key <= 0x01000047:           # F1..F24
        return f"f{key - 0x01000030 + 1}"
    return _QT_NAMED.get(key)


def _norm_hotkey(text: str) -> str:
    return "+".join(p.strip().lower() for p in text.split("+") if p.strip())


def _error_key(msg: str) -> str:
    m = re.match(r"\[(\w+)\] (\w+)", msg)
    return f"{m.group(1)}.{m.group(2)}" if m else ""


class SettingsController(QObject):
    valuesChanged = Signal()
    dirtyChanged = Signal()
    errorChanged = Signal()
    statusChanged = Signal()
    voicesChanged = Signal()
    testChanged = Signal()
    keyChanged = Signal()
    updateChanged = Signal()
    _voicesReady = Signal(object, str)
    _testDone = Signal(str)
    _updateResult = Signal(object, str)
    _installResult = Signal(str)

    def __init__(self, config_path: Path, *, on_saved: Callable[[], None] | None = None,
                 platform=None, stop_reading: Callable[[], None] | None = None,
                 voices_loader: Callable[[], list[dict]] | None = None, demo: bool = False,
                 backend_factory: Callable[[], object] | None = None,
                 on_capture: Callable[[bool], None] | None = None,
                 update_checker: Callable[[], dict] | None = None,
                 update_installer: Callable[[], None] | None = None):
        super().__init__()
        self.config_path = Path(config_path)
        self.window = None                 # lo pone SettingsWindow (mover, minimizar, cerrar)
        self._on_saved = on_saved
        self._platform = platform
        self._stop_reading = stop_reading
        self._demo = demo
        self._voices_loader = voices_loader
        self._backend_factory = backend_factory
        self._on_capture = on_capture
        self._capturing = False
        self._update_checker = update_checker
        self._update_installer = update_installer
        self._update_state = "idle"      # idle | checking | none | available | installing | error
        self._update_msg = ""
        self._update_latest = ""
        self._update_url = ""
        self._values: dict = {}
        self._base: dict = {}
        self._error = ""
        self._error_key = ""
        self._status = ""
        self._load_error = ""
        self._voices_state = "idle"
        self._voices: list[dict] = []
        self._voices_err = ""
        self._testing = False
        self._test_msg = ""
        self._test_reader = None
        self._key_stored = False
        self._voicesReady.connect(self._on_voices)
        self._testDone.connect(self._on_test_done)
        self._updateResult.connect(self._on_update_result)
        self._installResult.connect(self._on_install_result)
        self.reload_from_disk()
        known = "" if demo else updates.known_newer()
        if known:   # el chequeo silencioso de al arrancar ya la vio
            self._update_state, self._update_latest = "available", known
            self._update_url = updates.RELEASES_URL

    # ------------------------------------------------------------ lectura del config
    def _read_raw(self) -> dict:
        try:
            with open(self.config_path, "rb") as f:
                return tomllib.load(f)
        except (FileNotFoundError, tomllib.TOMLDecodeError):
            return {}

    def reload_from_disk(self) -> None:
        """Rearma el formulario con lo que hay en el config.toml (descarta lo no guardado)."""
        ensure_config(self.config_path)
        self._load_error = ""
        try:
            cfg = load_config(self.config_path)
        except ConfigError as e:
            self._load_error = str(e)
            cfg = parse_config({})
        vals = {k: cfg.data[k.split(".")[0]][k.split(".", 1)[1]] for k in FIELDS}
        vals[AUTOSTART] = self._autostart_now()
        self._base = dict(vals)
        self._values = dict(vals)
        self._key_stored = bool(secrets.get_api_key())
        self._error = self._error_key = ""
        self._status = ""
        for sig in (self.valuesChanged, self.dirtyChanged, self.errorChanged, self.statusChanged,
                    self.keyChanged):
            sig.emit()

    def _autostart_now(self):
        get = getattr(self._platform, "autostart_enabled", None)
        if not get:
            return None
        try:
            return bool(get())
        except Exception:
            return None

    # ------------------------------------------------------------ propiedades para QML
    def _get_values(self) -> dict:
        return dict(self._values)

    values = Property("QVariantMap", _get_values, notify=valuesChanged)

    def _get_dirty(self) -> bool:
        return any(self._values.get(k) != self._base.get(k) for k in self._values)

    dirty = Property(bool, _get_dirty, notify=dirtyChanged)
    error = Property(str, lambda self: self._error or self._load_error, notify=errorChanged)
    errorKey = Property(str, lambda self: self._error_key, notify=errorChanged)
    status = Property(str, lambda self: self._status, notify=statusChanged)
    configPath = Property(str, lambda self: str(self.config_path), constant=True)
    version = Property(str, lambda self: __version__, constant=True)
    canAutostart = Property(bool, lambda self: self._base.get(AUTOSTART) is not None, notify=valuesChanged)
    voicesState = Property(str, lambda self: self._voices_state, notify=voicesChanged)
    voices = Property("QVariantList", lambda self: list(self._voices), notify=voicesChanged)
    voicesError = Property(str, lambda self: self._voices_err, notify=voicesChanged)
    testing = Property(bool, lambda self: self._testing, notify=testChanged)
    testMessage = Property(str, lambda self: self._test_msg, notify=testChanged)
    keyStored = Property(bool, lambda self: self._key_stored, notify=keyChanged)
    keyAvailable = Property(bool, lambda self: secrets.available(), constant=True)
    updateState = Property(str, lambda self: self._update_state, notify=updateChanged)
    updateMessage = Property(str, lambda self: self._update_msg, notify=updateChanged)
    latestVersion = Property(str, lambda self: self._update_latest, notify=updateChanged)
    releaseUrl = Property(str, lambda self: self._update_url or updates.RELEASES_URL, notify=updateChanged)
    canUpdate = Property(bool, lambda self: self._update_installer is not None or os.name == "nt",
                         constant=True)
    positions = Property("QVariantList", lambda self: list(OVERLAY_POSITIONS), constant=True)

    @Property("QVariantList", notify=valuesChanged)
    def monitorOptions(self):
        n = max(1, len(QGuiApplication.screens()))
        cur = str(self._values.get("overlay.monitor", "active"))
        opts = [{"v": "active", "t": "El del mouse"}, {"v": "primary", "t": "El principal"}]
        nums = list(range(1, n + 1))
        if cur.isdigit() and int(cur) not in nums:
            nums.append(int(cur))
        return opts + [{"v": str(i), "t": f"Monitor {i}"} for i in nums]

    # ------------------------------------------------------------ edición
    @Slot(str, "QVariant")
    def set(self, key: str, value) -> None:
        if key not in self._values:
            return
        if key in _FLOATS:
            value = round(float(value), _FLOATS[key])
        elif key in _INTS:
            value = int(round(float(value)))
        elif isinstance(self._base.get(key), bool):
            value = bool(value)
        elif isinstance(self._base.get(key), str):
            value = str(value)
        if self._values[key] == value:
            return
        self._values[key] = value
        self._status = ""
        self._validate()
        self.valuesChanged.emit()
        self.dirtyChanged.emit()
        self.statusChanged.emit()

    @Slot(str, result="QVariant")
    def get(self, key: str):
        return self._values.get(key)

    def _candidate_raw(self) -> dict:
        raw = self._read_raw()
        for k in FIELDS:
            sec, name = k.split(".", 1)
            raw.setdefault(sec, {})
            if isinstance(raw[sec], dict):
                raw[sec][name] = self._values[k]
        return raw

    def _validate(self):
        """Valida el formulario completo con config.py. Devuelve la Config o None."""
        try:
            cfg = parse_config(self._candidate_raw(), self.config_path)
            err = key = ""
        except ConfigError as e:
            cfg, err = None, str(e)
            key = _error_key(err)
        if (err, key) != (self._error, self._error_key):
            self._error, self._error_key = err, key
            self.errorChanged.emit()
        return cfg

    @Slot()
    def revert(self) -> None:
        self.reload_from_disk()

    # ------------------------------------------------------------ guardado
    @Slot(result=bool)
    def save(self) -> bool:
        cfg = self._validate()
        if cfg is None:
            return False
        changed = {k: v for k, v in self._values.items()
                   if k != AUTOSTART and v != self._base.get(k)}
        auto_changed = self._values.get(AUTOSTART) != self._base.get(AUTOSTART)
        if changed:
            try:
                self._write(changed)
            except Exception as e:
                log.exception("no pude guardar el config")
                self._set_error(f"No pude guardar el config.toml: {e}")
                return False
        if auto_changed:
            try:
                self._platform.set_autostart(bool(self._values[AUTOSTART]))
            except Exception as e:
                log.exception("no pude cambiar el inicio con Windows")
                self._set_error(f"No pude cambiar el inicio con Windows: {e}")
                return False
        if self._on_saved and (changed or auto_changed):
            try:
                self._on_saved()
            except Exception:
                log.exception("falló la recarga tras guardar")
        self.reload_from_disk()
        self._status = "Guardado y aplicado."
        self.statusChanged.emit()
        return True

    def _set_error(self, msg: str) -> None:
        self._error, self._error_key = msg, ""
        self.errorChanged.emit()

    def _write(self, changed: dict) -> None:
        import tomlkit

        text = self.config_path.read_text(encoding="utf-8")
        try:
            doc = tomlkit.parse(text)
        except Exception as e:
            raise RuntimeError("el config.toml tiene un error de sintaxis; arreglalo con "
                               f"'Abrir config.toml' ({e})") from None
        for key, value in changed.items():
            sec, name = key.split(".", 1)
            if sec not in doc:
                doc.add(tomlkit.nl())
                doc.add(sec, tomlkit.table())
            doc[sec][name] = value
        out = tomlkit.dumps(doc)
        tomllib.loads(out)   # por las dudas: lo que escribo tiene que volver a leerse
        tmp = self.config_path.with_name(self.config_path.name + ".tmp")
        tmp.write_text(out, encoding="utf-8", newline="")
        try:
            os.replace(tmp, self.config_path)
        except OSError:   # otro programa lo tiene abierto sin permitir reemplazo: escribir encima
            self.config_path.write_text(out, encoding="utf-8", newline="")
            tmp.unlink(missing_ok=True)

    # ------------------------------------------------------------ atajos
    @Slot(int, int, result="QVariantMap")
    def captureKey(self, key: int, mods: int) -> dict:
        """Una tecla apretada mientras se captura. {done, text, error}: `text` es el atajo (o los
        modificadores que van hasta ahora, si todavía no hay tecla final)."""
        parts = [n for bit, n in ((_MOD_CTRL, "ctrl"), (_MOD_ALT, "alt"), (_MOD_SHIFT, "shift"),
                                  (_MOD_META, "win")) if mods & bit]
        if key in _QT_MODIFIER_KEYS:
            return {"done": False, "text": "+".join(parts), "error": ""}
        name = qt_key_name(key)
        if name is None:
            return {"done": False, "text": "+".join(parts),
                    "error": "Esa tecla no se puede usar en un atajo."}
        text = "+".join(parts + [name])
        try:
            parse_hotkey(text)
        except HotkeyError as e:
            msg = ("Agregá Ctrl, Alt, Shift o Win: una tecla sola se pisaría con lo que escribís."
                   if "modificador" in str(e) else f"Ese atajo no sirve: {e}.")
            return {"done": False, "text": text, "error": msg}
        return {"done": True, "text": text, "error": ""}

    @Slot(bool)
    def setCapturing(self, on: bool) -> None:
        """Mientras se captura un atajo los atajos de AltR se sueltan: si no, apretar el actual
        dispararía una lectura en vez de llegar al campo."""
        if on == self._capturing:
            return
        self._capturing = on
        if self._on_capture:
            try:
                self._on_capture(on)
            except Exception:
                log.exception("no pude (re)activar los atajos")

    @Slot(str, str, result="QVariantMap")
    def checkHotkey(self, which: str, text: str) -> dict:
        """¿Está libre este atajo? which = "read" o "stop" (el campo que se está editando)."""
        text = _norm_hotkey(text)
        if not text:
            return {"state": "none", "msg": ""}
        other_key = "general.stop_hotkey" if which == "read" else "general.hotkey"
        if _norm_hotkey(str(self._values.get(other_key, ""))) == text:
            what = "cortar" if which == "read" else "leer"
            return {"state": "dup", "msg": f"Ya lo usás para {what}. Elegí otro."}
        mine = {_norm_hotkey(str(self._base.get(k, ""))) for k in ("general.hotkey", "general.stop_hotkey")}
        if text in mine:
            return {"state": "own", "msg": "Es el atajo que ya usa AltR."}
        probe = getattr(self._platform, "hotkey_available", None)
        free = None
        if probe:
            try:
                free = probe(text)
            except Exception:
                free = None
        if free is True:
            return {"state": "free", "msg": "Libre."}
        if free is False:
            hint = (" Es el de la NVIDIA App: apagalo en sus ajustes o elegí otro."
                    if text == "alt+r" else " Probá con otro.")
            return {"state": "taken", "msg": "Otro programa ya usa este atajo." + hint}
        return {"state": "unknown", "msg": ""}

    # ------------------------------------------------------------ voces
    @Slot()
    def loadVoices(self) -> None:
        if self._voices_state in ("loading", "ready"):
            return
        self._voices_state, self._voices_err = "loading", ""
        self.voicesChanged.emit()
        if self._demo:
            self._voices_state, self._voices = "ready", list(SAMPLE_VOICES)
            self.voicesChanged.emit()
            return

        def work():
            try:
                loader = self._voices_loader
                if loader is None:
                    from .providers import list_edge_voice_infos as loader
                voices = loader()
                self._voicesReady.emit(voices, "")
            except Exception as e:
                self._voicesReady.emit([], f"{type(e).__name__}: {e}"[:160])

        threading.Thread(target=work, name="altr-voices", daemon=True).start()

    @Slot()
    def retryVoices(self) -> None:
        self._voices_state = "idle"
        self.loadVoices()

    def _on_voices(self, voices, err: str) -> None:
        if err or not voices:
            self._voices_state = "error"
            self._voices_err = ("No pude traer la lista de voces (¿hay internet?). "
                                "Podés escribir el nombre de la voz a mano.")
            log.warning("lista de voces: %s", err or "vacía")
        else:
            self._voices_state, self._voices = "ready", list(voices)
        self.voicesChanged.emit()

    # ------------------------------------------------------------ probar voz
    @Slot()
    def testVoice(self) -> None:
        if self._testing:
            self.stopTest()
            return
        cfg = self._validate()
        if cfg is None:
            self._set_test(False, "Corregí el error de abajo antes de probar.")
            return
        from .player import default_backend
        from .reader import Reader

        if self._stop_reading:
            self._stop_reading()
        lang = (cfg.edge.voice if cfg.tts.provider == "edge" else "es").split("-")[0].lower()
        sample = SAMPLES.get(lang, SAMPLES["es"])
        done = threading.Event()
        errors: list[str] = []
        backend = self._backend_factory() if self._backend_factory else default_backend()

        def on_state(speaking: bool) -> None:
            if not speaking:
                done.set()
                self._testDone.emit(errors[0] if errors else "")

        reader = Reader(cfg, backend, on_error=errors.append, on_state=on_state)
        self._test_reader = reader
        self._set_test(True, "Generando la voz…")
        if not reader.speak(sample):
            self._set_test(False, errors[0] if errors else "No hay nada para decir.")

    def _set_test(self, testing: bool, msg: str) -> None:
        self._testing, self._test_msg = testing, msg
        self.testChanged.emit()

    @Slot()
    def stopTest(self) -> None:
        if self._test_reader is not None:
            self._test_reader.stop()
        self._set_test(False, "")

    def _on_test_done(self, err: str) -> None:
        self._test_reader = None
        self._set_test(False, err)

    # ------------------------------------------------------------ clave de la API
    @Slot(str)
    def saveApiKey(self, key: str) -> None:
        if not key.strip():
            return
        try:
            secrets.set_api_key(key)
        except secrets.SecretsError as e:
            self._set_error(str(e))
            return
        self._key_stored = True
        self._status = "Clave guardada en el Administrador de credenciales."
        self.keyChanged.emit()
        self.statusChanged.emit()

    @Slot()
    def removeApiKey(self) -> None:
        try:
            secrets.delete_api_key()
        except secrets.SecretsError as e:
            self._set_error(str(e))
            return
        self._key_stored = False
        self._status = "Clave borrada."
        self.keyChanged.emit()
        self.statusChanged.emit()

    # ------------------------------------------------------------ actualizaciones
    def _set_update(self, state: str, msg: str = "") -> None:
        self._update_state, self._update_msg = state, msg
        self.updateChanged.emit()

    @Slot()
    def checkUpdates(self) -> None:
        if self._update_state in ("checking", "installing"):
            return
        self._set_update("checking", "Buscando…")
        checker = self._update_checker or updates.check_latest

        def work():
            try:
                self._updateResult.emit(checker(), "")
            except updates.UpdateError as e:
                self._updateResult.emit(None, str(e))
            except Exception as e:
                log.exception("falló la búsqueda de actualizaciones")
                self._updateResult.emit(None, f"No pude buscar actualizaciones: {e}")

        threading.Thread(target=work, name="altr-updates", daemon=True).start()

    def _on_update_result(self, info, err: str) -> None:
        if info is None:
            self._set_update("error", err)
            return
        self._update_latest = info["version"]
        self._update_url = info.get("url", "")
        if not self._demo:
            updates.record_check(info["version"])
        if info["newer"]:
            self._set_update("available", "")
        else:
            self._set_update("none", "Tenés la última versión.")

    @Slot()
    def installUpdate(self) -> None:
        if self._update_state not in ("available", "error", "none"):
            return
        self._set_update("installing", "Bajando el instalador…")
        installer = self._update_installer or updates.update_now

        def work():
            try:
                installer()
                self._installResult.emit("")
            except updates.UpdateError as e:
                self._installResult.emit(str(e))
            except Exception as e:
                log.exception("falló la actualización")
                self._installResult.emit(f"No pude actualizar: {e}")

        threading.Thread(target=work, name="altr-update-install", daemon=True).start()

    def _on_install_result(self, err: str) -> None:
        if err:
            self._set_update("error", err)
        else:
            self._set_update("installing", "Se abrió el instalador. AltR se cierra y vuelve a abrir solo.")

    @Slot()
    def openReleases(self) -> None:
        QDesktopServices.openUrl(QUrl(self.releaseUrl))

    # ------------------------------------------------------------ ventana
    @Slot()
    def openConfig(self) -> None:
        opener = getattr(self._platform, "open_path", None)
        if opener:
            opener(self.config_path)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.config_path)))

    @Slot()
    def startMove(self) -> None:
        if self.window is not None:
            self.window.startSystemMove()

    @Slot()
    def minimize(self) -> None:
        if self.window is not None:
            self.window.showMinimized()

    @Slot()
    def closeWindow(self) -> None:
        self.stopTest()
        self.setCapturing(False)
        if self.window is not None:
            self.window.hide()


class SettingsWindow:
    """La ventana. Sin marco y con fondo transparente: el vidrio, el contorno y la sombra los
    dibuja Settings.qml (mismo lenguaje visual que el overlay)."""

    def __init__(self, config_path: Path, **kw):
        self.ctl = SettingsController(config_path, **kw)
        self.error = ""
        view = QQuickView()
        view.setFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        fmt = QSurfaceFormat()
        fmt.setAlphaBufferSize(8)
        view.setFormat(fmt)
        view.setColor(QColor(0, 0, 0, 0))
        view.setResizeMode(QQuickView.ResizeMode.SizeViewToRootObject)
        view.setTitle("AltR - Configuración")
        view.rootContext().setContextProperty("ctl", self.ctl)
        view.setSource(QUrl.fromLocalFile(str(QML_FILE)))
        self.view, self.root = view, view.rootObject()
        if view.status() != QQuickView.Status.Ready or self.root is None:
            self.error = "; ".join(e.toString() for e in view.errors()) or "no cargó Settings.qml"
            log.error("la ventana de configuración no cargó: %s", self.error)
            self.root = None
        self.ctl.window = view

    @property
    def created(self) -> bool:
        return self.root is not None

    def select(self, section: str) -> None:
        if self.root is not None and section in SECTIONS:
            self.root.setProperty("seccion", section)

    def show(self, section: str | None = None) -> None:
        if self.root is None:
            return
        if section:
            self.select(section)
        if not self.view.isVisible():
            scr = QGuiApplication.screenAt(self.view.position()) or QGuiApplication.primaryScreen()
            geo = scr.availableGeometry()
            w, h = int(self.root.property("width")), int(self.root.property("height"))
            self.view.setScreen(scr)
            self.view.setPosition(geo.left() + (geo.width() - w) // 2,
                                  geo.top() + max(0, (geo.height() - h) // 2))
        self.view.show()
        self.view.raise_()
        self.view.requestActivate()
        self.ctl.loadVoices()

    def grab(self):
        return self.view.grabWindow()


def run_settings(config_path: Path, *, screenshot: str | None = None, section: str | None = None,
                 say: Callable[[str], None] = print, platform=None) -> int:
    """`AltR --settings`. Con --screenshot: carga la vista, comprueba que el formulario refleja el
    config, la guarda en un PNG y sale (0 = bien), para el CI. Sin eso abre la ventana."""
    import time

    from .ui import ensure_qapp

    qapp = ensure_qapp()
    check = screenshot is not None
    win = SettingsWindow(config_path, platform=platform, demo=check)
    if not win.created:
        say(f"La ventana de configuración no cargó: {win.error}")
        return 1
    if not check:
        win.view.visibleChanged.connect(lambda vis: None if vis else qapp.quit())
        win.show(section)
        qapp.exec()
        return 0

    problems: list[str] = []

    def ok(label: str, cond: bool) -> None:
        say(("ok   " if cond else "FALLA ") + label)
        if not cond:
            problems.append(label)

    def pump(secs: float) -> None:
        end = time.monotonic() + secs
        while time.monotonic() < end:
            qapp.processEvents()
            time.sleep(0.01)

    win.select(section or SECTIONS[0])
    win.view.show()
    win.ctl.loadVoices()
    pump(0.6)
    cfg = load_config(config_path)
    ok("el formulario muestra el atajo del config",
       win.ctl.get("general.hotkey") == cfg.general.hotkey)
    ok("la ventana se dibuja", bool(win.root.property("ready")))
    img = win.grab()
    solid = 0
    if img is not None and not img.isNull():
        step = max(1, img.width() // 64)
        solid = sum(1 for x in range(0, img.width(), step) for y in range(0, img.height(), step)
                    if img.pixelColor(x, y).alpha() > 40)
        img.save(screenshot)
        say(f"captura guardada en {screenshot}")
    ok("la captura tiene píxeles", solid > 20)
    win.view.hide()
    if problems:
        say("Configuración con fallas: " + "; ".join(problems))
        return 1
    say("Configuración OK")
    return 0
