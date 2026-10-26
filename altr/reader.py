"""Orquestador de una lectura: trocea, sintetiza por adelantado y reproduce en orden.

Una lectura nueva corta la anterior (igual que Alt+R en la versión Linux). Es
independiente de la plataforma: el audio sale por un `backend` y los errores por
`on_error`, así se prueba entero sin Windows.

Cada lectura es una `_Session` con todos los trozos conocidos desde el principio: la
interfaz (overlay) pide `snapshot()` para dibujar el karaoke y el progreso, y puede pausar
(`toggle_pause`) o saltar (`seek`) a cualquier punto ya sintetizado.
"""
from __future__ import annotations

import logging
import shutil
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Callable

from .audio import audio_duration, bin_peaks, envelope
from .config import Config
from .player import PlayControl
from .providers import TTSError, make_provider
from .text import clean_text, split_chunks

log = logging.getLogger("altr")
PREFETCH = 3  # trozos sintetizados por delante de lo que suena


def _words(s: str) -> int:
    return len(s.split())


class _Session:
    def __init__(self, texts: list[str], shown: list[str]):
        n = len(texts)
        self.id = uuid.uuid4().hex[:8]
        self.cancel = threading.Event()
        self.threads: list[threading.Thread] = []
        self.cond = threading.Condition()
        self.texts = texts          # lo que se sintetiza (con lexicón)
        self.shown = shown          # lo que se muestra (sin lexicón si las palabras alinean)
        self.paths: list[Path | None] = [None] * n
        self.durs: list[float | None] = [None] * n
        self.envs: list[list[float] | None] = [None] * n
        self.peaks: list[float] = []
        self.cur = 0                # trozo que suena, o el próximo si estamos entre trozos
        self.started = False        # ya sonó audio
        self.playing_now = False    # backend.play en curso
        self.finished = False       # terminó (bien, cortada o con error)
        self.ctl = PlayControl()
        self.jump: tuple[int, float] | None = None
        self.error: str | None = None


