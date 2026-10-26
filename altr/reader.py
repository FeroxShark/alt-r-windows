"""Orquestador de una lectura: trocea, sintetiza por adelantado y reproduce en orden.

Una lectura nueva corta la anterior (igual que Alt+R en la versión Linux). Es
independiente de la plataforma: el audio sale por un `backend` y los errores por
`on_error`, así se prueba entero sin Windows.
"""
from __future__ import annotations

import logging
import queue
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Callable

from .config import Config
from .providers import TTSError, make_provider
from .text import clean_text, split_chunks

log = logging.getLogger("altr")
_DONE = object()
PREFETCH = 3  # trozos sintetizados por delante de lo que suena


class _Session:
    def __init__(self):
        self.cancel = threading.Event()
        self.threads: list[threading.Thread] = []


class Reader:
    def __init__(self, cfg: Config, backend, on_error: Callable[[str], None] | None = None,
                 on_state: Callable[[bool], None] | None = None, provider=None):
        self.cfg = cfg
        self.backend = backend
        self.on_error = on_error or (lambda msg: None)
        self.on_state = on_state or (lambda speaking: None)
        self._provider = provider
        self._lock = threading.Lock()
        self._session: _Session | None = None

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

    def speak(self, raw_text: str) -> bool:
        """Empieza a leer (cortando lo anterior). False si no había nada que leer."""
        cfg = self.cfg
        text = clean_text(raw_text, strip_markdown=cfg.text.strip_markdown,
                          read_urls=cfg.text.read_urls, max_chars=cfg.text.max_chars,
                          lexicon=cfg.lexicon)
        chunks = split_chunks(text)
        if not chunks:
            return False
        with self._lock:
            self._stop_locked()
            try:
                provider = self._provider or make_provider(cfg)
            except Exception as e:  # config de proveedor incompleta, etc.
                self.on_error(str(e))
                return False
            session = _Session()
            self._session = session
            q: queue.Queue = queue.Queue(maxsize=PREFETCH)
            tmp = Path(tempfile.mkdtemp(prefix="altr-"))
            synth = threading.Thread(target=self._synth_loop, name="altr-synth",
                                     args=(session, provider, chunks, tmp, q), daemon=True)
            play = threading.Thread(target=self._play_loop, name="altr-play",
                                    args=(session, tmp, q, cfg.tts.volume), daemon=True)
            session.threads = [synth, play]
            self.on_state(True)
            synth.start()
            play.start()
        return True

    def _synth_loop(self, session, provider, chunks, tmp, q) -> None:
        try:
            for i, chunk in enumerate(chunks):
                if session.cancel.is_set():
                    return
                try:
                    path = provider.synthesize(chunk, tmp, f"c{i:04d}")
                except TTSError as e:
                    if session.cancel.is_set():
                        return
                    log.error("síntesis falló: %s", e)
                    self.on_error(str(e))
                    session.cancel.set()  # no seguir leyendo con huecos
                    return
                except Exception as e:
                    if session.cancel.is_set():
                        return
                    log.exception("síntesis falló")
                    self.on_error(f"Error inesperado al generar la voz: {e}")
                    session.cancel.set()
                    return
                while not session.cancel.is_set():
                    try:
                        q.put(path, timeout=0.1)
                        break
                    except queue.Full:
                        continue
        finally:
            while not session.cancel.is_set():
                try:
                    q.put(_DONE, timeout=0.1)
                    break
                except queue.Full:
                    continue

    def _play_loop(self, session, tmp, q, volume) -> None:
        try:
            while not session.cancel.is_set():
                try:
                    item = q.get(timeout=0.1)
                except queue.Empty:
                    continue
                if item is _DONE:
                    break
                try:
                    self.backend.play(item, volume, session.cancel)
                except Exception as e:
                    log.exception("reproducción falló")
                    self.on_error(f"No pude reproducir el audio: {e}")
                    session.cancel.set()
                    break
        finally:
            session.cancel.set()
            shutil.rmtree(tmp, ignore_errors=True)
            with self._lock:
                if self._session is session or self._session is None:
                    self._session = None
                    self.on_state(False)
