"""Marcas por palabra de un trozo: en qué segundo del audio empieza y termina cada palabra del texto.

El karaoke del overlay resalta la última palabra cuya marca ya empezó. Tres fuentes, de la más a la menos
precisa (sólo biblioteca estándar: nada que agrande el .exe):

  · "modelo": el motor dice cuándo pronuncia cada palabra. Edge lo hace (eventos WordBoundary del servicio);
    `de_limites` las ubica sobre las palabras del texto aunque Edge las parta o las junte («Ctrl+S» llega como
    «Ctrl», «+», «S»; «4 o» llega junto).
  · "audio": wav sin marcas (motores `[command]` como piper). Se estiman de la energía del wav: las pausas
    reales se reparten entre los límites de palabra (prefiriendo la puntuación) y dentro de cada tramo
    hablado el reparto sigue lo que tarda en decirse cada palabra («F5» pesa lo que pesa «efe cinco»).
    Es el mismo algoritmo de `asistente_marcas.py` de la versión Linux.
  · "texto": mp3 sin marcas (OpenAI). No se decodifica (sería una dependencia pesada): se reparte la
    duración del trozo según lo que tarda en decirse cada palabra, con pausas en la puntuación.

Si nada sirve devuelve None y el overlay reparte por caracteres, como antes.
"""
from __future__ import annotations

import array
import difflib
import math
import re
import wave
from pathlib import Path

from .audio import _mp3_header

PASO = 0.01          # s por cuadro de energía
MIN_PAUSA = 0.09     # s: un silencio más corto es una consonante, no una pausa
AJUSTE_VALLE = 0.05  # s: cuánto se puede correr un límite de palabra para caer en un valle de energía
SALIDA = 0.30       # s de silencio al final de un mp3 (estimación por texto; Edge deja ~0,9)
ENTRADA = 0.10       # s de silencio al principio de un mp3 (Edge empieza ~0,1 s)
PAUSA_COMA = 0.18    # s: pausa tras , ; (estimación por texto)
PAUSA_FIN = 0.38     # s: pausa tras . ! ? : … (estimación por texto)

_VOCALES = "aeiouáéíóúüyAEIOUÁÉÍÓÚÜY"
_PARTES = re.compile(r"\d+|[^\W\d_]+|[^\w\s]", re.UNICODE)
_PUNT_FUERTE = (".", "!", "?", ":", ";", "…")


def _silabas(s: str) -> int:
    return len(re.findall(f"[{_VOCALES}]+", s))


def peso(token: str) -> float:
    """Cuánto tarda en decirse una palabra, en sílabas aproximadas. Ve lo que no se lee como se escribe:
    «F5» = efe cinco, «Ctrl» = control, «12» = doce, «/» = barra."""
    total = 0.0
    partes = _PARTES.findall(token)
    letras = [p for p in partes if p[0].isalpha()]
    for p in partes:
        if p.isdigit():
            total += 1.8 * len(p)
        elif p[0].isalpha():
            if len(p) == 1 or (p.isupper() and len(p) <= 5):   # sigla o letra suelta: se dice cada letra
                total += 1.6 * len(p)
            elif _silabas(p) == 0:                             # sin vocales: abreviatura (Ctrl, Cmd)
                total += max(1.5, 0.6 * len(p))
            else:
                total += _silabas(p) + 0.12 * len(p)
        elif p in "+/=@&%#_*" or (p == "-" and letras and len(partes) == 1):
            total += 1.5                                       # símbolo que se pronuncia
    return max(total, 0.25)


# ------------------------------------------------------------------ validar
def sana(marcas, n: int, dur: float):
    """Exige una marca por palabra, números crecientes y dentro del audio. None si no sirve."""
    if not isinstance(marcas, (list, tuple)) or len(marcas) != n or n == 0:
        return None
    out, ult = [], 0.0
    for m in marcas:
        if not (isinstance(m, (list, tuple)) and len(m) == 2):
            return None
        try:
            a, b = float(m[0]), float(m[1])
        except (TypeError, ValueError):
            return None
        if not (math.isfinite(a) and math.isfinite(b)):
            return None
        a = max(ult, min(a, dur))
        b = max(a, min(b, dur))
        out.append([round(a, 3), round(b, 3)])
        ult = a
    return out


