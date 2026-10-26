"""Línea de comandos y arranque."""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import shutil
import sys
import tempfile
import wave
from pathlib import Path

from . import __version__
from .config import ConfigError, app_dir, default_config_path, ensure_config, load_config
from .providers import TTSError, list_edge_voices, make_provider
from .text import clean_text, split_chunks

log = logging.getLogger("altr")


def _setup_logging(verbose: bool) -> list[logging.Handler]:
    root = logging.getLogger("altr")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handlers: list[logging.Handler] = []
    try:
        app_dir().mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(app_dir() / "altr.log", maxBytes=500_000,
                                                  backupCount=1, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
        handlers.append(fh)
    except OSError:
        pass
    if sys.stderr is not None and sys.stderr.isatty():
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)
        handlers.append(sh)
    return handlers


class _Out:
    """print() que funciona también en el .exe sin consola: ahí escribe un archivo y lo abre."""

    def __init__(self):
        self.lines: list[str] = []
        self.console = sys.stdout is not None

    def __call__(self, text: str = "") -> None:
        if self.console:
            print(text)
        else:
            self.lines.append(text)

    def finish(self) -> None:
        if self.console or not self.lines:
            return
        path = app_dir() / "salida.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")
        if os.name == "nt" and not os.environ.get("ALTR_NO_OPEN"):
            os.startfile(str(path))  # noqa: S606


def concat_audio(paths: list[Path], out: Path) -> None:
    """Une los trozos en un solo archivo (mp3: se concatenan los bytes; wav: con el módulo wave)."""
    if len(paths) == 1:
        shutil.copyfile(paths[0], out)
    elif out.suffix.lower() == ".wav" and all(p.suffix.lower() == ".wav" for p in paths):
        with wave.open(str(out), "wb") as w:
            for i, p in enumerate(paths):
                with wave.open(str(p), "rb") as r:
                    if i == 0:
                        w.setparams(r.getparams())
                    w.writeframes(r.readframes(r.getnframes()))
    else:
        with open(out, "wb") as f:
            for p in paths:
                f.write(p.read_bytes())


def cmd_say(cfg, text: str, out_file: str | None, out: _Out) -> int:
    from .player import default_backend
    from .reader import Reader
    import threading

    if out_file:
        clean = clean_text(text, strip_markdown=cfg.text.strip_markdown, read_urls=cfg.text.read_urls,
                           max_chars=cfg.text.max_chars, lexicon=cfg.lexicon)
        chunks = split_chunks(clean)
        if not chunks:
            out("No hay texto para leer.")
            return 1
        provider = make_provider(cfg)
        tmp = Path(tempfile.mkdtemp(prefix="altr-say-"))
        try:
            parts = [provider.synthesize(c, tmp, f"c{i:04d}") for i, c in enumerate(chunks)]
            dest = Path(out_file)
            if parts[0].suffix.lower() != dest.suffix.lower() and len(parts) > 1:
                out(f"Aviso: el motor genera {parts[0].suffix}; guardá con esa extensión.")
            concat_audio(parts, dest)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        out(f"Audio guardado en {out_file}")
        return 0

    done = threading.Event()
    errors: list[str] = []
    reader = Reader(cfg, default_backend(), on_error=errors.append,
                    on_state=lambda s: None if s else done.set())
    if not reader.speak(text):
        out("No hay texto para leer.")
        return 1
    done.wait()
    for e in errors:
        out(f"Error: {e}")
    return 1 if errors else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="AltR", description="Lee en voz alta el texto seleccionado (atajo global).")
    p.add_argument("--version", action="store_true", help="muestra la versión")
    p.add_argument("--config", metavar="RUTA", help="usa este config.toml en vez del de siempre")
    p.add_argument("--config-path", action="store_true", help="muestra dónde está el config.toml")
    p.add_argument("--check", action="store_true", help="valida el config y sale (código 0 = bien)")
    p.add_argument("--say", metavar="TEXTO", help="lee este texto y sale (sin atajos ni bandeja)")
    p.add_argument("--out", metavar="ARCHIVO", help="con --say: guarda el audio en vez de reproducirlo")
    p.add_argument("--list-voices", nargs="?", const="", metavar="PREFIJO",
                   help="lista las voces de Edge (ej. es-AR)")
    p.add_argument("--install-autostart", action="store_true", help="arrancar con Windows")
    p.add_argument("--remove-autostart", action="store_true", help="no arrancar con Windows")
    p.add_argument("--no-tray", action="store_true", help="sin ícono de bandeja")
    p.add_argument("-v", "--verbose", action="store_true", help="registro detallado")
    return p


def main(argv: list[str] | None = None) -> int:
    if sys.stderr is None:  # .exe sin consola: argparse escribiría en el vacío
        sys.stderr = open(os.devnull, "w")
    args = build_parser().parse_args(argv)
    handlers = _setup_logging(args.verbose)
    out = _Out()
    try:
        return _run(args, out)
    finally:
        out.finish()
        # En Windows un archivo abierto no se puede borrar ni mover: soltar altr.log al salir.
        for h in handlers:
            logging.getLogger("altr").removeHandler(h)
            h.close()


def _run(args, out: _Out) -> int:
    config_path = Path(args.config) if args.config else default_config_path()
    if args.version:
        out(f"AltR {__version__}")
        return 0
    if args.config_path:
        out(str(config_path))
        return 0
    if args.list_voices is not None:
        try:
            for line in list_edge_voices(args.list_voices):
                out(line)
        except Exception as e:
            out(f"No pude obtener las voces (¿hay internet?): {e}")
            return 1
        return 0
    if args.install_autostart or args.remove_autostart:
        if os.name != "nt":
            out("El inicio con Windows sólo existe en Windows.")
            return 1
        from . import win
        win.set_autostart(args.install_autostart)
        out("AltR arrancará con Windows." if args.install_autostart else "AltR ya no arranca con Windows.")
        return 0

    ensure_config(config_path)
    try:
        cfg = load_config(config_path)
    except ConfigError as e:
        out(f"Config inválido: {e}")
        log.error("config inválido: %s", e)
        return 2
    for w in cfg.warnings:
        out(f"Aviso: {w}")
    if args.check:
        out(f"Config OK ({config_path})")
        out(f"  atajo: {cfg.general.hotkey}   cortar: {cfg.general.stop_hotkey or '(ninguno)'}")
        out(f"  motor: {cfg.tts.provider}   velocidad: {cfg.tts.speed:g}   volumen: {cfg.tts.volume}")
        return 0
    if args.say is not None:
        try:
            return cmd_say(cfg, args.say, args.out, out)
        except TTSError as e:
            out(f"Error: {e}")
            return 1

    if os.name != "nt":
        out("AltR (atajos y bandeja) sólo funciona en Windows. "
            "Acá podés probar con --say, --check y --list-voices.")
        return 1
    from . import win
    from .app import App

    tray_factory = None
    if not args.no_tray:
        from . import tray as tray_mod

        if tray_mod.available():
            def tray_factory(app):  # noqa: F811
                return tray_mod.Tray(
                    on_read_clipboard=app.read_clipboard, on_stop=app.reader.stop,
                    on_open_config=app.open_config, on_reload=app.reload,
                    on_open_log=app.open_log, on_quit=app.quit,
                    autostart_get=win.autostart_enabled, autostart_set=win.set_autostart)
        else:
            log.warning("pystray/Pillow no están instalados: corro sin ícono de bandeja.")
    return App(config_path, win, tray_factory=tray_factory).run()
