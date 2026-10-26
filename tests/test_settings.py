"""Modelo de la ventana de Configuración (SettingsController), sin Windows ni internet."""
import os
import tempfile
import time
import tomllib
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from altr import settings
    from altr.ui import ensure_qapp
    HAVE_QT = True
except ImportError:  # sin PySide6
    HAVE_QT = False

try:
    import tomlkit  # noqa: F401
    HAVE_TOMLKIT = True
except ImportError:
    HAVE_TOMLKIT = False

from altr import secrets
from altr.config import DEFAULT_CONFIG_PATH, load_config
from tests.test_reader import FakeBackend, FakeProvider, wait_for

COMMENTED = '''# comentario de arriba
[general]
# atajo para leer
hotkey = "ctrl+alt+r"   # con comentario al costado
stop_hotkey = "ctrl+alt+s"

[overlay]
# opacidad
opacity = 0.925
position = "bottom-center"

[lexicon]
github = "guitjab"
'''


class FakePlatform:
    def __init__(self, taken=()):
        self.taken, self.auto = set(taken), False

    def hotkey_available(self, text):
        return text not in self.taken

    def autostart_enabled(self):
        return self.auto

    def set_autostart(self, v):
        self.auto = v


@unittest.skipUnless(HAVE_QT and HAVE_TOMLKIT, "falta PySide6 o tomlkit")
class SettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = ensure_qapp()

    def make(self, text=COMMENTED, **kw):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        path = Path(d.name) / "config.toml"
        path.write_text(text, encoding="utf-8")
        saved = []
        kw.setdefault("platform", FakePlatform())
        ctl = settings.SettingsController(path, on_saved=lambda: saved.append(1), **kw)
        return ctl, path, saved

    def test_load_defaults_and_values(self):
        ctl, _, _ = self.make()
        self.assertEqual(ctl.get("general.hotkey"), "ctrl+alt+r")
        self.assertEqual(ctl.get("overlay.opacity"), 0.925)
        self.assertEqual(ctl.get("tts.provider"), "edge")      # faltaba: sale del default
        self.assertFalse(ctl.dirty)

    def test_roundtrip_keeps_comments(self):
        ctl, path, saved = self.make()
        ctl.set("general.hotkey", "ctrl+alt+l")
        ctl.set("overlay.opacity", 0.7)
        ctl.set("overlay.font_size", 20.0)
        self.assertTrue(ctl.dirty)
        self.assertTrue(ctl.save())
        text = path.read_text(encoding="utf-8")
        for keep in ("# comentario de arriba", "# atajo para leer", "# con comentario al costado",
                     "# opacidad", 'github = "guitjab"', 'stop_hotkey = "ctrl+alt+s"'):
            self.assertIn(keep, text)
        cfg = load_config(path)
        self.assertEqual((cfg.general.hotkey, cfg.overlay.opacity, cfg.overlay.font_size),
                         ("ctrl+alt+l", 0.7, 20))
        self.assertEqual(saved, [1])
        self.assertFalse(ctl.dirty)
        self.assertEqual(ctl.get("general.hotkey"), "ctrl+alt+l")
        # sólo se escribió lo que cambió: lo demás no aparece como clave nueva
        self.assertNotIn("clipboard_fallback", tomllib.loads(text).get("general", {}))

    def test_invalid_blocks_save(self):
        ctl, path, saved = self.make()
        before = path.read_text(encoding="utf-8")
        ctl.set("overlay.opacity", 5.0)
        self.assertIn("opacity", ctl.error)
        self.assertEqual(ctl.errorKey, "overlay.opacity")
        self.assertFalse(ctl.save())
        self.assertEqual(path.read_text(encoding="utf-8"), before)
        self.assertEqual(saved, [])
        ctl.set("overlay.opacity", 0.9)
        self.assertEqual(ctl.error, "")
        ctl.set("general.hotkey", "ctrl+alt+s")      # igual que stop_hotkey
        self.assertIn("mismo", ctl.error)

    def test_revert(self):
        ctl, _, _ = self.make()
        ctl.set("tts.speed", 1.5)
        ctl.revert()
        self.assertEqual(ctl.get("tts.speed"), 1.0)
        self.assertFalse(ctl.dirty)

    def test_autostart_goes_to_platform_not_toml(self):
        plat = FakePlatform()
        ctl, path, saved = self.make(platform=plat)
        ctl.set("app.autostart", True)
        self.assertTrue(ctl.save())
        self.assertTrue(plat.auto)
        self.assertNotIn("autostart", path.read_text(encoding="utf-8"))
        self.assertEqual(saved, [1])

    def test_check_hotkey(self):
        ctl, _, _ = self.make(platform=FakePlatform(taken={"win+l"}))
        self.assertEqual(ctl.checkHotkey("read", "ctrl+alt+s")["state"], "dup")
        self.assertEqual(ctl.checkHotkey("read", "ctrl+alt+r")["state"], "own")
        self.assertEqual(ctl.checkHotkey("read", "win+l")["state"], "taken")
        self.assertEqual(ctl.checkHotkey("read", "ctrl+alt+k")["state"], "free")
        self.assertEqual(ctl.checkHotkey("stop", "")["state"], "none")
        ctl2, _, _ = self.make(platform=None)
        self.assertEqual(ctl2.checkHotkey("read", "ctrl+alt+k")["state"], "unknown")

    def test_capture_key(self):
        ctl, _, _ = self.make()
        ctrl_alt = settings._MOD_CTRL | settings._MOD_ALT
        self.assertEqual(ctl.captureKey(0x4C, ctrl_alt), {"done": True, "text": "ctrl+alt+l", "error": ""})
        self.assertFalse(ctl.captureKey(0x01000021, settings._MOD_CTRL)["done"])   # sólo Ctrl
        self.assertFalse(ctl.captureKey(0x4C, 0)["done"])                           # sin modificador
        self.assertEqual(ctl.captureKey(0x01000030, settings._MOD_CTRL)["text"], "ctrl+f1")

    def test_voices(self):
        ctl, _, _ = self.make(voices_loader=lambda: settings.SAMPLE_VOICES)
        ctl.loadVoices()
        wait_for(lambda: self.qapp.processEvents() or ctl.voicesState == "ready")
        self.assertEqual(ctl.voicesState, "ready")
        self.assertTrue(any(v["name"] == "es-AR-ElenaNeural" for v in ctl.voices))
        self.assertTrue(all("locale" in v for v in ctl.voices))

        def boom():
            raise OSError("sin red")
        ctl2, _, _ = self.make(voices_loader=boom)
        ctl2.loadVoices()
        wait_for(lambda: self.qapp.processEvents() or ctl2.voicesState == "error")
        self.assertEqual(ctl2.voicesState, "error")

    def test_test_voice_uses_unsaved_config(self):
        ctl, path, _ = self.make()
        ctl.set("edge.voice", "en-US-AndrewNeural")
        prov, back = FakeProvider(), FakeBackend()
        seen = []

        def fake_make(cfg):
            seen.append(cfg.edge.voice)
            return prov
        with mock.patch("altr.reader.make_provider", fake_make):
            ctl2 = ctl
            ctl2._backend_factory = lambda: back
            ctl2.testVoice()
            self.assertTrue(wait_for(lambda: self.qapp.processEvents() or back.played))
            self.assertTrue(wait_for(lambda: self.qapp.processEvents() or not ctl.testing))
        self.assertEqual(seen[0], "en-US-AndrewNeural")
        self.assertIn("Hello", prov.calls[0])                 # frase en el idioma de la voz
        self.assertNotIn("Andrew", path.read_text(encoding="utf-8"))   # no se guardó

    def test_test_voice_blocked_by_invalid(self):
        ctl, _, _ = self.make()
        ctl.set("tts.speed", 99)
        ctl.testVoice()
        self.assertFalse(ctl.testing)
        self.assertTrue(ctl.testMessage)

    def test_api_key_never_in_toml(self):
        store = {}
        kr = mock.Mock()
        kr.set_password.side_effect = lambda s, a, k: store.update({(s, a): k})
        kr.get_password.side_effect = lambda s, a: store.get((s, a))
        kr.get_keyring.return_value = mock.Mock(priority=5)
        ctl, path, _ = self.make()
        with mock.patch("altr.secrets._keyring", return_value=kr):
            ctl.saveApiKey("  sk-secreta  ")
            self.assertTrue(ctl.keyStored)
            self.assertEqual(secrets.get_api_key(), "sk-secreta")
            ctl.set("openai.base_url", "http://localhost:8880/v1")
            ctl.save()
            self.assertNotIn("sk-secreta", path.read_text(encoding="utf-8"))
        with mock.patch("altr.secrets._keyring", return_value=None):
            ctl.saveApiKey("x")
            self.assertIn("variable de entorno", ctl.error)
            self.assertEqual(secrets.get_api_key(), "")

    def test_openai_provider_falls_back_to_stored_key(self):
        from altr.config import parse_config
        from altr.providers import OpenAIProvider
        cfg = parse_config({"tts": {"provider": "openai"}, "openai": {"api_key_env": "ALTR_TEST_NOPE"}})
        with mock.patch("altr.secrets.get_api_key", return_value="guardada"):
            self.assertEqual(OpenAIProvider(cfg)._api_key(), "guardada")

    def test_request_file(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"ALTR_HOME": d}):
            self.assertIsNone(settings.take_request())
            settings.request_open("voz")
            self.assertEqual(settings.take_request(), "voz")
            settings.request_open()
            self.assertEqual(settings.take_request(), "")
            self.assertIsNone(settings.take_request())

    def test_default_config_roundtrips(self):
        ctl, path, _ = self.make(text=DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
        ctl.set("tts.provider", "openai")
        ctl.set("openai.model", "tts-1")
        self.assertTrue(ctl.save())
        text = path.read_text(encoding="utf-8")
        self.assertIn("# Motor de voz:", text)
        self.assertEqual(load_config(path).openai.model, "tts-1")

    def test_update_flow(self):
        calls = []
        ctl, _, _ = self.make(update_checker=lambda: {"version": "9.9.9", "newer": True, "url": "https://x/r"},
                              update_installer=lambda: calls.append("run"), demo=True)
        self.assertEqual(ctl.updateState, "idle")
        ctl.checkUpdates()
        self.assertEqual(ctl.updateState, "checking")
        wait_for(lambda: self.qapp.processEvents() or (ctl.updateState != "checking"))
        self.assertEqual((ctl.updateState, ctl.latestVersion, ctl.releaseUrl), ("available", "9.9.9", "https://x/r"))
        self.assertTrue(ctl.canUpdate)
        ctl.installUpdate()
        wait_for(lambda: self.qapp.processEvents() or (ctl.updateState == "installing" and calls))
        self.assertEqual(calls, ["run"])

    def test_update_none_and_errors(self):
        ctl, _, _ = self.make(update_checker=lambda: {"version": "0.0.1", "newer": False, "url": ""}, demo=True)
        ctl.checkUpdates()
        wait_for(lambda: self.qapp.processEvents() or (ctl.updateState != "checking"))
        self.assertEqual(ctl.updateState, "none")

        def boom():
            raise settings.updates.UpdateError("No pude conectar con GitHub.")
        ctl, _, _ = self.make(update_checker=boom, demo=True)
        ctl.checkUpdates()
        wait_for(lambda: self.qapp.processEvents() or (ctl.updateState != "checking"))
        self.assertEqual((ctl.updateState, ctl.updateMessage), ("error", "No pude conectar con GitHub."))

        def bad_install():
            raise settings.updates.UpdateError("no instalo")
        ctl, _, _ = self.make(update_checker=lambda: {"version": "9.9.9", "newer": True, "url": ""},
                              update_installer=bad_install, demo=True)
        ctl.checkUpdates()
        wait_for(lambda: self.qapp.processEvents() or (ctl.updateState == "available"))
        ctl.installUpdate()
        wait_for(lambda: self.qapp.processEvents() or (ctl.updateState == "error"))
        self.assertEqual(ctl.updateMessage, "no instalo")

    def test_check_updates_is_a_setting(self):
        ctl, path, _ = self.make()
        self.assertIs(ctl.get("general.check_updates"), True)
        ctl.set("general.check_updates", False)
        self.assertTrue(ctl.save())
        self.assertFalse(load_config(path).general.check_updates)

    def test_capturing_releases_hotkeys_once(self):
        seen = []
        ctl, _, _ = self.make(on_capture=seen.append)
        ctl.setCapturing(True)
        ctl.setCapturing(True)
        ctl.setCapturing(False)
        ctl.setCapturing(False)
        self.assertEqual(seen, [True, False])

    def test_every_section_renders(self):
        with tempfile.TemporaryDirectory() as d:
            win = settings.SettingsWindow(Path(d) / "config.toml", platform=FakePlatform(), demo=True)
            self.assertTrue(win.created, win.error)
            win.view.show()
            for sec in settings.SECTIONS:
                win.select(sec)
                self.qapp.processEvents()
                img = win.grab()
                self.assertFalse(img.isNull(), sec)
            win.view.hide()

    def test_window_and_cli_screenshot(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "config.toml"
            shot = Path(d) / "s.png"
            lines = []
            rc = settings.run_settings(cfg, screenshot=str(shot), say=lines.append)
            self.assertEqual(rc, 0, lines)
            self.assertTrue(shot.exists())

    def test_cli_settings_flag(self):
        from altr import cli
        args = cli.build_parser().parse_args(["--settings", "voz"])
        self.assertEqual(args.settings, "voz")
        self.assertEqual(cli.build_parser().parse_args(["--settings"]).settings, "")


if __name__ == "__main__":
    unittest.main()
