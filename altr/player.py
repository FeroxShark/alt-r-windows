"""Reproducción. En Windows se usa MCI (win.py); en otros sistemas, un reproductor
externo (mpv/ffplay), sólo para desarrollar y probar fuera de Windows.

Todos los backends cumplen `play(path, volume, cancel, ctl=None, start=0.0)`: reproducen UN
trozo y vuelven cuando terminó, cuando se activó `cancel` o cuando `ctl.interrupt` pide
cortar este trozo. `ctl` (PlayControl) es el mando que usa el lector para pausar y saltar, y
donde el backend deja la posición.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path

from .audio import audio_duration


class PlayControl:
    """Mando compartido entre el lector y el backend: pausa, salto y posición del trozo actual."""

    def __init__(self):
        self.paused = False
        self.interrupt = threading.Event()   # el lector pide cortar ESTE trozo (salto a otro)
        self.position = 0.0                  # segundos dentro del trozo que suena
        self.length: float | None = None     # duración real del trozo, si el backend la sabe
        self._seek: float | None = None
        self._lock = threading.Lock()

    def begin(self, start: float = 0.0) -> None:
        """El lector arranca un trozo nuevo."""
        with self._lock:
            self._seek = None
        self.interrupt.clear()
        self.position = start
        self.length = None

    def seek(self, secs: float) -> None:
        with self._lock:
            self._seek = max(0.0, secs)
        self.position = max(0.0, secs)

    def take_seek(self) -> float | None:
        with self._lock:
            s, self._seek = self._seek, None
        return s


class ExternalBackend:
    """Backend de desarrollo: delega en mpv o ffplay si están instalados."""

    def __init__(self):
        self.cmd = None
        if shutil.which("mpv"):
            self.cmd = ["mpv", "--no-video", "--really-quiet", "--volume={vol}", "--start={start}"]
        elif shutil.which("ffplay"):
            self.cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-volume", "{vol}",
                        "-ss", "{start}"]

    @property
    def available(self) -> bool:
        return self.cmd is not None

    def _spawn(self, path: Path, volume: int, start: float):
        argv = [a.format(vol=volume, start=f"{start:.2f}") for a in self.cmd] + [str(path)]
        return subprocess.Popen(argv, stdin=subprocess.DEVNULL)

    def play(self, path: Path, volume: int, cancel: threading.Event,
             ctl: PlayControl | None = None, start: float = 0.0) -> None:
        if not self.cmd:
            raise RuntimeError("No hay mpv ni ffplay para reproducir.")
        ctl = ctl or PlayControl()
        ctl.length = audio_duration(path)
        pos, t0 = start, time.monotonic()
        proc = self._spawn(path, volume, pos)
        stopped = False  # SIGSTOP enviado
        try:
            while proc.poll() is None:
                if cancel.wait(0.03) or ctl.interrupt.is_set():
                    break
                now = time.monotonic()
                s = ctl.take_seek()
                if s is not None:
                    proc.terminate()
                    proc.wait(timeout=2)
                    pos, t0, stopped = s, now, False
                    proc = self._spawn(path, volume, pos)
                    if ctl.paused:
                        os.kill(proc.pid, signal.SIGSTOP)
                        stopped = True
                elif ctl.paused != stopped:
                    os.kill(proc.pid, signal.SIGSTOP if ctl.paused else signal.SIGCONT)
                    stopped = ctl.paused
                    pos, t0 = ctl.position, now
                elif not stopped:
                    ctl.position = pos + (now - t0)
        finally:
            if proc.poll() is None:
                if stopped:
                    os.kill(proc.pid, signal.SIGCONT)
                proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()


class NullBackend:
    """No reproduce nada (usado por --say --out y en los tests)."""

    def play(self, path: Path, volume: int, cancel: threading.Event,
             ctl: PlayControl | None = None, start: float = 0.0) -> None:
        pass


class SimBackend:
    """Reproduce "en silencio" a tiempo real: respeta pausa, salto y corte. Para --demo-overlay
    y los tests de la interfaz (sin placa de sonido)."""

    def play(self, path: Path, volume: int, cancel: threading.Event,
             ctl: PlayControl | None = None, start: float = 0.0) -> None:
        ctl = ctl or PlayControl()
        dur = audio_duration(path)
        ctl.length = dur
        pos, last = start, time.monotonic()
        while pos < dur:
            if cancel.wait(0.02) or ctl.interrupt.is_set():
                return
            now = time.monotonic()
            s = ctl.take_seek()
            if s is not None:
                pos = min(s, dur)
            elif not ctl.paused:
                pos += now - last
            last = now
            ctl.position = min(pos, dur)


def default_backend():
    if os.name == "nt":
        from .win import MciBackend
        return MciBackend()
    return ExternalBackend()
