"""Dónde va la cápsula del overlay: lógica pura (sin Qt, se prueba en cualquier sistema).

Port de lo que el overlay de Linux (tts-status/shell.qml) ganó el 2026-11-16:
- por defecto arriba, centrada, DEBAJO de la barra de tareas si ésta está arriba: se parte del área
  de trabajo del monitor (en Windows es SPI_GETWORKAREA; Qt la da como `availableGeometry()`);
- se arrastra (manija o cuerpo, con umbral) y la posición queda por monitor;
- doble clic en la manija vuelve al lugar por defecto.

Todo son rectángulos (x, y, ancho, alto) en píxeles de pantalla. La posición guardada son
fracciones de la pantalla ENTERA (centro horizontal / arriba de la ventana), igual que el `pos.json`
de Linux: sobrevive a un cambio de resolución.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("altr")

HUECO = 16            # aire entre el borde del área de trabajo y la cápsula
DRAG_THRESHOLD = 6    # px: menos que esto desde el cuerpo sigue siendo un clic (palabras del karaoke)
SNAP_CENTER = 14      # px: al arrastrar se engancha al centro horizontal del área de trabajo


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:      # último píxel (como QRect.right())
        return self.x + self.w - 1

    @property
    def bottom(self) -> int:
        return self.y + self.h - 1


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v)) if hi >= lo else lo


def clamp_window(x: float, y: float, w: int, h: int, work: Rect) -> tuple[int, int]:
    """Deja la ventana (w x h) entera dentro del área de trabajo."""
    return (round(clamp(x, work.x, work.x + work.w - w)),
            round(clamp(y, work.y, work.y + work.h - h)))


def anchor_xy(position: str, work: Rect, w: int, h: int) -> tuple[int, int]:
    """Lugar por defecto según `[overlay] position` ('top-center', 'bottom-right'...): arriba, la
    ventana pegada al borde del área de trabajo (la cápsula queda HUECO más abajo, ya dentro de la
    ventana); abajo, pegada al borde de abajo."""
    if position.endswith("left"):
        x = work.x + HUECO
    elif position.endswith("right"):
        x = work.x + work.w - w - HUECO
    else:
        x = work.x + (work.w - w) // 2
    y = work.y if position.startswith("top") else work.y + work.h - h
    return x, y


def pin_from_window(x: float, y: float, w: int, screen: Rect) -> dict:
    """Posición de la ventana -> fracciones de la pantalla (centro, arriba)."""
    return {"x": round((x + w / 2 - screen.x) / screen.w, 5),
            "y": round((y - screen.y) / screen.h, 5)}


def window_from_pin(pin: dict, w: int, h: int, screen: Rect, work: Rect) -> tuple[int, int]:
    """Fracciones guardadas -> esquina de la ventana, ya metida en el área de trabajo (si la
    barra de tareas cambió de lugar o la resolución es otra, no queda fuera ni bajo la barra)."""
    cx = screen.x + float(pin["x"]) * screen.w
    top = screen.y + float(pin["y"]) * screen.h
    return clamp_window(cx - w / 2, top, w, h, work)


def valid_pin(pin) -> bool:
    try:
        return (isinstance(pin, dict) and 0.0 <= float(pin["x"]) <= 1.0 and 0.0 <= float(pin["y"]) <= 1.0)
    except (KeyError, TypeError, ValueError):
        return False


def exceeds_threshold(dx: float, dy: float, threshold: float = DRAG_THRESHOLD) -> bool:
    return dx * dx + dy * dy > threshold * threshold


class Drag:
    """Un arrastre en curso: recuerda dónde agarraste la ventana y la sigue al cursor.
    Las coordenadas del cursor son GLOBALES (de pantalla): como la ventana se mueve con el cursor,
    las locales de QML no sirven para esto."""

    def __init__(self, cursor: tuple[float, float], win: tuple[int, int]):
        self.off = (cursor[0] - win[0], cursor[1] - win[1])
        self.pos = win
        self.moved = False

    def move(self, cursor: tuple[float, float], w: int, h: int, work: Rect) -> tuple[int, int]:
        x = cursor[0] - self.off[0]
        if abs(x + w / 2 - (work.x + work.w / 2)) < SNAP_CENTER:     # se engancha al centro
            x = work.x + (work.w - w) / 2
        pos = clamp_window(x, cursor[1] - self.off[1], w, h, work)
        if pos != self.pos:
            self.moved = True
        self.pos = pos
        return pos


class PosStore:
    """`pos.json`: {"<monitor>": {"x": fracción, "y": fracción}}. Lee con tolerancia (un archivo
    roto = sin posiciones guardadas) y escribe atómico (tmp + replace)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.data: dict = {}
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        self.data = {k: v for k, v in raw.items() if valid_pin(v)} if isinstance(raw, dict) else {}

    def get(self, monitor: str) -> dict | None:
        return self.data.get(monitor)

    def set(self, monitor: str, pin: dict) -> None:
        self.data[monitor] = {"x": pin["x"], "y": pin["y"]}
        self._save()

    def clear(self, monitor: str) -> bool:
        had = self.data.pop(monitor, None) is not None
        if had:
            self._save()
        return had

    def clear_all(self) -> None:
        if self.data:
            self.data = {}
            self._save()

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps(self.data, indent=1) + "\n", encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            log.warning("no pude guardar la posición del overlay en %s", self.path, exc_info=True)
