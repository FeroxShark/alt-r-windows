import os
import tempfile
import unittest
from pathlib import Path

from altr.config import (ConfigError, DEFAULT_CONFIG_PATH, ensure_config, load_config,
                         parse_config)


class ConfigTests(unittest.TestCase):
    def test_default_template_is_valid(self):
        cfg = load_config(DEFAULT_CONFIG_PATH)
        self.assertEqual(cfg.general.hotkey, "ctrl+alt+r")
        self.assertEqual(cfg.tts.provider, "edge")
        self.assertEqual(cfg.edge.voice, "es-AR-ElenaNeural")
        self.assertEqual(cfg.warnings, [])
        self.assertEqual(cfg.lexicon, {})

    def test_empty_file_gives_defaults(self):
        cfg = parse_config({})
        self.assertEqual(cfg.tts.speed, 1.0)
        self.assertTrue(cfg.general.clipboard_fallback)

    def test_override_and_int_to_float(self):
        cfg = parse_config({"tts": {"speed": 2, "volume": 40}, "edge": {"voice": "es-ES-ElviraNeural"}})
        self.assertEqual(cfg.tts.speed, 2.0)
        self.assertIsInstance(cfg.tts.speed, float)
        self.assertEqual(cfg.tts.volume, 40)
        self.assertEqual(cfg.edge.voice, "es-ES-ElviraNeural")

    def test_unknown_keys_warn(self):
        cfg = parse_config({"tts": {"vocecita": "x"}, "raro": {}})
        self.assertEqual(len(cfg.warnings), 2)

    def test_wrong_type(self):
        with self.assertRaisesRegex(ConfigError, r"\[tts\] speed"):
            parse_config({"tts": {"speed": "rápido"}})
        with self.assertRaises(ConfigError):
            parse_config({"general": {"notifications": 1}})

    def test_ranges_and_provider(self):
        for bad in ({"tts": {"speed": 9}}, {"tts": {"volume": 101}}, {"tts": {"provider": "azure"}},
                    {"general": {"hotkey": "r"}}, {"general": {"hotkey": "alt+nada"}},
                    {"general": {"stop_hotkey": "ctrl+alt+r"}}, {"overlay": {"position": "arriba"}}, {"overlay": {"monitor": "0"}}, {"overlay": {"opacity": 0.1}}, {"overlay": {"font_size": 40}}, {"text": {"max_chars": 0}}):
            with self.assertRaises(ConfigError, msg=bad):
                parse_config(bad)

    def test_overlay_defaults_and_overrides(self):
        o = parse_config({}).overlay
        self.assertEqual((o.enabled, o.position, o.monitor, o.opacity, o.font_size),
                         (True, "bottom-center", "active", 0.925, 16))
        o = parse_config({"overlay": {"position": "Top-Right", "monitor": "2", "opacity": 1}}).overlay
        self.assertEqual((o.position, o.monitor, o.opacity), ("top-right", "2", 1.0))

    def test_empty_stop_hotkey_ok(self):
        self.assertEqual(parse_config({"general": {"stop_hotkey": ""}}).general.stop_hotkey, "")

    def test_command_requires_args(self):
        with self.assertRaisesRegex(ConfigError, "args"):
            parse_config({"tts": {"provider": "command"}})
        cfg = parse_config({"tts": {"provider": "command"}, "command": {"args": ["x", "{output}"]}})
        self.assertEqual(cfg.command.args, ["x", "{output}"])

    def test_lexicon_lowercased(self):
        self.assertEqual(parse_config({"lexicon": {"GitHub": "guitjab"}}).lexicon, {"github": "guitjab"})

    def test_ensure_config_and_syntax_error(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sub" / "config.toml"
            self.assertTrue(ensure_config(p))
            self.assertFalse(ensure_config(p))
            load_config(p)
            p.write_text("[tts\nprovider = ", encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "sintaxis"):
                load_config(p)

    def test_missing_file(self):
        with self.assertRaises(ConfigError):
            load_config(Path("/no/existe/config.toml"))


if __name__ == "__main__":
    unittest.main()
