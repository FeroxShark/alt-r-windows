"""Prueba MCI real (sólo Windows) sobre un wav corto: abrir, play, position, pause, seek, close.

Mide el hueco al abrir un trozo (open + play) y lo imprime. Salidas:
  0 = MCI anduvo y las posiciones son coherentes, o MCI-NO-DISPONIBLE (no es Windows o el runner no
      tiene placa de audio: se avisa y la prueba de sincronía usa SimBackend)
  1 = MCI abrió el audio pero dio posiciones incoherentes
"""
import math
import os
import sys
import tempfile
import time
import wave


def wav(path, secs=3.0, sr=16000):
    n = int(sr * secs)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"".join(int(6000 * math.sin(2 * math.pi * 330 * i / sr)).to_bytes(2, "little", signed=True)
                               for i in range(n)))


def main() -> int:
    if os.name != "nt":
        print("MCI-NO-DISPONIBLE: no es Windows; se usa SimBackend")
        return 0
    from altr.win import _mci, _mci_error

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "probe.wav")
        wav(path)
        t0 = time.monotonic()
        err, _ = _mci(f'open "{path}" alias probe')
        if err:
            print(f"MCI-NO-DISPONIBLE: open falló ({_mci_error(err)}); se usa SimBackend")
            return 0
        try:
            _mci("set probe time format milliseconds")
            err, _ = _mci("play probe")
            hueco = time.monotonic() - t0
            if err:
                print(f"MCI-NO-DISPONIBLE: play falló ({_mci_error(err)}); se usa SimBackend")
                return 0
            print(f"MCI hueco open+play: {hueco * 1000:.0f} ms")

            def pos():
                e, v = _mci("status probe position")
                return int(v) if not e and v.isdigit() else None

            _, length = _mci("status probe length")
            print(f"MCI length: {length} ms (esperado 3000)")
            time.sleep(0.6)
            p1 = pos()
            _mci("pause probe")
            time.sleep(0.1)
            pa = pos()
            time.sleep(0.5)
            pb = pos()
            _mci("play probe from 2000")
            time.sleep(0.4)
            p2 = pos()
            print(f"MCI posiciones: tras 0,6 s={p1} ms, pausa={pa}/{pb} ms, tras seek a 2000 y 0,4 s={p2} ms")
            problemas = []
            if p1 is None or not 300 <= p1 <= 1200:
                problemas.append(f"posición tras 0,6 s fuera de rango ({p1})")
            if pa is None or pb is None or abs(pb - pa) > 60:
                problemas.append(f"la posición se movió en pausa ({pa} -> {pb})")
            if p2 is None or not 2200 <= p2 <= 2900:
                problemas.append(f"posición tras seek fuera de rango ({p2})")
            if not length.isdigit() or abs(int(length) - 3000) > 200:
                problemas.append(f"duración rara ({length})")
            if problemas:
                print("MCI-INCOHERENTE: " + "; ".join(problemas))
                return 1
            print("MCI OK")
            return 0
        finally:
            _mci("close probe")


if __name__ == "__main__":
    sys.exit(main())
