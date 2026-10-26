"""Ícono de bandeja con pystray + Pillow (opcionales: sin ellos AltR corre sin ícono)."""
from __future__ import annotations

import logging
from typing import Callable

from . import __version__

log = logging.getLogger("altr")


def available() -> bool:
    try:
        import PIL  # noqa: F401
        import pystray  # noqa: F401
        return True
    except Exception:
        return False


def make_icon_image(speaking: bool = False):
    """Parlante dibujado a mano (sin archivos de imagen)."""
    from PIL import Image, ImageDraw

    s = 64
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bg = (22, 163, 74, 255) if speaking else (31, 41, 55, 255)
    d.rounded_rectangle((2, 2, s - 3, s - 3), radius=14, fill=bg)
    white = (255, 255, 255, 255)
    d.polygon([(14, 25), (24, 25), (34, 16), (34, 48), (24, 39), (14, 39)], fill=white)
    d.arc((30, 22, 46, 42), -60, 60, fill=white, width=3)
    d.arc((30, 14, 56, 50), -60, 60, fill=white, width=3)
    return img


class Tray:
    def __init__(self, *, on_read_clipboard: Callable, on_stop: Callable, on_open_config: Callable,
                 on_reload: Callable, on_open_log: Callable, on_quit: Callable,
                 autostart_get: Callable[[], bool] | None = None,
                 autostart_set: Callable[[bool], None] | None = None):
        import pystray

        self._pystray = pystray
        self._autostart_get = autostart_get
        self._autostart_set = autostart_set
        item = pystray.MenuItem
        items = [
            item("Detener lectura", lambda: on_stop(), default=True),
            item("Leer el portapapeles", lambda: on_read_clipboard()),
            pystray.Menu.SEPARATOR,
            item("Abrir configuración", lambda: on_open_config()),
            item("Recargar configuración", lambda: on_reload()),
            item("Abrir registro (log)", lambda: on_open_log()),
        ]
        if autostart_get and autostart_set:
            items.append(item("Iniciar con Windows", self._toggle_autostart,
                              checked=lambda _i: self._autostart_get()))
        items += [pystray.Menu.SEPARATOR, item(f"AltR {__version__}", None, enabled=False),
                  item("Salir", lambda: on_quit())]
        self.icon = pystray.Icon("AltR", make_icon_image(False), "AltR", pystray.Menu(*items))

    def _toggle_autostart(self, _icon=None, _item=None) -> None:
        try:
            self._autostart_set(not self._autostart_get())
        except Exception:
            log.exception("no pude cambiar el inicio con Windows")

    def run(self) -> None:
        self.icon.run()  # bloquea hasta stop()

    def stop(self) -> None:
        self.icon.stop()

    def set_speaking(self, speaking: bool) -> None:
        try:
            self.icon.icon = make_icon_image(speaking)
            self.icon.title = "AltR - leyendo..." if speaking else "AltR"
        except Exception:
            log.debug("no pude actualizar el ícono", exc_info=True)

    def notify(self, message: str, title: str = "AltR") -> None:
        try:
            self.icon.notify(message, title)
        except Exception:
            log.debug("no pude mostrar la notificación", exc_info=True)
