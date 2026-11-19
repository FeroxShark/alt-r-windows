"""Banco de sincronía del karaoke: ¿la palabra resaltada es la que se está oyendo?

Un "hablante" falso genera audio cuya verdad por palabra conoce al milisegundo (no sale de `altr.marks`: el
modelo de duraciones es otro, con ritmo irregular, pausas en la puntuación y siglas que se dicen deletreadas).
El lector real (`Reader`) lo reproduce con `SimBackend` a reloj real y el overlay real (Overlay.qml, Qt offscreen)
resalta palabras. Cada 20 ms se compara la palabra resaltada con lo que suena:

    error = cuánto antes (+) o después (-) del audio está el resaltado, en segundos

Medido en inicio, medio, final, tras pausa y tras salto (adelante y atrás). Sin Windows ni placa de sonido.
"""
from __future__ import annotations

import os
import random
import re
import threading
import time
import wave
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from altr.config import parse_config
from altr.player import SimBackend

TEXTO = """No se descargó ninguna imagen de la galería. El navegador bloquea leer las direcciones de las fotos del sitio, y ese bloqueo no lo rodeé.

Para bajarlas en calidad original a mano, desde tu navegador:

Abrí la publicación y apretá F12.
Andá a la pestaña Network, elegí el filtro Img y recargá con F5.
Hacé clic en la columna Size para ordenar por tamaño. La foto de la publicación es de las más pesadas.
Clic derecho sobre esa fila, Open in new tab, y guardala con Ctrl+S.

Ya hay 8 fotos del mapa en ￼
prospeccion/fotos/galeria-centro/para-design/
, así que del sitio te alcanza con 4 o 5: el local por dentro, el sillón y el logo."""

_VOC = re.compile(r"[aeiouáéíóúü]+")


def _silabas(w: str) -> int:
    return max(1, len(_VOC.findall(w.lower())))


class Hablante:
    """Proveedor falso con verdad conocida. `formato` = "wav" | "mp3"; `con_marcas` = da marcas del modelo
    (como Edge) además del audio. `escala` acelera el habla (más palabras por segundo = prueba más dura)."""

    def __init__(self, formato="wav", con_marcas=False, escala=0.55, seed=11, jitter_marcas=0.0):
        self.formato, self.escala, self.seed = formato, escala, seed
        self.jitter = jitter_marcas
        self.verdad: dict[str, list[list[float]]] = {}   # nombre del archivo -> [[ini, fin]] por palabra
        self.dur: dict[str, float] = {}
        if con_marcas:
            self.synthesize_marked = self._marked
        self.rng = random.Random(seed)

    # -- el habla --------------------------------------------------------------------------
    def _hablar(self, text: str):
        marks, t = [], 0.14
        for tok in text.split():
            alnum = re.sub(r"[\W_]", "", tok)
            if not alnum:
                d = 0.0                                              # símbolo mudo (￼)
            elif re.search(r"\d", tok) or tok.rstrip(".,;:").isupper() or "+" in tok:
                d = 0.30 * (1 + len(re.findall(r"[A-Za-z]+|\d+", tok)))   # «F5» = efe cinco
            elif "/" in tok:
                d = 0.16 * (1 + tok.count("/")) * 2
            else:
                d = (0.06 + 0.075 * _silabas(alnum) + 0.01 * len(alnum)) * self.rng.uniform(0.7, 1.35)
            d *= self.escala
            marks.append([round(t, 4), round(t + d, 4)])
            t += d + 0.012 * self.escala
            if tok[-1:] in ",;":
                t += 0.22
            elif tok[-1:] in ".!?:":
                t += 0.42
        return marks, t + 0.12

    def _wav(self, path: Path, marks, total):
        sr = 16000
        n = int(sr * total)
        buf = bytearray(2 * n)
        import math
        for (a, b) in marks:
            i0, i1 = int(a * sr), int(b * sr)
            for i in range(i0, min(n, i1)):
                t = i / sr
                fade = min(1.0, (i - i0) / 240, (i1 - i) / 240)
                env = (0.55 + 0.45 * math.sin(2 * math.pi * 4.2 * t) ** 2) * fade
                v = int(9000 * env * math.sin(2 * math.pi * 160 * t))
                buf[2 * i:2 * i + 2] = v.to_bytes(2, "little", signed=True)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(bytes(buf))

    @staticmethod
    def _mp3(path: Path, marks, total):
        """mp3 CBR de 48 kbps / 24 kHz sin sonido real, pero con la información lateral de un mp3 de verdad:
        `big_values` = 0 en el silencio y > 0 donde se habla (es lo que lee `altr.marks`)."""
        frames = max(1, int(total / 0.024 + 0.999))
        out = bytearray()
        for k in range(frames):
            a, b = k * 0.024, (k + 1) * 0.024
            habla = any(m0 < b and m1 > a and m1 > m0 for m0, m1 in marks)
            # MPEG-2 mono: main_data_begin(8) private(1) part2_3_length(12) big_values(9) ...
            lado = (900 if habla else 0) << (72 - 9 - 12) | (120 if habla else 0) << (72 - 9 - 12 - 9)
            out += bytes([0xFF, 0xF3, 0x64, 0xC0]) + lado.to_bytes(9, "big") + bytes(131)
        path.write_bytes(bytes(out))
        return frames * 0.024

    def synthesize(self, text, out_dir, name):
        marks, total = self._hablar(text)
        ext = "mp3" if self.formato == "mp3" else "wav"
        path = Path(out_dir) / f"{name}.{ext}"
        if ext == "wav":
            self._wav(path, marks, total)
        else:
            total = self._mp3(path, marks, total)
        self.verdad[path.name] = marks
        self.dur[path.name] = total
        return path

    def _marked(self, text, out_dir, name):
        path = self.synthesize(text, out_dir, name)
        j = self.jitter
        marks = [[round(max(0.0, a + random.uniform(-j, j)), 3), round(max(0.0, b + random.uniform(-j, j)), 3)]
                 for a, b in self.verdad[path.name]]
        return path, marks


