"""La aplicación residente: atajos globales + lectura + bandeja y overlay (ui.py).

La plataforma (Windows) se inyecta como objeto con: capture_selection, get_clipboard_text,
HotkeyManager, single_instance, open_path, autostart_enabled, set_autostart. Así la lógica
(recarga de config, errores, ciclo de vida) se prueba en Linux con un doble falso.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from . import __version__
from .config import Config, ConfigError, app_dir, ensure_config, load_config, parse_config
from .player import default_backend
from .providers import make_provider
from .reader import Reader

log = logging.getLogger("altr")


class App:
    def __init__(self, config_path: Path, platform, backend=None, tray_factory=None):
        self.config_path = Path(config_path)
        self.platform = platform
        self.tray = None
        self.tray_factory = tray_factory
        self._quit = threading.Event()
        self._capture_lock = threading.Lock()
        self._pending_error: str | None = None
        self.cfg = self._load_or_default(first=True)
        self.reader = Reader(self.cfg, backend or default_backend(),
                             on_error=self.notify, on_state=self._on_state)
        self.hotkeys = None

    # ------------------------------------------------------------ config
    def _load_or_default(self, first: bool = False) -> Config:
        created = ensure_config(self.config_path)
        if created:
            log.info("config creado en %s", self.config_path)
        try:
            cfg = load_config(self.config_path)
        except ConfigError as e:
            log.error("config inválido: %s", e)
            self._pending_error = f"Config inválido: {e}"
            if first:
                return parse_config({})
            raise
        for w in cfg.warnings:
            log.warning(w)
        return cfg

    def _bindings(self) -> dict[str, str]:
        return {"read": self.cfg.general.hotkey, "stop": self.cfg.general.stop_hotkey}

    def reload(self) -> None:
        try:
            cfg = self._load_or_default()
        except ConfigError as e:
            self.notify(f"No recargué: {e} (sigue el config anterior)")
            return
        self.cfg = cfg
        self.reader.set_config(cfg)
        if self.hotkeys:
            self.hotkeys.reload(self._bindings())
        if self.tray and hasattr(self.tray, "apply_config"):
            self.tray.apply_config(cfg)
        msg = "Configuración recargada."
        if cfg.warnings:
            msg += " Avisos: " + " ".join(cfg.warnings)
        self.notify(msg, force=True)

    # --------------------------------------------------------- acciones
    def notify(self, message: str, force: bool = False) -> None:
        log.info("aviso: %s", message)
        if self.tray and (force or self.cfg.general.notifications):
            self.tray.notify(message)

    def _on_state(self, speaking: bool) -> None:
        if self.tray:
            self.tray.set_speaking(speaking)

    def on_hotkey(self, name: str) -> None:
        if name == "stop":
            self.reader.stop()
        elif name == "read":
            self.read_selection()

    def read_selection(self) -> None:
        if not self._capture_lock.acquire(blocking=False):
            return
        try:
            g = self.cfg.general
            text = self.platform.capture_selection(
                restore=g.restore_clipboard, fallback=g.clipboard_fallback,
                clipboard_only_apps=g.clipboard_only_apps)
            if not text.strip():
                self.notify("No hay texto seleccionado ni en el portapapeles.")
                return
            self.reader.speak(text)
        except Exception as e:
            log.exception("falló la lectura")
            self.notify(f"Falló la captura del texto: {e}")
        finally:
            self._capture_lock.release()

    def read_clipboard(self) -> None:
        text = self.platform.get_clipboard_text() or ""
        if not text.strip():
            self.notify("El portapapeles no tiene texto.")
            return
        self.reader.speak(text)

    def open_config(self) -> None:
        self.platform.open_path(self.config_path)

    def open_log(self) -> None:
        self.platform.open_path(app_dir() / "altr.log")

    def quit(self) -> None:
        self._quit.set()
        self.reader.stop()
        if self.tray:
            self.tray.stop()

    # ---------------------------------------------------------- ciclo de vida
    def run(self) -> int:
        if not self.platform.single_instance():
            log.info("AltR ya está corriendo; salgo.")
            return 0
        log.info("AltR %s arrancando; config: %s", __version__, self.config_path)
        self.hotkeys = self.platform.HotkeyManager(self.on_hotkey, on_error=lambda m: self.notify(m, force=True))
        if self.tray_factory:
            self.tray = self.tray_factory(self)
        self.hotkeys.start(self._bindings())
        err = self._pending_error
        if self.tray:
            threading.Timer(1.0, self._startup_notice, args=(err,)).start()
            self.tray.run()  # bloquea hasta quit()
        else:
            self._quit.wait()
        self.hotkeys.stop()
        return 0

    def _startup_notice(self, err: str | None) -> None:
        if err:
            self.notify(err + " Uso la configuración por defecto.", force=True)
        else:
            g = self.cfg.general
            self.notify(f"Listo. {g.hotkey.upper()} lee la selección"
                        + (f"; {g.stop_hotkey.upper()} corta." if g.stop_hotkey else "."), force=True)
