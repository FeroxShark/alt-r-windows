"""Pruebas de la capa de Windows. Sólo corren en Windows (CI: windows-latest)."""
import os
import sys
import threading
import time
import unittest

IS_WIN = os.name == "nt"


@unittest.skipUnless(IS_WIN, "sólo Windows")
class WinTests(unittest.TestCase):
    def test_import(self):
        from altr import win  # noqa: F401

    def test_clipboard_roundtrip(self):
        from altr import win
        text = "Prueba ñandú ✓ 日本語\nsegunda línea"
        before = win.clipboard_sequence()
        self.assertTrue(win.set_clipboard_text(text))
        self.assertNotEqual(win.clipboard_sequence(), before)
        self.assertEqual(win.get_clipboard_text(), text)

    def test_hotkey_register_and_error_on_duplicate(self):
        from altr import win
        errors = []
        a = win.HotkeyManager(lambda n: None, on_error=errors.append)
        a.start({"read": "ctrl+alt+shift+f12", "stop": ""})
        self.assertEqual(errors, [])
        b = win.HotkeyManager(lambda n: None, on_error=errors.append)
        b.start({"read": "ctrl+alt+shift+f12"})
        self.assertEqual(len(errors), 1)
        self.assertIn("ya usa", errors[0])
        a.stop()
        b.stop()

    def test_hotkey_fires_on_simulated_keys(self):
        from altr import win
        got = threading.Event()
        m = win.HotkeyManager(lambda n: got.set())
        m.start({"read": "ctrl+alt+shift+f11"})
        VK_F11 = 0x7A
        win.send_keys([(win.VK_CONTROL, False), (win.VK_MENU, False), (win.VK_SHIFT, False),
                       (VK_F11, False), (VK_F11, True),
                       (win.VK_SHIFT, True), (win.VK_MENU, True), (win.VK_CONTROL, True)])
        self.assertTrue(got.wait(3))
        m.stop()

    def test_single_instance_flag(self):
        from altr import win
        self.assertTrue(win.single_instance())

    def test_foreground_process_name_is_string(self):
        from altr import win
        self.assertIsInstance(win.foreground_process_name(), str)

    def test_autostart_roundtrip(self):
        from altr import win
        was = win.autostart_enabled()
        try:
            win.set_autostart(True)
            self.assertTrue(win.autostart_enabled())
            win.set_autostart(False)
            self.assertFalse(win.autostart_enabled())
        finally:
            win.set_autostart(was)

    def test_mci_plays_generated_wav(self):
        """Puede fallar en máquinas sin placa de sonido (como los runners de CI)."""
        import tempfile, wave
        from pathlib import Path
        from altr import win
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.wav"
            with wave.open(str(p), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
                w.writeframes(b"\x00\x00" * 1600)
            try:
                win.MciBackend().play(p, 50, threading.Event())
            except RuntimeError as e:
                self.skipTest(f"MCI sin dispositivo de audio: {e}")

    def test_selection_capture_with_notepad(self):
        """Abre el Bloc de notas con texto, lo selecciona y verifica la captura real."""
        import subprocess, tempfile
        from pathlib import Path
        from altr import win
        if not os.environ.get("ALTR_TEST_GUI"):
            self.skipTest("ALTR_TEST_GUI=1 para probar con una ventana real")
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "n.txt"
            f.write_text("texto de prueba para AltR", encoding="utf-8")
            p = subprocess.Popen(["notepad.exe", str(f)])
            try:
                time.sleep(2.5)
                win.send_keys([(win.VK_CONTROL, False), (0x41, False), (0x41, True), (win.VK_CONTROL, True)])
                time.sleep(0.3)
                win.set_clipboard_text("anterior")
                got = win.capture_selection(restore=True, fallback=False)
                self.assertEqual(got.strip(), "texto de prueba para AltR")
                self.assertEqual(win.get_clipboard_text(), "anterior")
            finally:
                p.kill()


if __name__ == "__main__":
    unittest.main()
