import unittest

from altr.hotkeys import (HotkeyError, MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, parse_hotkey)


class HotkeyTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(parse_hotkey("alt+r"), (MOD_ALT, 0x52))
        self.assertEqual(parse_hotkey("Ctrl+Alt+R"), (MOD_CONTROL | MOD_ALT, 0x52))
        self.assertEqual(parse_hotkey(" win + shift + s "), (MOD_WIN | MOD_SHIFT, 0x53))

    def test_digits_function_named(self):
        self.assertEqual(parse_hotkey("alt+1"), (MOD_ALT, 0x31))
        self.assertEqual(parse_hotkey("ctrl+f5"), (MOD_CONTROL, 0x74))
        self.assertEqual(parse_hotkey("f12"), (0, 0x7B))  # F-keys solas están permitidas
        self.assertEqual(parse_hotkey("alt+space"), (MOD_ALT, 0x20))

    def test_errors(self):
        for bad in ("", "r", "alt", "alt+", "alt+ñ", "alt+f25", "foo+r", "ctrl+alt+superfluo"):
            with self.assertRaises(HotkeyError, msg=bad):
                parse_hotkey(bad)


if __name__ == "__main__":
    unittest.main()
