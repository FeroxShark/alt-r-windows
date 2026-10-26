"""Actualizaciones: comparación de versiones, chequeo diario e instalador (sin internet)."""
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from altr import updates


class VersionTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(updates.parse_version("v0.2.1"), (0, 2, 1))
        self.assertEqual(updates.parse_version("1.0"), (1, 0))
        self.assertIsNone(updates.parse_version("nightly"))
        self.assertIsNone(updates.parse_version(""))

    def test_is_newer(self):
        self.assertTrue(updates.is_newer("v0.2.0", "0.1.9"))
        self.assertTrue(updates.is_newer("0.10.0", "0.9.0"))      # numérico, no alfabético
        self.assertTrue(updates.is_newer("1.0.0.1", "1.0.0"))
        self.assertFalse(updates.is_newer("0.1.0", "0.1.0"))
        self.assertFalse(updates.is_newer("1.0", "1.0.0"))
        self.assertFalse(updates.is_newer("0.0.9", "0.1.0"))
        self.assertFalse(updates.is_newer("basura", "0.1.0"))


class CheckLatestTests(unittest.TestCase):
    def test_newer(self):
        body = json.dumps({"tag_name": "v99.0.0", "html_url": "https://x/r"}).encode()
        with mock.patch.object(updates, "_get", return_value=body):
            info = updates.check_latest()
        self.assertTrue(info["newer"])
        self.assertEqual((info["version"], info["url"]), ("99.0.0", "https://x/r"))

    def test_same_version(self):
        body = json.dumps({"tag_name": "v" + updates.__version__}).encode()
        with mock.patch.object(updates, "_get", return_value=body):
            self.assertFalse(updates.check_latest()["newer"])

    def test_errors_are_friendly(self):
        def http(code):
            return urllib.error.HTTPError("u", code, "m", {}, io.BytesIO(b""))
        for exc, frag in ((http(404), "publicadas"), (http(403), "demasiados"), (http(500), "500"),
                          (urllib.error.URLError("sin red"), "internet")):
            with mock.patch.object(updates, "_get", side_effect=exc):
                with self.assertRaises(updates.UpdateError) as cm:
                    updates.check_latest()
            self.assertIn(frag, str(cm.exception))
        with mock.patch.object(updates, "_get", return_value=b"no es json"):
            with self.assertRaises(updates.UpdateError):
                updates.check_latest()
        with mock.patch.object(updates, "_get", return_value=b'{"tag_name": "nightly"}'):
            with self.assertRaises(updates.UpdateError):
                updates.check_latest()


class DailyCheckTests(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        p = mock.patch.dict(os.environ, {"ALTR_HOME": d.name})
        p.start()
        self.addCleanup(p.stop)

    def test_due_then_not(self):
        self.assertTrue(updates.due(now=1_000_000))                 # nunca se chequeó
        updates.record_check("0.5.0", now=1_000_000)
        self.assertFalse(updates.due(now=1_000_000 + 3600))
        self.assertTrue(updates.due(now=1_000_000 + updates.CHECK_EVERY + 1))
        self.assertTrue(updates.due(now=999_000))                   # reloj hacia atrás: se reintenta

    def test_failed_check_still_counts_and_keeps_latest(self):
        updates.record_check("99.0.0", now=1_000_000)
        updates.record_check(None, now=1_100_000)
        self.assertFalse(updates.due(now=1_100_001))
        self.assertEqual(updates.known_newer(), "99.0.0")

    def test_known_newer_ignores_installed(self):
        self.assertEqual(updates.known_newer(), "")
        updates.record_check(updates.__version__)
        self.assertEqual(updates.known_newer(), "")

    def test_corrupt_state_file(self):
        updates.state_file().write_text("{no", encoding="utf-8")
        self.assertTrue(updates.due())
        self.assertEqual(updates.known_newer(), "")


class InstallerTests(unittest.TestCase):
    GOOD = "function Install-AltR { }\n" + "# relleno\n" * 80

    def test_download_validates(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(updates, "_get", return_value=self.GOOD.encode()):
                path = updates.download_installer(Path(d))
            self.assertEqual(path.name, "install.ps1")
            self.assertIn("Install-AltR", path.read_text(encoding="utf-8"))
            with mock.patch.object(updates, "_get", return_value=b"<html>404</html>"):
                with self.assertRaises(updates.UpdateError):
                    updates.download_installer(Path(d))
            with mock.patch.object(updates, "_get", side_effect=urllib.error.URLError("x")):
                with self.assertRaises(updates.UpdateError):
                    updates.download_installer(Path(d))

    def test_launch_only_on_windows(self):
        with mock.patch.object(updates.os, "name", "posix"):
            with self.assertRaises(updates.UpdateError):
                updates.launch_installer(Path("install.ps1"))

    def test_launch_command(self):
        script = Path("tmp") / "install.ps1"   # antes de parchear os.name: con "nt" Path() ya no se instancia en Linux
        with mock.patch.object(updates.os, "name", "nt"), \
                mock.patch.object(updates.subprocess, "Popen") as popen:
            updates.launch_installer(script)
        cmd = popen.call_args.args[0]
        self.assertEqual(cmd[0], "powershell.exe")
        self.assertIn("Bypass", cmd)
        self.assertTrue(cmd[-1].endswith("install.ps1"))


if __name__ == "__main__":
    unittest.main()
