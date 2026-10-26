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
        self.starts = []
        self.seeks = 0
        self.play_time = play_time

    def play(self, path, volume, cancel, ctl=None, start=0.0):
        self.played.append((Path(path).read_bytes().decode(), volume))
        self.starts.append(start)
        end = time.monotonic() + self.play_time
        while time.monotonic() < end:
            if cancel.wait(0.01) or (ctl and ctl.interrupt.is_set()):
                return
            if ctl and ctl.take_seek() is not None:
                self.seeks += 1


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
            def play(self, *a, **kw):
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

    def test_snapshot_phases_and_texts(self):
        r, states, _ = self.make(FakeProvider(), FakeBackend(play_time=5))
        self.assertIsNone(r.snapshot())
        r.speak(LONG)
        self.assertTrue(wait_for(lambda: (r.snapshot() or {}).get("phase") == "playing"))
        snap = r.snapshot()
        self.assertEqual(" ".join(snap["texts"]).split(), LONG.split())
        self.assertEqual(len(snap["durs"]), len(snap["texts"]))
        self.assertTrue(snap["durs"][0] > 0)
        r.stop()
        self.assertTrue(wait_for(lambda: r.snapshot()["phase"] == "done"))

    def test_snapshot_error_phase(self):
        r, states, errors = self.make(FakeProvider(fail_on=0), FakeBackend())
        r.speak("Hola.")
        self.assertTrue(wait_for(lambda: (r.snapshot() or {}).get("phase") == "error"))
        self.assertEqual(r.snapshot()["error"], "boom")

    def test_pause_toggles_phase(self):
        r, *_ = self.make(FakeProvider(), FakeBackend(play_time=5))
        r.speak(LONG)
        self.assertTrue(wait_for(lambda: (r.snapshot() or {}).get("phase") == "playing"))
        r.toggle_pause()
        self.assertEqual(r.snapshot()["phase"], "paused")
        r.toggle_pause()
        self.assertEqual(r.snapshot()["phase"], "playing")
        r.stop()

    def test_seek_within_chunk_and_to_other_chunk(self):
        class Big(FakeProvider):  # ~2 s por trozo (6000 B/s) para que haya dónde saltar
            def synthesize(self, text, out_dir, name):
                p = super().synthesize(text, out_dir, name)
                p.write_bytes(text.encode().ljust(12000, b" "))
                return p

        back = FakeBackend(play_time=5)
        r, *_ = self.make(Big(), back)
        r.speak(LONG)
        self.assertTrue(wait_for(lambda: (r.snapshot() or {}).get("phase") == "playing"))
        self.assertTrue(wait_for(lambda: sum(d is not None for d in r.snapshot()["durs"]) >= 3))
        d0 = r.snapshot()["durs"][0]
        r.seek(d0 / 2)
        self.assertTrue(wait_for(lambda: back.seeks == 1))
        n = len(back.played)
        r.seek(d0 + 0.1)  # cae en el trozo 1
        self.assertTrue(wait_for(lambda: len(back.played) == n + 1))
        self.assertAlmostEqual(back.starts[-1], 0.1, delta=0.05)
        self.assertAlmostEqual(r.snapshot()["pos"], d0 + 0.1, delta=0.05)
        self.assertEqual(r.snapshot()["phase"], "playing")  # no parpadea a "stalled" al saltar
        r.stop()


if __name__ == "__main__":
    unittest.main()
