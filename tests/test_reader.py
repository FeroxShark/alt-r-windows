import threading
import time
import unittest
from pathlib import Path

from altr.config import parse_config
from altr.providers import TTSError
from altr.reader import Reader


class FakeProvider:
    def __init__(self, fail_on=None, delay=0.0):
        self.calls = []
        self.fail_on = fail_on
        self.delay = delay

    def synthesize(self, text, out_dir, name):
        time.sleep(self.delay)
        self.calls.append(text)
        if self.fail_on is not None and len(self.calls) - 1 == self.fail_on:
            raise TTSError("boom")
        p = Path(out_dir) / f"{name}.mp3"
        p.write_bytes(text.encode())
        return p


class FakeBackend:
    def __init__(self, play_time=0.0):
        self.played = []
        self.play_time = play_time

    def play(self, path, volume, cancel):
        self.played.append((Path(path).read_bytes().decode(), volume))
        cancel.wait(self.play_time)


def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


LONG = " ".join(f"Frase número {i} para leer en voz alta y ocupar lugar." for i in range(12))


class ReaderTests(unittest.TestCase):
    def make(self, provider, backend, **kw):
        states, errors = [], []
        r = Reader(parse_config({"tts": {"volume": 70}}), backend, on_error=errors.append,
                   on_state=states.append, provider=provider, **kw)
        return r, states, errors

    def test_plays_all_chunks_in_order_and_reports_state(self):
        prov, back = FakeProvider(), FakeBackend()
        r, states, errors = self.make(prov, back)
        self.assertTrue(r.speak(LONG))
        self.assertTrue(wait_for(lambda: states == [True, False]))
        self.assertEqual(" ".join(t for t, _ in back.played).split(), LONG.split())
        self.assertTrue(all(v == 70 for _, v in back.played))
        self.assertEqual(errors, [])
        self.assertFalse(r.speaking)

    def test_nothing_to_read(self):
        r, states, _ = self.make(FakeProvider(), FakeBackend())
        self.assertFalse(r.speak("   \n"))
        self.assertEqual(states, [])

    def test_stop_cuts_playback(self):
        prov, back = FakeProvider(), FakeBackend(play_time=5)
        r, states, _ = self.make(prov, back)
        r.speak(LONG)
        self.assertTrue(wait_for(lambda: len(back.played) == 1))
        t0 = time.monotonic()
        r.stop()
        self.assertTrue(wait_for(lambda: states[-1:] == [False]))
        self.assertLess(time.monotonic() - t0, 1.0)
        self.assertEqual(len(back.played), 1)

    def test_new_speak_replaces_old(self):
        prov, back = FakeProvider(), FakeBackend(play_time=5)
        r, states, _ = self.make(prov, back)
        r.speak(LONG)
        self.assertTrue(wait_for(lambda: len(back.played) == 1))
        back.play_time = 0
        r.speak("Texto nuevo.")
        self.assertTrue(wait_for(lambda: ("Texto nuevo.", 70) in back.played))
        self.assertTrue(wait_for(lambda: not r.speaking))
        self.assertEqual(states[-1], False)

    def test_provider_error_reported_once_and_stops(self):
        prov, back = FakeProvider(fail_on=1), FakeBackend()
        r, states, errors = self.make(prov, back)
        r.speak(LONG)
        self.assertTrue(wait_for(lambda: states[-1:] == [False]))
        self.assertEqual(errors, ["boom"])
        self.assertEqual(len(prov.calls), 2)

    def test_backend_error_reported(self):
        class Bad:
            def play(self, *a):
                raise RuntimeError("sin audio")

        r, states, errors = self.make(FakeProvider(), Bad())
        r.speak("Hola.")
        self.assertTrue(wait_for(lambda: states[-1:] == [False]))
        self.assertIn("sin audio", errors[0])

    def test_tempdir_cleaned(self):
        dirs = []

        class Rec(FakeProvider):
            def synthesize(self, text, out_dir, name):
                dirs.append(Path(out_dir))
                return super().synthesize(text, out_dir, name)

        r, states, _ = self.make(Rec(), FakeBackend())
        r.speak("Hola.")
        self.assertTrue(wait_for(lambda: states == [True, False]))
        self.assertTrue(dirs and wait_for(lambda: not dirs[0].exists()))


if __name__ == "__main__":
    unittest.main()
