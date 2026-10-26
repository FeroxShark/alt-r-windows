"""Duración y forma de onda aproximada de los trozos de audio (sólo biblioteca estándar).

La duración la necesita el overlay (barra de progreso y karaoke). Para wav se lee del
encabezado; para mp3 se lee el primer cuadro (y la etiqueta Xing/Info si hay, que trae la
cantidad exacta de cuadros). Si nada de eso sirve se estima con 48 kbps, que es lo que
genera Edge.
"""
from __future__ import annotations

import array
import wave
from pathlib import Path

DEFAULT_BYTES_PER_SEC = 6000.0  # 48 kbps (audio-24khz-48kbitrate-mono-mp3 de Edge)
ENV_HZ = 20                     # muestras de la envolvente por segundo de audio

_MPEG1 = {
    3: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
    2: [0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384],
    1: [0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448],
}
_MPEG2 = {
    3: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
    2: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
    1: [0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256],
}
_RATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}


def _mp3_header(b: bytes, i: int):
    """(kbps, sample_rate, samples_por_cuadro, mono, tiene_crc, mpeg1) del cuadro en b[i:], o None."""
    if i + 4 > len(b) or b[i] != 0xFF or (b[i + 1] & 0xE0) != 0xE0:
        return None
    ver = (b[i + 1] >> 3) & 3          # 3 = MPEG1, 2 = MPEG2, 0 = MPEG2.5, 1 = reservado
    layer = 4 - ((b[i + 1] >> 1) & 3)  # 1, 2 o 3 (0 = reservado -> 4)
    br_idx, sr_idx = b[i + 2] >> 4, (b[i + 2] >> 2) & 3
    if ver == 1 or layer == 4 or br_idx in (0, 15) or sr_idx == 3:
        return None
    table = (_MPEG1 if ver == 3 else _MPEG2)[layer]
    spf = 384 if layer == 1 else (1152 if ver == 3 or layer == 2 else 576)
    return (table[br_idx], _RATES[ver][sr_idx], spf, (b[i + 3] >> 6) == 3,
            (b[i + 1] & 1) == 0, ver == 3)


def mp3_seconds(path: Path) -> float | None:
    """Duración de un mp3, o None si no se reconoce."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            head = f.read(10)
            skip = 0
            if head[:3] == b"ID3" and len(head) == 10:  # etiqueta ID3v2: tamaño en 4 bytes de 7 bits
                skip = 10 + ((head[6] & 0x7F) << 21 | (head[7] & 0x7F) << 14
                             | (head[8] & 0x7F) << 7 | (head[9] & 0x7F))
            f.seek(skip)
            buf = f.read(8192)
    except OSError:
        return None
    for i in range(len(buf) - 4):
        h = _mp3_header(buf, i)
        if not h:
            continue
        kbps, sr, spf, mono, crc, mpeg1 = h
        side = (17 if mono else 32) if mpeg1 else (9 if mono else 17)
        tag = i + 4 + (2 if crc else 0) + side
        if buf[tag:tag + 4] in (b"Xing", b"Info") and len(buf) >= tag + 12 and buf[tag + 7] & 1:
            frames = int.from_bytes(buf[tag + 8:tag + 12], "big")
            if frames:
                return frames * spf / sr
        return max(0, size - skip - i) * 8 / (kbps * 1000)
    return None


def audio_duration(path: Path) -> float:
    """Segundos de audio de un wav o mp3 (estimado si no se puede leer)."""
    path = Path(path)
    try:
        with wave.open(str(path), "rb") as w:
            if w.getframerate():
                return w.getnframes() / w.getframerate()
    except (wave.Error, EOFError, OSError):
        pass
    secs = mp3_seconds(path)
    if secs is not None:
        return secs
    try:
        return path.stat().st_size / DEFAULT_BYTES_PER_SEC
    except OSError:
        return 0.0


# ------------------------------------------------------------------ envolvente
def _wav_envelope(path: Path, hz: int) -> list[float] | None:
    try:
        with wave.open(str(path), "rb") as w:
            width, nch, rate = w.getsampwidth(), w.getnchannels(), w.getframerate()
            raw = w.readframes(w.getnframes())
    except (wave.Error, EOFError, OSError):
        return None
    if width == 2:
        arr = array.array("h")
        arr.frombytes(raw[: len(raw) // 2 * 2])
        full = 32768.0
    elif width == 1:
        arr = array.array("h", [x - 128 for x in raw])  # wav de 8 bits: sin signo, centrado en 128
        full = 128.0
    else:
        return None
    if nch > 1:
        arr = arr[::nch]
    win = max(1, rate // hz)
    out = []
    for i in range(0, len(arr), win):
        seg = arr[i:i + win]
        out.append(max(max(seg), -min(seg)) / full)
    return out


def _energy(c: str) -> float:
    if c in "aeiouáéíóúüAEIOUÁÉÍÓÚÜ":
        return 1.0
    if c.isalnum():
        return 0.55
    if c == " ":
        return 0.12
    return 0.0  # puntuación: pausa


def _text_envelope(text: str, dur: float, hz: int) -> list[float]:
    """Aproximación para mp3 (no se decodifica): vocales fuertes, consonantes medias, pausas en
    espacios y puntuación, repartidas parejo a lo largo de la duración del trozo."""
    n = max(1, round(dur * hz))
    if not text:
        return [0.3] * n
    en = [_energy(c) for c in text]
    out = []
    for i in range(n):
        a = i * len(en) // n
        b = max(a + 1, (i + 1) * len(en) // n)
        seg = en[a:b]
        out.append(sum(seg) / len(seg))
    sm = out[:]
    for i in range(1, n - 1):
        sm[i] = 0.25 * out[i - 1] + 0.5 * out[i] + 0.25 * out[i + 1]
    return sm


def envelope(path: Path, text: str, dur: float, hz: int = ENV_HZ) -> list[float]:
    """Envolvente 0..1 del trozo a `hz` muestras por segundo: real si es wav, aproximada si no."""
    env = _wav_envelope(Path(path), hz) if str(path).lower().endswith(".wav") else None
    return env if env else _text_envelope(text, dur, hz)


def bin_peaks(envs: list[list[float] | None], n: int = 18) -> list[float]:
    """Resume las envolventes (en orden, None = sin generar) en `n` picos 0..1 a lo largo del
    tiempo, como el archivo de picos del overlay de Linux. [] si no hay nada."""
    flat: list[float] = []
    for e in envs:
        if e is None:
            break
        flat.extend(e)
    if not flat:
        return []
    out = []
    for b in range(n):
        a = b * len(flat) // n
        z = max(a + 1, (b + 1) * len(flat) // n)
        seg = flat[a:z]
        out.append(0.5 * (sum(seg) / len(seg)) + 0.5 * max(seg))
    top = max(out)
    if top <= 0:
        return [0.35] * n
    return [min(1.0, v / top) for v in out]
