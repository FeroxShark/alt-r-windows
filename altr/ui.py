"""Interfaz de AltR con Qt (PySide6): ícono de bandeja y overlay de reproducción.

Todo corre en UN QApplication, en el hilo principal. Los atajos globales viven en su propio hilo
(win.HotkeyManager) y la lectura en los suyos: lo que viene de otro hilo entra por `_Dispatcher`
(una señal de Qt, que encola la llamada en el hilo de la interfaz).

El overlay (`OverlayController`) es una ventana QQuickView con `qml/Overlay.qml`: sin marco,
siempre arriba, sin tomar el foco, transparente a los clics salvo la cápsula (máscara). Cada
100 ms pide `reader.snapshot()` y le pasa a QML sólo lo que cambió. La ventana de configuración
que viene después será otra vista QML en este mismo QApplication.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import (QColor, QCursor, QGuiApplication, QIcon, QPainter, QPen, QPixmap,
                           QPolygonF, QRegion, QSurfaceFormat)
from PySide6.QtQuick import QQuickView, QQuickWindow, QSGRendererInterface
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import __version__

log = logging.getLogger("altr")

QML_DIR = Path(__file__).resolve().parent / "qml"
HUECO = 16          # aire entre el borde de la pantalla y la cápsula (igual que Linux)
ERROR_SECS = 8.0    # cuánto se queda el error en pantalla si nadie lo cierra


_qapp: QApplication | None = None   # referencia: si Python lo suelta, Qt destruye el QApplication


def ensure_qapp() -> QApplication:
    """El QApplication del proceso (lo crea la primera vez). Render por software: el overlay es
    chico, así no se depende de la placa de video ni de sus drivers."""
    global _qapp
    app = QApplication.instance()
    if app is None:
        QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Software)
        app = QApplication(["AltR"])
        app.setApplicationName("AltR")
        app.setQuitOnLastWindowClosed(False)
    _qapp = app
    return app


class _Dispatcher(QObject):
    """Ejecuta una función en el hilo de la interfaz, llamada desde cualquier hilo (siempre
    encolada, también si ya se está en ese hilo: así `quit` antes de `exec` no se pierde)."""
    call = Signal(object)

    def __init__(self):
        super().__init__()
        self.call.connect(self._run, Qt.ConnectionType.QueuedConnection)

    @Slot(object)
    def _run(self, fn) -> None:
        try:
            fn()
        except Exception:
            log.exception("falló una llamada a la interfaz")

    def post(self, fn: Callable[[], None]) -> None:
        self.call.emit(fn)


class _Bridge(QObject):
    """Lo que QML puede pedirle a Python (contexto `bridge`)."""

    def __init__(self, ctl: "OverlayController"):
        super().__init__()
        self._ctl = ctl

    @Slot()
    def stop(self) -> None:
        self._ctl.close_clicked()

    @Slot()
    def togglePause(self) -> None:
        self._ctl.reader.toggle_pause()

    @Slot(float)
    def seek(self, t: float) -> None:
        self._ctl.reader.seek(t)

    @Slot(int, int, int, int)
    def setMask(self, x: int, y: int, w: int, h: int) -> None:
        self._ctl.set_mask(x, y, w, h)


class OverlayController:
    """La ventana del overlay y su puente con el lector."""

    def __init__(self, reader, overlay_cfg):
        self.reader = reader
        self.cfg = overlay_cfg
        self.view: QQuickView | None = None
        self.root = None
        self.error = ""             # por qué no se pudo crear (QML roto, etc.)
        self.shown_count = 0        # cuántas veces apareció
        self._sent: dict = {}
        self._sid: str | None = None
        self._dismissed: str | None = None   # lectura con error que el usuario cerró
        self._err_since: float | None = None
        self._styled = False
        self.bridge = _Bridge(self)
        self.timer = QTimer()
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._tick)
        self.apply_config(overlay_cfg)

    # ---------------------------------------------------------------- creación
    @property
    def created(self) -> bool:
        return self.root is not None

    def _create(self) -> None:
        view = QQuickView()
        view.setFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                      | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        fmt = QSurfaceFormat()
        fmt.setAlphaBufferSize(8)
        view.setFormat(fmt)
        view.setColor(QColor(0, 0, 0, 0))
        view.setResizeMode(QQuickView.ResizeMode.SizeViewToRootObject)
        view.setTitle("AltR overlay")
        view.rootContext().setContextProperty("bridge", self.bridge)
        view.setSource(QUrl.fromLocalFile(str(QML_DIR / "Overlay.qml")))
        if view.status() != QQuickView.Status.Ready or view.rootObject() is None:
            self.error = "; ".join(e.toString() for e in view.errors()) or "no cargó Overlay.qml"
            log.error("el overlay no cargó: %s", self.error)
            view.deleteLater()
            return
        self.view, self.root = view, view.rootObject()

    # ------------------------------------------------------------------ config
    def apply_config(self, overlay_cfg) -> None:
        self.cfg = overlay_cfg
        if not overlay_cfg.enabled:
            self.timer.stop()
            self._hide()
            return
        if self.view is None and not self.error:
            self._create()
        if self.root is None:
            return
        self.root.setProperty("kfont", int(overlay_cfg.font_size))
        self.root.setProperty("bgAlpha", float(overlay_cfg.opacity))
        self.root.setProperty("atTop", overlay_cfg.position.startswith("top"))
        if self.view.isVisible():
            self._place()
        self.timer.start()

    # ---------------------------------------------------------------- ventana
    def _screen(self):
        mon = self.cfg.monitor
        screens = QGuiApplication.screens()
        if mon == "primary":
            return QGuiApplication.primaryScreen()
        if mon.isdigit() and 1 <= int(mon) <= len(screens):
            return screens[int(mon) - 1]
        return QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()

    def _place(self) -> None:
        scr = self._screen()
        full, geo = scr.geometry(), scr.availableGeometry()
        self.root.setProperty("cardW", max(360, min(704, round(full.width() * 0.6))))
        w, h = int(self.root.property("width")), int(self.root.property("height"))
        self.view.setScreen(scr)
        self.view.resize(w, h)
        pos = self.cfg.position
        if pos.endswith("left"):
            x = geo.left() + HUECO
        elif pos.endswith("right"):
            x = geo.right() + 1 - w - HUECO
        else:
            x = geo.left() + (geo.width() - w) // 2
        y = geo.top() if pos.startswith("top") else geo.bottom() + 1 - h
        self.view.setPosition(x, y)

    def _show(self) -> None:
        self._place()
        self.view.show()
        if not self._styled and os.name == "nt":
            from . import win
            try:
                win.apply_overlay_style(int(self.view.winId()))
            except Exception:
                log.debug("no pude reforzar el estilo de la ventana", exc_info=True)
            self._styled = True
        self.shown_count += 1

    def _hide(self) -> None:
        if self.view is not None and self.view.isVisible():
            self.view.hide()

    def set_mask(self, x: int, y: int, w: int, h: int) -> None:
        if self.view is not None and w > 0 and h > 0:
            self.view.setMask(QRegion(x, y, w, h))

    # ------------------------------------------------------------------ lectura
    def close_clicked(self) -> None:
        """La X del overlay: corta la lectura (y si había un error, lo descarta)."""
        if self._sid:
            self._dismissed = self._sid
        self.reader.stop()

    def _push(self, key: str, value) -> None:
        if self._sent.get(key) != value:
            self.root.setProperty(key, value)
            self._sent[key] = value

    def _tick(self) -> None:
        if self.root is None:
            return
        snap = self.reader.snapshot()
        if snap is not None:
            if snap["id"] != self._sid:
                self._sid, self._sent, self._err_since = snap["id"], {}, None
            phase = snap["phase"]
            if phase == "error":
                self._err_since = self._err_since or time.monotonic()
                if self._sid == self._dismissed or time.monotonic() - self._err_since > ERROR_SECS:
                    phase = "done"
            # el id va primero: QML limpia lo de la lectura anterior al cambiarlo
            self._push("sid", snap["id"])
            self._push("phase", phase)
            self._push("texts", snap["texts"])
            self._push("durs", [-1 if d is None else d for d in snap["durs"]])
            self._push("complete", snap["complete"])
            self._push("peaks", snap["peaks"])
            self._push("errText", snap["error"])
            self._push("pos", snap["pos"])
        active = bool(self.root.property("uiActive"))
        if active and not self.view.isVisible():
            self._show()
        elif not active and self.view.isVisible():
            self.view.hide()

    # ----------------------------------------------------- para pruebas / demo
    def state(self) -> dict:
        """Lo que QML tiene ahora (para la demo y los tests)."""
        r = self.root
        names = ("phase", "uiActive", "lecWords", "globalPos", "totalDur", "complete", "paused",
                 "appear", "curBar", "width", "height")
        return {n: r.property(n) for n in names} if r is not None else {}

    def grab(self):
        """Foto de la ventana como QImage (render por software, anda aunque esté oculta)."""
        return self.view.grabWindow() if self.view is not None else None


# ---------------------------------------------------------------------- bandeja
def make_icon(speaking: bool = False) -> QIcon:
    """Parlante dibujado a mano (sin archivos de imagen); verde mientras lee."""
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(22, 163, 74) if speaking else QColor(31, 41, 55))
    p.drawRoundedRect(QRectF(2, 2, 60, 60), 14, 14)
    white = QColor(255, 255, 255)
    p.setBrush(white)
    p.drawPolygon(QPolygonF([QPointF(14, 25), QPointF(24, 25), QPointF(34, 16),
                             QPointF(34, 48), QPointF(24, 39), QPointF(14, 39)]))
    pen = QPen(white, 3)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(30, 22, 16, 20), -60 * 16, 120 * 16)
    p.drawArc(QRectF(30, 14, 26, 36), -60 * 16, 120 * 16)
    p.end()
    return QIcon(pm)


class UiHost:
    """Bandeja + overlay + bucle de Qt. Cumple el protocolo que usa App: run / stop / notify /
    set_speaking / apply_config."""

    def __init__(self, app):
        self.app = app
        self.qapp = ensure_qapp()
        self.dispatch = _Dispatcher()
        self.icons = {False: make_icon(False), True: make_icon(True)}
        self.overlay = OverlayController(app.reader, app.cfg.overlay)
        if self.overlay.error and app.cfg.overlay.enabled:
            log.warning("sigo sin overlay: %s", self.overlay.error)
        self.tray = QSystemTrayIcon(self.icons[False])
        self.tray.setToolTip("AltR")
        self.menu = self._build_menu()
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._activated)
        self.tray.show()

    def _build_menu(self) -> QMenu:
        app, menu = self.app, QMenu()

        def act(text: str, fn, checkable: bool = False):
            a = menu.addAction(text)
            if checkable:
                a.setCheckable(True)
            a.triggered.connect(lambda _checked=False: fn())
            return a

        act("Detener lectura", app.reader.stop)
        act("Leer el portapapeles", app.read_clipboard)
        menu.addSeparator()
        act("Abrir configuración", app.open_config)
        act("Recargar configuración", app.reload)
        act("Abrir registro (log)", app.open_log)
        get = getattr(app.platform, "autostart_enabled", None)
        put = getattr(app.platform, "set_autostart", None)
        if get and put:
            self._autostart = act("Iniciar con Windows", self._toggle_autostart, checkable=True)
            self._autostart_io = (get, put)
            menu.aboutToShow.connect(lambda: self._autostart.setChecked(bool(get())))
        menu.addSeparator()
        act(f"AltR {__version__}", lambda: None).setEnabled(False)
        act("Salir", app.quit)
        return menu

    def _toggle_autostart(self) -> None:
        get, put = self._autostart_io
        try:
            put(not get())
        except Exception:
            log.exception("no pude cambiar el inicio con Windows")

    def _activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.app.reader.stop()

    # --- protocolo de App (se puede llamar desde cualquier hilo) ---
    def run(self) -> None:
        self.qapp.exec()
        self.tray.hide()
        self.overlay.timer.stop()

    def stop(self) -> None:
        self.dispatch.post(self.qapp.quit)

    def notify(self, message: str, title: str = "AltR") -> None:
        self.dispatch.post(lambda: self.tray.showMessage(
            title, message, QSystemTrayIcon.MessageIcon.Information, 6000))

    def set_speaking(self, speaking: bool) -> None:
        def apply():
            self.tray.setIcon(self.icons[speaking])
            self.tray.setToolTip("AltR - leyendo..." if speaking else "AltR")
        self.dispatch.post(apply)

    def apply_config(self, cfg) -> None:
        self.dispatch.post(lambda: self.overlay.apply_config(cfg.overlay))
