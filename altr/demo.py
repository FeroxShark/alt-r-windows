"""`AltR --demo-overlay`: abre el overlay con una lectura de mentira (sin red ni parlantes) y
comprueba que se crea, muestra el texto, pausa, salta y se cierra. Sirve para verlo sin hablar
con Edge y para que el CI pruebe el .exe de verdad. Sale con 0 si todo anduvo, 1 si no.
"""
from __future__ import annotations

import math
import time
import wave
from pathlib import Path
from typing import Callable

from .config import Config, parse_config
from .player import SimBackend
from .reader import Reader

DEMO_TEXT = (
    "Así se ve AltR mientras lee. La palabra que suena se marca en verde y las que ya pasaron "
    "se apagan. Podés pausar con el botón de la izquierda, hacer clic en la onda para saltar a "
    "otro punto o tocar una palabra para empezar desde ahí. La cápsula no te roba el foco: seguís "
    "escribiendo donde estabas. Cuando termina, se va sola."
)


class DemoProvider:
    """Genera wav "de voz": un zumbido con el ritmo de las sílabas, a `cps` caracteres por segundo."""

    def __init__(self, cps: float = 22.0):
        self.cps = cps

    def synthesize(self, text: str, out_dir: Path, name: str) -> Path:
        rate = 16000
        n = int(rate * max(0.4, len(text) / self.cps))
        frames = bytearray()
        for i in range(n):
            t = i / rate
            syl = 0.5 + 0.5 * math.sin(2 * math.pi * 3.6 * t) ** 2   # sílabas
            word = 0.12 + 0.88 * abs(math.sin(2 * math.pi * 0.37 * t + len(text)))  # frases
            v = int(9000 * syl * word * math.sin(2 * math.pi * 170 * t))
            frames += v.to_bytes(2, "little", signed=True)
        path = Path(out_dir) / f"{name}.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(bytes(frames))
        return path


def run_demo(cfg: Config | None = None, screenshot: str | None = None,
             say: Callable[[str], None] = print, cps: float = 22.0) -> int:
    from .ui import OverlayController, ensure_qapp

    qapp = ensure_qapp()
    cfg = cfg or parse_config({})
    # la demo siempre muestra el overlay, aunque el config lo tenga apagado
    ov_cfg = cfg.overlay
    if not ov_cfg.enabled:
        ov_cfg = parse_config({"overlay": {"enabled": True}}).overlay

    problems: list[str] = []
    reader = Reader(cfg, SimBackend(), on_error=lambda m: problems.append(f"error del lector: {m}"),
                    provider=DemoProvider(cps))
    ov = OverlayController(reader, ov_cfg)

    def pump(cond: Callable[[], bool], timeout: float = 15.0) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            qapp.processEvents()
            if cond():
                return True
            time.sleep(0.01)
        qapp.processEvents()
        return cond()

    def check(label: str, ok: bool) -> bool:
        say(("ok   " if ok else "FALLA ") + label)
        if not ok:
            problems.append(label)
        return ok

    try:
        if not check("el overlay se crea (Overlay.qml carga)" + (f": {ov.error}" if ov.error else ""),
                     ov.created):
            return 1
        reader.speak(DEMO_TEXT)
        check("aparece con la lectura en curso",
              pump(lambda: ov.state().get("phase") == "playing" and ov.state().get("lecWords", 0) > 0))
        check("la ventana se muestra", ov.view.isVisible() and ov.shown_count >= 1)
        pump(lambda: ov.state().get("globalPos", 0) > 1.0, 6)
        img = ov.grab()
        opaque = 0
        if img is not None and not img.isNull():
            step = max(1, img.width() // 64)
            opaque = sum(1 for x in range(0, img.width(), step) for y in range(0, img.height(), step)
                         if img.pixelColor(x, y).alpha() > 40)
            if screenshot:
                img.save(screenshot)
                say(f"captura guardada en {screenshot}")
        check("la cápsula se dibuja (hay píxeles opacos)", opaque > 20)

        ov.bridge.togglePause()
        check("pausa", pump(lambda: ov.state().get("phase") == "paused", 3))
        ov.bridge.togglePause()
        check("sigue", pump(lambda: ov.state().get("phase") == "playing", 3))

        check("termina de generar todo", pump(lambda: bool(ov.state().get("complete")), 10))
        total = ov.state().get("totalDur", 0) or 0
        target = total * 0.7
        ov.bridge.seek(target)
        check("salta a otro punto", pump(lambda: ov.state().get("globalPos", 0) >= target - 0.6, 4))

        ov.bridge.stop()
        check("se cierra al cortar", pump(lambda: not ov.state().get("uiActive", True), 4))
        check("la ventana se oculta", pump(lambda: not ov.view.isVisible(), 2))
    finally:
        reader.stop()
        ov.timer.stop()
        if ov.view is not None:
            ov.view.hide()
    if problems:
        say("Demo con fallas: " + "; ".join(problems))
        return 1
    say("Demo OK")
    return 0
