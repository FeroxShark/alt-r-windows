import struct
import tempfile
import unittest
import wave
from pathlib import Path

from altr.audio import audio_duration, bin_peaks, envelope, mp3_seconds


def write_wav(path, secs, rate=8000, amp=8000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", amp if (i // 40) % 2 else -amp) for i in range(int(secs * rate))))


def fake_mp3(frames, with_xing=True):
    # MPEG2 layer3, 24 kHz, mono; con etiqueta Xing que declara `frames` cuadros
    hdr = bytes([0xFF, 0xF3, 0x84, 0xC0])  # br idx 8 (64k MPEG2), sr idx 1 (24k), mono
    body = bytearray(hdr + bytes(417 - 4))
    if with_xing:
        tag = 4 + 9  # MPEG2 mono, sin CRC
        body[tag:tag + 4] = b"Xing"
        body[tag + 4:tag + 8] = (1).to_bytes(4, "big")
        body[tag + 8:tag + 12] = frames.to_bytes(4, "big")
    return bytes(body)


class AudioTests(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())

    def test_wav_duration_and_envelope(self):
        p = self.d / "a.wav"
        write_wav(p, 1.5)
        self.assertAlmostEqual(audio_duration(p), 1.5, places=2)
        env = envelope(p, "hola", 1.5)
        self.assertAlmostEqual(len(env), 30, delta=2)
        self.assertGreater(max(env), 0.2)

    def test_mp3_xing_duration(self):
        p = self.d / "a.mp3"
        p.write_bytes(fake_mp3(100))
        # MPEG2 layer3: 576 muestras por cuadro a 24 kHz
        self.assertAlmostEqual(mp3_seconds(p), 100 * 576 / 24000, places=3)

    def test_unknown_file_falls_back_to_size(self):
        p = self.d / "x.mp3"
        p.write_bytes(b"\x00" * 12000)
        self.assertAlmostEqual(audio_duration(p), 2.0)

    def test_text_envelope_for_mp3(self):
        p = self.d / "t.mp3"
        p.write_bytes(b"\x00" * 6000)
        env = envelope(p, "Hola, ¿cómo estás?", 1.0)
        self.assertEqual(len(env), 20)
        self.assertTrue(all(0 <= v <= 1 for v in env))

    def test_bin_peaks(self):
        self.assertEqual(bin_peaks([None]), [])
        peaks = bin_peaks([[0.1] * 40, [0.9] * 40, None, [0.5] * 40])
        self.assertEqual(len(peaks), 18)
        self.assertEqual(max(peaks), 1.0)


if __name__ == "__main__":
    unittest.main()
