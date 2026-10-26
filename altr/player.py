"""Reproducción. En Windows se usa MCI (win.py); en otros sistemas, un reproductor
externo (mpv/ffplay), sólo para desarrollar y probar fuera de Windows."""
from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path


class ExternalBackend:
    """Backend de desarrollo: delega en mpv o ffplay si están instalados."""

    def __init__(self):
        self.cmd = None
        if shutil.which("mpv"):
            self.cmd = ["mpv", "--no-video", "--really-quiet", "--volume={vol}"]
        elif shutil.which("ffplay"):
            self.cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-volume", "{vol}"]

    @property
    def available(self) -> bool:
        return self.cmd is not None

    def play(self, path: Path, volume: int, cancel: threading.Event) -> None:
        if not self.cmd:
            raise RuntimeError("No hay mpv ni ffplay para reproducir.")
        argv = [a.format(vol=volume) for a in self.cmd] + [str(path)]
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL)
        try:
            while proc.poll() is None:
                if cancel.wait(0.05):
                    proc.terminate()
                    break
        finally:
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()


class NullBackend:
    """No reproduce nada (usado por --say --out y en los tests)."""

    def play(self, path: Path, volume: int, cancel: threading.Event) -> None:
        pass


def default_backend():
    import os

    if os.name == "nt":
        from .win import MciBackend
        return MciBackend()
    return ExternalBackend()