# ------------------------------------------------------- Edge (WordBoundary)
def de_limites(limites, texto: str, dur: float):
    """Marcas por palabra de `texto` a partir de los eventos del servicio: [(inicio_s, duracion_s, texto)].

    Se alinean carácter a carácter (sólo letras y dígitos): cada palabra del texto empieza donde empieza su
    primer carácter y termina donde termina el último, repartiendo el tiempo de cada evento entre sus
    caracteres. Las palabras sin letras ni dígitos (símbolos) quedan con marca vacía pegada a la anterior.
    None si lo que dijo el servicio no se parece al texto (entonces se estima del audio)."""
    palabras = texto.split()
    if not palabras or not limites:
        return None
    # línea de tiempo del servicio: un (ini, fin) por carácter alfanumérico
    src_txt, src_t = [], []
    for ini, d, t in limites:
        cs = [c for c in str(t).lower() if c.isalnum()]
        for k, c in enumerate(cs):
            src_txt.append(c)
            src_t.append((ini + d * k / len(cs), ini + d * (k + 1) / len(cs)))
    dst_txt, dst_w = [], []
    for w, p in enumerate(palabras):
        for c in p.lower():
            if c.isalnum():
                dst_txt.append(c)
                dst_w.append(w)
    if not src_txt or not dst_txt:
        return None
    # carácter del texto -> carácter del servicio (igualdad exacta o por bloques coincidentes)
    mapa: list[int | None] = [None] * len(dst_txt)
    if src_txt == dst_txt:
        mapa = list(range(len(dst_txt)))
    else:
        sm = difflib.SequenceMatcher(None, dst_txt, src_txt, autojunk=False)
        if sm.ratio() < 0.85:
            return None
        for a, b, n in sm.get_matching_blocks():
            for k in range(n):
                mapa[a + k] = b + k
    tiempos: list[tuple[float, float]] = [(0.0, 0.0)] * len(dst_txt)
    for i, j in enumerate(mapa):
        if j is not None:
            tiempos[i] = src_t[j]
    # caracteres sin pareja: interpolar entre vecinos con tiempo conocido
    conocidos = [i for i, j in enumerate(mapa) if j is not None]
    if not conocidos:
        return None
    for i, j in enumerate(mapa):
        if j is not None:
            continue
        prev = max((k for k in conocidos if k < i), default=None)
        sig = min((k for k in conocidos if k > i), default=None)
        if prev is None:
            tiempos[i] = (tiempos[sig][0], tiempos[sig][0])
        elif sig is None:
            tiempos[i] = (tiempos[prev][1], tiempos[prev][1])
        else:
            a, b = tiempos[prev][1], tiempos[sig][0]
            f = (i - prev) / (sig - prev)
            tiempos[i] = (a + (b - a) * f, a + (b - a) * f)
    ini_w: dict[int, float] = {}
    fin_w: dict[int, float] = {}
    for i, w in enumerate(dst_w):
        ini_w.setdefault(w, tiempos[i][0])
        fin_w[w] = tiempos[i][1]
    marcas, ultimo = [], 0.0
    for w in range(len(palabras)):
        if w in ini_w:
            marcas.append([ini_w[w], fin_w[w]])
            ultimo = fin_w[w]
        else:
            marcas.append([ultimo, ultimo])
    return sana(marcas, len(palabras), dur)


