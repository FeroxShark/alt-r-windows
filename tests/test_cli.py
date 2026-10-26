import contextlib
import io
import json
import os
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from altr import cli


def run(args, home):
    buf = io.StringIO()
    with mock.patch.dict(os.environ, {"ALTR_HOME": home}), contextlib.redirect_stdout(buf):
        rc = cli.main(args)
    return rc, buf.getvalue()


class CliTests(unittest.TestCase):
    def test_version_and_check(self):
        with tempfile.TemporaryDirectory() as d:
            rc, out = run(["--version"], d)
            self.assertEqual((rc, out.split()[0]), (0, "AltR"))
            rc, out = run(["--check"], d)
            self.assertEqual(rc, 0)
            self.assertIn("alt+r", out)
            self.assertTrue((Path(d) / "config.toml").exists())

    def test_check_bad_config(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "config.toml").write_text('[tts]\nspeed = 99\n', encoding="utf-8")
            rc, out = run(["--check"], d)
            self.assertEqual(rc, 2)
            self.assertIn("speed", out)

    def test_say_out_with_command_provider_concatenates_wav(self):
        with tempfile.TemporaryDirectory() as d:
            gen = Path(d) / "gen.py"
            gen.write_text(
                "import sys, wave\n"
                "w = wave.open(sys.argv[1], 'wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)\n"
                "w.writeframes(b'\\x00\\x00' * 800); w.close()\n", encoding="utf-8")
            import sys
            cfg = Path(d) / "c.toml"
            cfg.write_text(
                '[tts]\nprovider = "command"\n[command]\n'
                f'args = [{json.dumps(sys.executable)}, {json.dumps(str(gen))}, "{{output}}"]\n'
                'stdin = false\noutput_ext = "wav"\n',
                encoding="utf-8")
            text = " ".join(f"Oración larga número {i} que ocupa bastante espacio en el texto." for i in range(15))
            dest = Path(d) / "salida.wav"
            rc, out = run(["--config", str(cfg), "--say", text, "--out", str(dest)], d)
            self.assertEqual(rc, 0, out)
            with wave.open(str(dest)) as w:
                self.assertGreater(w.getnframes(), 800)  # más de un trozo unido


if __name__ == "__main__":
    unittest.main()
