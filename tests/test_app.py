import tempfile
import threading
import time
import unittest
from pathlib import Path

from altr.app import App
from altr.config import parse_config
from tests.test_reader import FakeBackend, FakeProvider, wait_for


class FakeHotkeys:
    def __init__(self, on_trigger, on_error=None):
        self.on_trigger = on_trigger
        self.bindings = None
        self.reloads = []

    def start(self, bindings):
        self.bindings = bindings

    def reload(self, bindings):
        self.reloads.append(bindings)

    def stop(self):
        pass


class FakePlatform:
    HotkeyManager = FakeHotkeys

    def __init__(self, selection="Hola mundo.", clipboard="del portapapeles."):
        self.selection = selection
        self.clipboard = clipboard
        self.calls = []
        self.opened = []

    def single_instance(self):
        return True

    def capture_selection(self, restore, fallback, clipboard_only_apps):
        self.calls.append((restore, fallback, tuple(clipboard_only_apps)))
        return self.selection

    def get_clipboard_text(self):
        return self.clipboard

    def open_path(self, p):
        self.opened.append(p)


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "config.toml"
        self.plat = FakePlatform()
        self.back = FakeBackend()
        self.app = App(self.path, self.plat, backend=self.back)
        self.app.reader.set_config(self.app.cfg, provider=FakeProvider())

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_default_config(self):
        self.assertTrue(self.path.exists())
        self.assertEqual(self.app.cfg.general.hotkey, "ctrl+alt+r")

    def test_read_hotkey_speaks_selection(self):
        self.app.on_hotkey("read")
        self.assertTrue(wait_for(lambda: self.back.played))
        self.assertEqual(self.back.played[0][0], "Hola mundo.")
        restore, fallback, only = self.plat.calls[0]
        self.assertTrue(restore and fallback)
        self.assertIn("WindowsTerminal.exe", only)

    def test_empty_selection_notifies(self):
        self.plat.selection = "  "
        msgs = []
        self.app.notify = msgs.append
        self.app.read_selection()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(self.back.played, [])

    def test_stop_hotkey(self):
        self.back.play_time = 5
        self.app.on_hotkey("read")
        self.assertTrue(wait_for(lambda: self.back.played))
        self.app.on_hotkey("stop")
        self.assertTrue(wait_for(lambda: not self.app.reader.speaking))

    def test_read_clipboard(self):
        self.app.read_clipboard()
        self.assertTrue(wait_for(lambda: self.back.played))
        self.assertEqual(self.back.played[0][0], "del portapapeles.")

    def test_reload_ok_and_hotkeys_updated(self):
        self.app.hotkeys = FakeHotkeys(self.app.on_hotkey)
        self.path.write_text('[general]\nhotkey = "ctrl+alt+l"\n[tts]\nvolume = 20\n', encoding="utf-8")
        self.app.reload()
        self.assertEqual(self.app.cfg.tts.volume, 20)
        self.assertEqual(self.app.hotkeys.reloads[0]["read"], "ctrl+alt+l")

    def test_reload_applies_overlay_config_to_tray(self):
        class Tray:
            def __init__(self):
                self.applied, self.notes = [], []

            def apply_config(self, cfg):
                self.applied.append(cfg.overlay.position)

            def notify(self, msg):
                self.notes.append(msg)

        self.app.tray = Tray()
        self.path.write_text('[overlay]\nposition = "top-right"\n', encoding="utf-8")
        self.app.reload()
        self.assertEqual(self.app.tray.applied, ["top-right"])

    def test_reload_bad_config_keeps_old(self):
        self.app.hotkeys = FakeHotkeys(self.app.on_hotkey)
        msgs = []
        self.app.notify = lambda m, force=False: msgs.append(m)
        self.path.write_text('[tts]\nprovider = "azure"\n', encoding="utf-8")
        self.app.reload()
        self.assertEqual(self.app.cfg.tts.provider, "edge")
        self.assertEqual(self.app.hotkeys.reloads, [])
        self.assertIn("azure", msgs[0])

    def test_bad_config_at_startup_falls_back_to_defaults(self):
        p = Path(self.tmp.name) / "malo.toml"
        p.write_text("esto no es toml [", encoding="utf-8")
        app = App(p, FakePlatform(), backend=FakeBackend())
        self.assertEqual(app.cfg.tts.provider, "edge")
        self.assertIn("Config inválido", app._pending_error)

    def test_run_and_quit(self):
        t = threading.Thread(target=self.app.run)
        t.start()
        self.assertTrue(wait_for(lambda: self.app.hotkeys is not None and self.app.hotkeys.bindings))
        self.assertEqual(self.app.hotkeys.bindings, {"read": "ctrl+alt+r", "stop": "ctrl+alt+s"})
        self.app.quit()
        t.join(3)
        self.assertFalse(t.is_alive())


if __name__ == "__main__":
    unittest.main()
