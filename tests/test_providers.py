import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from altr.config import parse_config
from altr.providers import (CommandProvider, EdgeProvider, OpenAIProvider, TTSError, make_provider)


class _Handler(BaseHTTPRequestHandler):
    seen: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Handler.seen.append((self.path, self.headers.get("Authorization"), body))
        if self.headers.get("Authorization") == "Bearer mala":
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"error":"bad key"}')
            return
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.end_headers()
        self.wfile.write(b"ID3FAKEAUDIO")

    def log_message(self, *a):
        pass


class OpenAITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_port}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def cfg(self, **openai):
        o = {"base_url": self.base, "model": "kokoro", "voice": "ef_dora", "api_key_env": ""}
        o.update(openai)
        return parse_config({"tts": {"provider": "openai", "speed": 1.25}, "openai": o})

    def test_request_shape_no_key(self):
        _Handler.seen.clear()
        with tempfile.TemporaryDirectory() as d:
            out = make_provider(self.cfg()).synthesize("hola", Path(d), "c0")
            self.assertEqual(out.read_bytes(), b"ID3FAKEAUDIO")
            self.assertEqual(out.suffix, ".mp3")
        path, auth, body = _Handler.seen[0]
        self.assertEqual(path, "/v1/audio/speech")
        self.assertIsNone(auth)
        self.assertEqual(body["model"], "kokoro")
        self.assertEqual(body["voice"], "ef_dora")
        self.assertEqual(body["input"], "hola")
        self.assertEqual(body["speed"], 1.25)
        self.assertNotIn("instructions", body)

    def test_key_from_env_and_instructions(self):
        _Handler.seen.clear()
        with mock.patch.dict(os.environ, {"MI_CLAVE": "sk-123"}), tempfile.TemporaryDirectory() as d:
            OpenAIProvider(self.cfg(api_key_env="MI_CLAVE", instructions="tranquilo")).synthesize("x", Path(d), "c0")
        _, auth, body = _Handler.seen[0]
        self.assertEqual(auth, "Bearer sk-123")
        self.assertEqual(body["instructions"], "tranquilo")

    def test_missing_env_key(self):
        env = {k: v for k, v in os.environ.items() if k != "NO_EXISTE_XYZ"}
        with mock.patch.dict(os.environ, env, clear=True), tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(TTSError, "NO_EXISTE_XYZ"):
                OpenAIProvider(self.cfg(api_key_env="NO_EXISTE_XYZ")).synthesize("x", Path(d), "c0")

    def test_http_error_message(self):
        with mock.patch.dict(os.environ, {"K": "mala"}), tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(TTSError, "401.*API key"):
                OpenAIProvider(self.cfg(api_key_env="K")).synthesize("x", Path(d), "c0")

    def test_connection_refused(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(TTSError, "conectar"):
                OpenAIProvider(self.cfg(base_url="http://127.0.0.1:1/v1")).synthesize("x", Path(d), "c0")


FAKE_TTS = """
import sys, pathlib
args = sys.argv[1:]
out = args[args.index('--out') + 1]
text = sys.stdin.read() if '--stdin' in args else args[args.index('--text') + 1]
pathlib.Path(out).write_bytes(('AUDIO:' + text + ':' + args[args.index('--ls') + 1]).encode())
"""


class CommandTests(unittest.TestCase):
    def provider(self, d, extra, stdin):
        script = Path(d) / "fake.py"
        script.write_text(FAKE_TTS, encoding="utf-8")
        args = [sys.executable, str(script), "--out", "{output}", "--ls", "{length_scale}"] + extra
        return CommandProvider(parse_config({"tts": {"provider": "command", "speed": 2.0},
                                             "command": {"args": args, "stdin": stdin, "output_ext": "wav"}}))

    def test_stdin(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.provider(d, ["--stdin"], True).synthesize("hola ñandú", Path(d), "c0")
            self.assertEqual(out.suffix, ".wav")
            self.assertEqual(out.read_text(encoding="utf-8"), "AUDIO:hola ñandú:0.5000")

    def test_text_placeholder(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.provider(d, ["--text", "{text}"], False).synthesize("chau", Path(d), "c1")
            self.assertEqual(out.read_text(), "AUDIO:chau:0.5000")

    def test_errors(self):
        with tempfile.TemporaryDirectory() as d:
            bad = CommandProvider(parse_config({"tts": {"provider": "command"},
                                                "command": {"args": ["/no/existe/prog", "{output}"]}}))
            with self.assertRaisesRegex(TTSError, "No encuentro"):
                bad.synthesize("x", Path(d), "c0")
            fail = CommandProvider(parse_config({"tts": {"provider": "command"},
                                                 "command": {"args": [sys.executable, "-c", "import sys; sys.exit(3)"]}}))
            with self.assertRaisesRegex(TTSError, "error 3"):
                fail.synthesize("x", Path(d), "c0")
            nofile = CommandProvider(parse_config({"tts": {"provider": "command"},
                                                   "command": {"args": [sys.executable, "-c", "pass"]}}))
            with self.assertRaisesRegex(TTSError, "no generó"):
                nofile.synthesize("x", Path(d), "c0")


class EdgeTests(unittest.TestCase):
    def test_rate_string(self):
        self.assertEqual(EdgeProvider.rate_string(1.0), "+0%")
        self.assertEqual(EdgeProvider.rate_string(1.25), "+25%")
        self.assertEqual(EdgeProvider.rate_string(0.8), "-20%")
        self.assertEqual(EdgeProvider.rate_string(4.0), "+200%")
        self.assertEqual(EdgeProvider.rate_string(0.25), "-75%")

    @unittest.skipUnless(os.environ.get("ALTR_TEST_NETWORK"), "ALTR_TEST_NETWORK=1 para probar con internet")
    def test_real_synthesis(self):
        with tempfile.TemporaryDirectory() as d:
            out = make_provider(parse_config({"tts": {"speed": 1.2}})).synthesize("Hola, ¿qué tal?", Path(d), "c0")
            self.assertGreater(out.stat().st_size, 2000)


if __name__ == "__main__":
    unittest.main()
