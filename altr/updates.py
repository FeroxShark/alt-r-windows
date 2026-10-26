"""Actualizaciones: consulta el último release en GitHub y, si hay uno nuevo, corre install.ps1.

El instalador ya sabe cerrar AltR, reemplazar el .exe y dejar la configuración como está; acá sólo
se compara la versión, se baja el script (de la rama main) y se lo lanza en un PowerShell aparte.
Nada de esto usa Qt: el controlador de la ventana de Configuración y la bandeja lo llaman desde
hilos de trabajo.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import __version__
from .config import app_dir

log = logging.getLogger("altr")

REPO = "FeroxShark/alt-r-windows"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
INSTALL_URL = f"https://raw.githubusercontent.com/{REPO}/main/install.ps1"
RELEASES_URL = f"https://github.com/{REPO}/releases"
CHECK_EVERY = 24 * 3600       # chequeo silencioso al arrancar: una vez por día
TIMEOUT = 10


class UpdateError(RuntimeError):
    """Mensaje pensado para mostrárselo al usuario."""


def parse_version(text: str) -> tuple[int, ...] | None:
    """'v0.2.1' -> (0, 2, 1). None si no parece una versión."""
    m = re.match(r"^\s*v?(\d+(?:\.\d+){0,3})", str(text or ""))
    return tuple(int(p) for p in m.group(1).split(".")) if m else None


def is_newer(candidate: str, current: str = __version__) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    if a is None or b is None:
        return False
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def _get(url: str, accept: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"AltR/{__version__}", "Accept": accept})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def check_latest() -> dict:
    """Consulta la API de GitHub. Devuelve {version, tag, url, newer, current}. Levanta
    UpdateError con un texto entendible si no se pudo (sin internet, sin releases, límite de GitHub)."""
    try:
        data = json.loads(_get(API_URL, "application/vnd.github+json").decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UpdateError("Todavía no hay versiones publicadas.") from None
        if e.code in (403, 429):
            raise UpdateError("GitHub no deja consultar ahora (demasiados pedidos). Probá en un rato.") from None
        raise UpdateError(f"GitHub respondió {e.code}.") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise UpdateError("No pude conectar con GitHub. ¿Hay internet?") from None
    except ValueError:
        raise UpdateError("GitHub respondió algo que no entiendo.") from None
    tag = str(data.get("tag_name") or "")
    ver = parse_version(tag)
    if ver is None:
        raise UpdateError("No pude leer la versión del último release.")
    version = ".".join(str(p) for p in ver)
    return {"version": version, "tag": tag, "url": data.get("html_url") or RELEASES_URL,
            "newer": is_newer(version), "current": __version__}


# ----------------------------------------------------------------- chequeo diario
def state_file() -> Path:
    return app_dir() / "updates.json"


def _read_state() -> dict:
    try:
        data = json.loads(state_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def record_check(version: str | None, now: float | None = None) -> None:
    """Anota cuándo se chequeó y qué versión salió (None = el chequeo falló: se reintenta mañana
    igual, así una racha sin internet no martilla a GitHub)."""
    state = _read_state()
    state["checked"] = time.time() if now is None else now
    if version:
        state["latest"] = version
    try:
        state_file().parent.mkdir(parents=True, exist_ok=True)
        state_file().write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        log.debug("no pude guardar updates.json", exc_info=True)


def due(now: float | None = None) -> bool:
    """¿Pasó más de un día desde el último chequeo?"""
    last = _read_state().get("checked", 0)
    now = time.time() if now is None else now
    return not isinstance(last, (int, float)) or now - last >= CHECK_EVERY or last > now


def known_newer() -> str:
    """La versión nueva que ya vio el último chequeo, o "" si no hay (o ya se instaló)."""
    latest = str(_read_state().get("latest") or "")
    return latest if latest and is_newer(latest) else ""


# ------------------------------------------------------------------ instalación
def download_installer(dest_dir: Path | None = None) -> Path:
    """Baja install.ps1 de la rama main a una carpeta temporal y lo valida."""
    try:
        body = _get(INSTALL_URL, "text/plain")
    except (urllib.error.URLError, TimeoutError, OSError):
        raise UpdateError("No pude bajar el instalador de GitHub. ¿Hay internet?") from None
    text = body.decode("utf-8", errors="replace")
    if "Install-AltR" not in text or len(text) < 500:
        raise UpdateError("El instalador que bajé no es el esperado; no lo ejecuto.")
    folder = Path(dest_dir) if dest_dir else Path(tempfile.mkdtemp(prefix="altr-update-"))
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "install.ps1"
    path.write_text(text, encoding="utf-8", newline="")
    return path


def launch_installer(script: Path) -> None:
    """Corre el instalador en un PowerShell aparte y a la vista (él cierra AltR, reemplaza el
    .exe y lo vuelve a abrir). Sólo Windows."""
    if os.name != "nt":
        raise UpdateError("Actualizar desde acá sólo funciona en Windows.")
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]
    try:
        subprocess.Popen(cmd, creationflags=flags, close_fds=True)
    except OSError as e:
        raise UpdateError(f"No pude abrir PowerShell: {e}") from None


def update_now() -> None:
    launch_installer(download_installer())