class BackendVerdad(SimBackend):
    """SimBackend que anota qué archivo suena y dónde, para medir contra la verdad."""

    def __init__(self):
        self.nombre: str | None = None
        self.ctl = None
        self.sonando = False
        self.orden: list[str] = []

    def play(self, path, volume, cancel, ctl=None, start=0.0):
        self.nombre, self.ctl = Path(path).name, ctl
        if self.nombre not in self.orden:
            self.orden.append(self.nombre)
        self.sonando = True
        try:
            super().play(path, volume, cancel, ctl=ctl, start=start)
        finally:
            self.sonando = False


def _cuantil(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else 0.0


def medir(qapp, hablante: Hablante, texto: str = TEXTO, log=print) -> dict:
    """Corre una lectura con el overlay real y devuelve {fase: [errores en ms]} más `resumen`."""
    import tempfile
    from altr import ui
    from altr.reader import Reader

    cfg = parse_config({})
    backend = BackendVerdad()
    reader = Reader(cfg, backend, provider=hablante)
    tmp = tempfile.TemporaryDirectory()
    ov = ui.OverlayController(reader, cfg.overlay, pos_path=Path(tmp.name) / "pos.json")
    try:
        errores: dict[str, list[float]] = {}
        fase = ["inicio"]
        gracia_hasta = [0.0]

        def pump(seg):
            fin = time.monotonic() + seg
            while time.monotonic() < fin:
                qapp.processEvents()
                muestrear()
                time.sleep(0.02)

        def global_verdad():
            """(tiempo global oído, [(ini, fin)] globales de todas las palabras) según el audio de verdad."""
            nombres = sorted(hablante.verdad)
            if not backend.sonando or backend.nombre is None or backend.ctl is None:
                return None
            k = nombres.index(backend.nombre)
            base = sum(hablante.dur[n] for n in nombres[:k])
            return base + backend.ctl.position, k, nombres

        def muestrear():
            if time.monotonic() < gracia_hasta[0]:
                return
            g = global_verdad()
            st = ov.state()
            if g is None or st.get("phase") not in ("playing", "paused"):
                return
            oido, k, nombres = g
            # palabras globales (en el orden de los trozos) con su inicio global
            ini, base = [], 0.0
            for n in nombres:
                if n not in hablante.verdad:
                    continue
                for a, b in hablante.verdad[n]:
                    ini.append((base + a, base + b))
                base += hablante.dur[n]
            # la verdad sólo se conoce de los trozos ya generados: las palabras siguientes todavía no existen
            if oido < ini[0][0] - 1e-6:
                return
            w = st.get("curWord", -1)
            if w < 0 or w >= len(ini):
                return
            a = ini[w][0]
            b = ini[w + 1][0] if w + 1 < len(ini) else float("inf")
            err = (a - oido) if oido < a else (-(oido - b) if oido >= b else 0.0)
            errores.setdefault(fase[0], []).append(err * 1000)

        def esperar_audio():
            fin = time.monotonic() + 10
            while time.monotonic() < fin:
                qapp.processEvents()
                if ov.state().get("phase") == "playing" and backend.sonando:
                    return True
                time.sleep(0.01)
            return False

        reader.speak(texto)
        if not esperar_audio():
            raise RuntimeError("no arrancó el audio")
        pump(1.2)                                   # inicio

        fase[0] = "medio"
        fin = time.monotonic() + 60
        while not ov.state().get("complete") and time.monotonic() < fin:
            pump(0.1)
        total = ov.state()["totalDur"]
        while ov.state()["globalPos"] < total * 0.45 and time.monotonic() < fin:
            pump(0.05)
        pump(1.5)

        fase[0] = "pausa"
        ov.bridge.togglePause()
        gracia_hasta[0] = time.monotonic() + 0.4
        pump(0.5)
        pump(1.0)
        fase[0] = "tras pausa"
        ov.bridge.togglePause()
        gracia_hasta[0] = time.monotonic() + 0.4
        pump(1.5)

        def saltar(destino, nombre):
            fase[0] = nombre
            reader.seek(destino)
            gracia_hasta[0] = time.monotonic() + 0.4
            pump(1.8)

        saltar(total * 0.2, "tras salto atrás")
        saltar(total * 0.62, "tras salto adelante")
        saltar(total * 0.62 - 0.45, "tras salto atrás corto")

        fase[0] = "final"
        fin = time.monotonic() + total + 10
        while ov.state()["globalPos"] < total - 2.5 and time.monotonic() < fin:
            pump(0.05)
        pump(1.8)
    finally:
        reader.stop()
        ov.timer.stop()
        if ov.view is not None:
            ov.view.hide()
        tmp.cleanup()

    out = {}
    for f, xs in errores.items():
        absx = [abs(x) for x in xs]
        out[f] = {"n": len(xs), "max": max(absx), "p90": _cuantil(absx, 0.9),
                  "adelante": max([x for x in xs if x > 0] or [0.0]),
                  "atras": -min([x for x in xs if x < 0] or [0.0])}
    out["_todo"] = _resumen(errores)
    return out


def _resumen(errores):
    todo = [abs(x) for xs in errores.values() for x in xs]
    # deriva: el error de la última tercera parte de las muestras de lectura continua contra la primera
    cont = [abs(x) for f in ("inicio", "medio", "final") for x in errores.get(f, [])]
    ter = max(1, len(cont) // 3)
    return {"n": len(todo), "max": max(todo or [0.0]), "p90": _cuantil(todo, 0.9),
            "deriva_ms": (sum(cont[-ter:]) / ter) - (sum(cont[:ter]) / ter) if cont else 0.0}


def informe(nombre, res, log=print):
    log(f"--- {nombre}")
    for f, m in res.items():
        if f.startswith("_"):
            continue
        log(f"  {f:<22} n={m['n']:<4} máx {m['max']:6.0f} ms  p90 {m['p90']:6.0f} ms  "
            f"(adelantado {m['adelante']:.0f}, atrasado {m['atras']:.0f})")
    t = res["_todo"]
    log(f"  TOTAL  máx {t['max']:.0f} ms  p90 {t['p90']:.0f} ms  deriva {t['deriva_ms']:+.0f} ms")