class Reader:
    def __init__(self, cfg: Config, backend, on_error: Callable[[str], None] | None = None,
                 on_state: Callable[[bool], None] | None = None, provider=None):
        self.cfg = cfg
        self.backend = backend
        self.on_error = on_error or (lambda msg: None)
        self.on_state = on_state or (lambda speaking: None)
        self._provider = provider
        self._lock = threading.Lock()
        self._session: _Session | None = None   # la lectura viva
        self._latest: _Session | None = None    # la última (aunque haya terminado), para snapshot()

    def set_config(self, cfg: Config, provider=None) -> None:
        with self._lock:
            self.cfg = cfg
            self._provider = provider

    @property
    def speaking(self) -> bool:
        s = self._session
        return s is not None and not s.cancel.is_set() and any(t.is_alive() for t in s.threads)

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        s, self._session = self._session, None
        if s:
            s.cancel.set()

    # ------------------------------------------------------------- lectura
    def speak(self, raw_text: str) -> bool:
        """Empieza a leer (cortando lo anterior). False si no había nada que leer."""
        cfg = self.cfg
        opts = dict(strip_markdown=cfg.text.strip_markdown, read_urls=cfg.text.read_urls,
                    max_chars=cfg.text.max_chars)
        chunks = split_chunks(clean_text(raw_text, lexicon=cfg.lexicon, **opts))
        if not chunks:
            return False
        shown = chunks
        if cfg.lexicon:  # el overlay muestra el texto original, no el "fonético" del lexicón
            plain = split_chunks(clean_text(raw_text, lexicon=None, **opts))
            if len(plain) == len(chunks) and all(_words(a) == _words(b) for a, b in zip(plain, chunks)):
                shown = plain
        with self._lock:
            self._stop_locked()
            try:
                provider = self._provider or make_provider(cfg)
            except Exception as e:  # config de proveedor incompleta, etc.
                self.on_error(str(e))
                return False
            session = _Session(chunks, shown)
            self._session = self._latest = session
            tmp = Path(tempfile.mkdtemp(prefix="altr-"))
            synth = threading.Thread(target=self._synth_loop, name="altr-synth",
                                     args=(session, provider, tmp), daemon=True)
            play = threading.Thread(target=self._play_loop, name="altr-play",
                                    args=(session, tmp, cfg.tts.volume), daemon=True)
            session.threads = [synth, play]
            self.on_state(True)
            synth.start()
            play.start()
        return True

    def _fail(self, session: _Session, msg: str) -> None:
        with session.cond:
            session.error = msg
            session.cond.notify_all()
        self.on_error(msg)
        session.cancel.set()  # no seguir leyendo con huecos

    def _synth_loop(self, session: _Session, provider, tmp: Path) -> None:
        try:
            for i, chunk in enumerate(session.texts):
                with session.cond:  # no adelantarse más de PREFETCH trozos
                    while i - session.cur > PREFETCH and not session.cancel.is_set():
                        session.cond.wait(0.1)
                if session.cancel.is_set():
                    return
                try:
                    path = provider.synthesize(chunk, tmp, f"c{i:04d}")
                    dur = audio_duration(path)
                    env = envelope(path, chunk, dur)
                except TTSError as e:
                    if session.cancel.is_set():
                        return
                    log.error("síntesis falló: %s", e)
                    self._fail(session, str(e))
                    return
                except Exception as e:
                    if session.cancel.is_set():
                        return
                    log.exception("síntesis falló")
                    self._fail(session, f"Error inesperado al generar la voz: {e}")
                    return
                with session.cond:
                    session.paths[i], session.durs[i], session.envs[i] = path, dur, env
                    session.peaks = bin_peaks(session.envs)
                    session.cond.notify_all()
        finally:
            with session.cond:
                session.cond.notify_all()

    def _next_ready(self, session: _Session, i: int, start: float):
        """Espera el trozo `i` (o un salto pedido). Devuelve (i, start) o None si no hay más."""
        with session.cond:
            while not session.cancel.is_set():
                if session.jump:
                    (i, start), session.jump = session.jump, None
                    session.ctl.interrupt.clear()
                if i >= len(session.paths):
                    return None
                if session.paths[i] is not None:
                    session.cur = i
                    session.cond.notify_all()
                    return i, start
                if not self._synth_alive(session):
                    return None
                session.cond.wait(0.1)
        return None

    @staticmethod
    def _synth_alive(session: _Session) -> bool:
        return bool(session.threads) and session.threads[0].is_alive()

    def _play_loop(self, session: _Session, tmp: Path, volume: int) -> None:
        i, start = 0, 0.0
        try:
            while True:
                nxt = self._next_ready(session, i, start)
                if nxt is None:
                    break
                i, start = nxt
                ctl = session.ctl
                ctl.begin(start)
                session.started = session.playing_now = True
                try:
                    self.backend.play(session.paths[i], volume, session.cancel, ctl=ctl, start=start)
                except Exception as e:
                    if session.cancel.is_set():
                        break
                    log.exception("reproducción falló")
                    self._fail(session, f"No pude reproducir el audio: {e}")
                    break
                finally:
                    session.playing_now = False
                with session.cond:
                    if ctl.length and abs(ctl.length - (session.durs[i] or 0)) > 0.05:
                        session.durs[i] = ctl.length  # la duración real manda para los trozos que siguen
                        session.peaks = bin_peaks(session.envs)
                    if not session.jump:
                        i, start = i + 1, 0.0
                        session.cur = min(i, len(session.paths))
                    session.cond.notify_all()
        finally:
            session.cancel.set()
            session.finished = True
            shutil.rmtree(tmp, ignore_errors=True)
            with self._lock:
                if self._session is session or self._session is None:
                    self._session = None
                    self.on_state(False)

    # ----------------------------------------------- control desde la interfaz
    def _live(self) -> _Session | None:
        s = self._session
        return s if s and not s.finished and not s.cancel.is_set() else None

    def toggle_pause(self) -> None:
        s = self._live()
        if s:
            s.ctl.paused = not s.ctl.paused

    def seek(self, t: float) -> None:
        """Salta al instante `t` (segundos del audio ya generado, contando desde el principio)."""
        s = self._live()
        if not s:
            return
        with s.cond:
            known = [(i, d) for i, d in enumerate(s.durs) if d is not None]
            # sólo hasta el primer hueco: más allá del último trozo contiguo no hay audio todavía
            seq, acc = [], 0.0
            for i, d in enumerate(s.durs):
                if d is None:
                    break
                seq.append((i, acc, d))
                acc += d
            if not seq or not known:
                return
            t = max(0.0, min(t, acc))
            k, base, d = next(((i, a, dd) for i, a, dd in seq if t < a + dd), seq[-1])
            off = max(0.0, min(t - base, d - 0.05))
            if k == s.cur and s.playing_now and not s.jump:
                s.ctl.seek(off)
            else:
                s.jump = (k, off)
                s.ctl.interrupt.set()
            s.cond.notify_all()

    def snapshot(self) -> dict | None:
        """Foto de la última lectura para la interfaz, o None si todavía no hubo ninguna."""
        s = self._latest
        if s is None:
            return None
        with s.cond:
            durs = list(s.durs)
            if s.jump:  # salto pedido y todavía no ejecutado: ya se muestra el destino
                k, off = s.jump
                pos = sum(d or 0.0 for d in durs[:k]) + off
            else:
                before = sum(d or 0.0 for d in durs[:s.cur])
                pos = before + (s.ctl.position if s.playing_now else 0.0)
            if s.error:
                phase = "error"
            elif s.finished or s.cancel.is_set():
                phase = "done"
            elif not s.started:
                phase = "preparing"
            elif s.ctl.paused:
                phase = "paused"
            elif s.playing_now or s.jump or s.cur >= len(s.paths) or s.paths[s.cur] is not None:
                phase = "playing"  # entre trozos con el siguiente ya listo no es una espera
            else:
                phase = "stalled"
            return {"id": s.id, "phase": phase, "texts": list(s.shown), "durs": durs, "pos": pos,
                    "complete": all(p is not None for p in s.paths), "peaks": list(s.peaks),
                    "error": s.error or ""}