# --------------------------------------------------------- wav (energía)
def _energia(ruta):
    """RMS por cuadro de PASO segundos (lista de float) y duración del wav en segundos."""
    with wave.open(str(ruta), "rb") as w:
        sr, canales, ancho, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        crudo = w.readframes(n)
    if ancho != 2 or n == 0:
        return [], n / float(sr or 1)
    a = array.array("h")
    a.frombytes(crudo[: len(crudo) - len(crudo) % 2])
    tam = max(1, int(sr * PASO)) * canales
    salto = max(1, tam // 64)            # submuestreo: alcanza para la envolvente y cuesta poco en Python puro
    rms = []
    for i in range(0, len(a) - tam + 1, tam):
        b = a[i:i + tam:salto]
        rms.append(math.sqrt(sum(x * x for x in b) / len(b)))
    return rms, n / float(sr)


def _tramos_de_voz(rms, paso=PASO, piso=30.0):
    """[(cuadro_ini, cuadro_fin)] de los tramos hablados, separados por silencios de al menos MIN_PAUSA."""
    if not rms:
        return []
    orden = sorted(rms)
    alto = orden[int(len(orden) * 0.95)] or 1.0
    umbral = max(alto * 0.07, piso)
    voz = [v > umbral for v in rms]
    tramos, ini, callado = [], None, 0
    minimo = max(1, int(round(MIN_PAUSA / paso)))
    for i, v in enumerate(voz):
        if v:
            if ini is None:
                ini = i
            callado = 0
        elif ini is not None:
            callado += 1
            if callado >= minimo:
                tramos.append((ini, i - callado + 1))
                ini, callado = None, 0
    if ini is not None:
        tramos.append((ini, len(voz) - callado))
    return [t for t in tramos if t[1] > t[0]]


def _termina_en(palabra: str, signos: str) -> bool:
    return palabra.rstrip("\"')]»”’")[-1:] in signos


def _repartir(pesos, tramos, palabras=None, paso=PASO):
    """Qué palabras caen en cada tramo hablado. Programación dinámica: cada tramo tiene que durar lo que
    pesan sus palabras, y un corte conviene donde el texto trae puntuación (una pausa larga sin signo, o
    un signo fuerte sin pausa, cuesta). Devuelve los cortes [0..n]."""
    n, s = len(pesos), len(tramos)
    acu = [0.0]
    for p in pesos:
        acu.append(acu[-1] + p)
    voz_total = sum(b - a for a, b in tramos) or 1
    ritmo = voz_total / (acu[-1] or 1.0)
    piso = 0.15 / paso
    inf = float("inf")
    costo = [[inf] * (n + 1) for _ in range(s + 1)]
    previo = [[0] * (n + 1) for _ in range(s + 1)]
    costo[0][0] = 0.0

    def corte(j, a):
        """Costo de cortar entre los tramos j-1 y j (1-based) justo antes de la palabra `a`."""
        if palabras is None or j < 2:
            return 0.0
        pausa = (tramos[j - 1][0] - tramos[j - 2][1]) * paso
        w = palabras[a - 1]
        if _termina_en(w, ",;"):
            return 0.0 if pausa >= 0.1 else 0.15
        if _termina_en(w, ".!?:…"):
            return 0.0 if pausa >= 0.2 else 0.3
        return 0.5 if pausa >= 0.2 else 0.0      # una pausa larga sin puntuación casi nunca es entre palabras

    for j in range(1, s + 1):
        dur = tramos[j - 1][1] - tramos[j - 1][0]
        for b in range(j, n - (s - j) + 1):
            mejor, de = inf, 0
            for a in range(j - 1, b):
                c0 = costo[j - 1][a]
                if c0 == inf:
                    continue
                esperado = (acu[b] - acu[a]) * ritmo
                c = c0 + ((dur - esperado) / max(esperado, piso)) ** 2 + corte(j, a)
                if c < mejor:
                    mejor, de = c, a
            costo[j][b], previo[j][b] = mejor, de
    cortes = [n]
    b = n
    for j in range(s, 0, -1):
        b = previo[j][b]
        cortes.append(b)
    return cortes[::-1]


def _unir_tramos(palabras, tramos):
    """Nunca más tramos que palabras: une los que tienen la pausa más corta entre sí."""
    tramos = list(tramos)
    while len(tramos) > len(palabras):
        huecos = [tramos[i + 1][0] - tramos[i][1] for i in range(len(tramos) - 1)]
        i = huecos.index(min(huecos))
        tramos[i:i + 2] = [(tramos[i][0], tramos[i + 1][1])]
    return tramos


def _valle(rms, cuadro, paso=PASO):
    """Corre un límite de palabra al cuadro de menor energía que tenga cerca."""
    r = int(round(AJUSTE_VALLE / paso))
    a, b = max(0, cuadro - r), min(len(rms) - 1, cuadro + r)
    if a >= b:
        return cuadro
    return min(range(a, b + 1), key=lambda i: (rms[i], abs(i - cuadro)))


def _alinear(rms, paso, piso, dur, texto):
    """Reparte las palabras de `texto` sobre los tramos hablados de una envolvente (un valor por `paso` s)."""
    palabras = texto.split()
    tramos = _unir_tramos(palabras, _tramos_de_voz(rms, paso, piso))
    if not tramos:
        return None
    pesos = [peso(p) for p in palabras]
    cortes = _repartir(pesos, tramos, palabras, paso)
    marcas = []
    for j, (a, b) in enumerate(tramos):
        w0, w1 = cortes[j], cortes[j + 1]
        total = sum(pesos[w0:w1]) or 1.0
        run = 0.0
        ini = a
        for w in range(w0, w1):
            run += pesos[w]
            fin = b if w == w1 - 1 else _valle(rms, int(round(a + (b - a) * run / total)), paso)
            fin = max(ini, min(b, fin))
            marcas.append([round(ini * paso, 3), round(fin * paso, 3)])
            ini = fin
    return sana(marcas, len(palabras), dur)


def desde_wav(ruta, texto: str):
    """Marcas estimadas de la energía de un wav: [[ini, fin], ...] una por palabra de `texto`, o None."""
    if not texto.split():
        return None
    rms, dur = _energia(ruta)
    return _alinear(rms, PASO, 30.0, dur, texto)


# ------------------------------------------------------- mp3 (información lateral)
def _energia_mp3(ruta):
    """Envolvente de un mp3 SIN decodificarlo: por cada granulo, `big_values` de su información lateral
    (cuántos coeficientes espectrales no nulos hay: 0 en el silencio digital, 50-270 al hablar). Devuelve
    (valores, segundos_por_valor, duración) o None. Sólo mono/estéreo capa III (MPEG-1 y 2)."""
    try:
        b = Path(ruta).read_bytes()
    except OSError:
        return None
    i = 0
    if b[:3] == b"ID3" and len(b) >= 10:
        i = 10 + ((b[6] & 0x7F) << 21 | (b[7] & 0x7F) << 14 | (b[8] & 0x7F) << 7 | (b[9] & 0x7F))
    vals: list[float] = []
    paso = None
    primero = True
    while i + 4 <= len(b):
        h = _mp3_header(b, i)
        if not h or h[2] not in (576, 1152):
            i += 1
            continue
        kbps, sr, spf, mono, crc, mpeg1 = h
        flen = (144 if mpeg1 else 72) * kbps * 1000 // sr + ((b[i + 2] >> 1) & 1)
        si = i + 4 + (2 if crc else 0)
        nch = 1 if mono else 2
        ng = 2 if mpeg1 else 1
        # cabecera de la información lateral antes de los granulos
        ini_bits = (9 + (5 if mono else 3) + 4 * nch) if mpeg1 else (8 + (1 if mono else 2))
        largo = 59 if mpeg1 else 63          # bits de un granulo+canal
        if si + 32 > len(b):
            break
        lado = int.from_bytes(b[si:si + 32], "big")
        total = 256
        # el primer cuadro de un mp3 de LAME/Xing trae la etiqueta, no audio: no cuenta en la línea de tiempo
        tag = si + (17 if mono else 32) if mpeg1 else si + (9 if mono else 17)
        if primero and b[tag:tag + 4] in (b"Xing", b"Info"):
            primero = False
            i += max(flen, 4)
            continue
        primero = False
        for g in range(ng):
            suma = 0
            for c in range(nch):
                pos = ini_bits + (g * nch + c) * largo
                suma += (lado >> (total - pos - 12 - 9)) & 0x1FF   # big_values: 9 bits tras part2_3_length
            vals.append(float(suma))
        paso = spf / ng / sr
        i += max(flen, 4)
    if not vals or not paso:
        return None
    return vals, paso, len(vals) * paso


def desde_mp3(ruta, texto: str):
    """Marcas estimadas de un mp3 sin decodificarlo (ver `_energia_mp3`), o None."""
    if not texto.split():
        return None
    e = _energia_mp3(ruta)
    if not e:
        return None
    vals, paso, dur = e
    return _alinear(vals, paso, 3.0, dur, texto)


# ----------------------------------------------------------- mp3 (por texto)
def desde_texto(texto: str, dur: float):
    """Marcas estimadas sin mirar el audio: la duración (sin la entrada y la salida) se reparte según
    lo que tarda en decirse cada palabra, y la puntuación se lleva su pausa."""
    palabras = texto.split()
    if not palabras or dur <= 0:
        return None
    pesos = [peso(p) for p in palabras]
    pausas = []
    for p in palabras:
        fin = p.rstrip("\"')]»”’")[-1:]
        pausas.append(PAUSA_FIN if fin in _PUNT_FUERTE else PAUSA_COMA if fin == "," else 0.0)
    pausas[-1] = 0.0                       # tras la última no hay nada que repartir
    util = dur - ENTRADA - SALIDA - sum(pausas)
    if util <= 0.05 * dur:                  # trozo cortísimo o pausas de más: sin pausas
        pausas = [0.0] * len(palabras)
        util = max(dur - ENTRADA - SALIDA, 0.5 * dur)
    por_peso = util / sum(pesos)
    t, marcas = min(ENTRADA, dur * 0.5), []
    for p, pa in zip(pesos, pausas):
        marcas.append([t, t + p * por_peso])
        t += p * por_peso + pa
    return sana(marcas, len(palabras), dur)


def de_archivo(ruta, texto: str, dur: float):
    """(marcas, fuente) para un trozo sin marcas del motor: del wav si es wav, del texto si no."""
    n = len(texto.split())
    if n == 0:
        return None, None
    ruta = Path(ruta)
    try:
        if ruta.suffix.lower() == ".wav":
            m = desde_wav(ruta, texto)
        else:
            m = desde_mp3(ruta, texto)
    except (OSError, EOFError, wave.Error, ValueError, ZeroDivisionError, IndexError):
        m = None
    if m:
        return m, "audio"
    m = desde_texto(texto, dur)
    return (m, "texto") if m else (None, None)
