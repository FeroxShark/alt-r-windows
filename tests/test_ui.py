"""Overlay y bandeja con Qt. Corren con QT_QPA_PLATFORM=offscreen (se fuerza acá); si PySide6 no
está instalado se saltean."""
import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from altr import ui
    from altr.demo import DEMO_TEXT, DemoProvider, run_demo
    HAVE_QT = True
except ImportError:  # sin PySide6
    HAVE_QT = False

from altr.config import parse_config
from altr.player import SimBackend
from altr.reader import Reader
from tests.test_reader import FakeBackend, FakeProvider


@unittest.skipUnless(HAVE_QT, "PySide6 no está instalado")
class OverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = ui.ensure_qapp()

    def pump(self, cond, timeout=8.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.qapp.processEvents()
            if cond():
                return True
            time.sleep(0.01)
        self.qapp.processEvents()
        return cond()

    def make(self, overlay=None, provider=None, backend=None):
        cfg = parse_config({"overlay": overlay or {}})
        reader = Reader(cfg, backend or SimBackend(), provider=provider or DemoProvider(40))
        ov = ui.OverlayController(reader, cfg.overlay)
        self.addCleanup(self._close, reader, ov)
        return reader, ov

    @staticmethod
    def _close(reader, ov):
        reader.stop()
        ov.timer.stop()
        if ov.view is not None:
            ov.view.hide()

    def test_qml_loads_without_errors(self):
        _, ov = self.make()
        self.assertEqual(ov.error, "")
        self.assertTrue(ov.created)
        self.assertFalse(ov.view.isVisible())  # sin lectura no se ve

    def test_shows_text_and_hides_when_done(self):
        reader, ov = self.make()
        reader.speak(DEMO_TEXT)
        self.assertTrue(self.pump(lambda: ov.state().get("phase") == "playing"))
        self.assertTrue(ov.view.isVisible())
        self.assertEqual(ov.state()["lecWords"], len(DEMO_TEXT.split()))
        self.assertTrue(self.pump(lambda: ov.state()["globalPos"] > 0.5))
        reader.stop()
        self.assertTrue(self.pump(lambda: not ov.state()["uiActive"] and not ov.view.isVisible()))

    def test_window_is_frameless_tool_and_translucent(self):
        _, ov = self.make()
        flags = ov.view.flags()
        for f in ("FramelessWindowHint", "WindowStaysOnTopHint", "WindowDoesNotAcceptFocus", "Tool"):
            flag = getattr(ui.Qt.WindowType, f)
            self.assertEqual(flags & flag, flag, f)
        self.assertEqual(ov.view.color().alpha(), 0)

    def test_placement_follows_config(self):
        for pos, atTop in (("bottom-center", False), ("top-right", True), ("bottom-left", False)):
            reader, ov = self.make({"position": pos})
            self.assertEqual(ov.root.property("atTop"), atTop)
            reader.speak(DEMO_TEXT)
            self.assertTrue(self.pump(lambda: ov.view.isVisible()))
            geo = ov._screen().availableGeometry()
            v = ov.view
            if atTop:
                self.assertEqual(v.y(), geo.top())
            else:
                self.assertEqual(v.y() + v.height(), geo.bottom() + 1)
            if pos.endswith("right"):
                self.assertEqual(v.x() + v.width(), geo.right() + 1 - ui.HUECO)
            elif pos.endswith("left"):
                self.assertEqual(v.x(), geo.left() + ui.HUECO)
            else:
                self.assertAlmostEqual(v.x() + v.width() / 2, geo.center().x(), delta=2)
            reader.stop()

    def test_config_values_reach_qml(self):
        _, ov = self.make({"opacity": 0.6, "font_size": 20})
        self.assertAlmostEqual(ov.root.property("bgAlpha"), 0.6)
        self.assertEqual(ov.root.property("kfont"), 20)
        cfg2 = parse_config({"overlay": {"opacity": 0.8, "font_size": 14}})
        ov.apply_config(cfg2.overlay)
        self.assertAlmostEqual(ov.root.property("bgAlpha"), 0.8)
        self.assertEqual(ov.root.property("kfont"), 14)

    def test_disabled_never_shows(self):
        reader, ov = self.make({"enabled": False})
        self.assertFalse(ov.created)
        reader.speak("Hola, esto no se ve.")
        self.pump(lambda: False, 0.4)
        self.assertIsNone(ov.view)

    def test_pause_seek_and_close_buttons(self):
        reader, ov = self.make()
        reader.speak(DEMO_TEXT)
        self.assertTrue(self.pump(lambda: ov.state().get("phase") == "playing"))
        ov.bridge.togglePause()
        self.assertTrue(self.pump(lambda: ov.state()["phase"] == "paused"))
        ov.bridge.togglePause()
        self.assertTrue(self.pump(lambda: ov.state()["phase"] == "playing"))
        self.assertTrue(self.pump(lambda: ov.state()["complete"]))
        target = ov.state()["totalDur"] * 0.6
        ov.bridge.seek(target)
        self.assertTrue(self.pump(lambda: ov.state()["globalPos"] >= target - 0.5))
        ov.bridge.stop()
        self.assertTrue(self.pump(lambda: not ov.view.isVisible()))

    def test_mask_covers_only_the_capsule(self):
        reader, ov = self.make()
        reader.speak(DEMO_TEXT)
        self.assertTrue(self.pump(lambda: ov.state().get("phase") == "playing"))
        self.assertTrue(self.pump(lambda: ov.state()["appear"] > 0.99))
        mask = ov.view.mask().boundingRect()
        self.assertEqual(mask.width(), ov.state()["width"])
        self.assertGreater(mask.height(), 80)
        self.assertLess(mask.height(), ov.state()["height"])

    def test_error_shows_and_close_dismisses(self):
        class Boom(FakeProvider):
            def synthesize(self, *a):
                from altr.providers import TTSError
                raise TTSError("sin internet")

        reader, ov = self.make(provider=Boom())
        reader.speak("Hola.")
        self.assertTrue(self.pump(lambda: ov.state().get("phase") == "error"))
        self.assertTrue(ov.view.isVisible())
        self.assertEqual(ov.root.property("errText"), "sin internet")
        ov.bridge.stop()
        self.assertTrue(self.pump(lambda: not ov.view.isVisible()))

    def test_second_reading_replaces_first_even_with_same_text(self):
        reader, ov = self.make()
        reader.speak("Una frase corta para leer.")
        self.assertTrue(self.pump(lambda: ov.state().get("lecWords") == 5))
        reader.speak("Una frase corta para leer.")
        self.assertTrue(self.pump(lambda: ov.state().get("phase") == "playing"))
        self.assertTrue(self.pump(lambda: ov.state().get("lecWords") == 5))

    def test_karaoke_word_follows_position(self):
        reader, ov = self.make()
        reader.speak(DEMO_TEXT)
        self.assertTrue(self.pump(lambda: ov.state().get("lecWords", 0) > 0 and ov.state()["globalPos"] > 0.3))
        a = ov.root.property("visPos")
        self.assertTrue(self.pump(lambda: ov.root.property("visPos") > a + 0.5))

    def test_grab_has_pixels(self):
        reader, ov = self.make()
        reader.speak(DEMO_TEXT)
        self.assertTrue(self.pump(lambda: ov.state().get("phase") == "playing"))
        self.pump(lambda: ov.state()["appear"] > 0.99)
        img = ov.grab()
        self.assertFalse(img.isNull())
        self.assertTrue(any(img.pixelColor(x, img.height() // 2).alpha() > 100
                            for x in range(0, img.width(), 8)))


@unittest.skipUnless(HAVE_QT, "PySide6 no está instalado")
class HostTests(unittest.TestCase):
    def test_icon_draws_both_states(self):
        ui.ensure_qapp()
        for s in (False, True):
            icon = ui.make_icon(s)
            self.assertFalse(icon.pixmap(32, 32).isNull())

    def test_uihost_protocol_and_menu(self):
        from altr.app import App
        from tests.test_app import FakePlatform

        with tempfile.TemporaryDirectory() as d:
            app = App(Path(d) / "config.toml", FakePlatform(), backend=FakeBackend())
            host = ui.UiHost(app)
            labels = [a.text() for a in host.menu.actions() if a.text()]
            for want in ("Detener lectura", "Leer el portapapeles", "Abrir configuración",
                         "Recargar configuración", "Salir"):
                self.assertIn(want, labels)
            host.set_speaking(True)
            host.notify("hola")
            host.apply_config(app.cfg)
            ui.ensure_qapp().processEvents()
            host.stop()
            host.run()   # el quit ya está encolado: vuelve enseguida
            host.overlay.timer.stop()


@unittest.skipUnless(HAVE_QT, "PySide6 no está instalado")
class DemoTests(unittest.TestCase):
    def test_demo_passes(self):
        lines = []
        with tempfile.TemporaryDirectory() as d:
            shot = str(Path(d) / "overlay.png")
            code = run_demo(say=lines.append, cps=40, screenshot=shot)
            self.assertTrue(Path(shot).stat().st_size > 3000)
        self.assertEqual(code, 0, "\n".join(lines))
        self.assertEqual(lines[-1], "Demo OK")


if __name__ == "__main__":
    unittest.main()
