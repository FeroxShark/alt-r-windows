"""Motores TTS. Cada uno convierte un trozo de texto en un archivo de audio.

Interfaz: provider.synthesize(text, out_dir, name) -> Path (mp3 o wav).
Todo con la biblioteca estándar salvo edge-tts (que se importa recién al usarlo).
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from .config import Config


class TTSError(RuntimeError):
    """Falla de síntesis con un mensaje legible para el usuario."""


class EdgeProvider:
    def __init__(self, cfg: Config):
        self.voice = cfg.edge.voice
        self.pitch = cfg.edge.pitch
        self.proxy = cfg.edge.proxy or None
        self.speed = cfg.tts.speed

    @staticmethod
    def rate_string(speed: float) -> str:
        pct = max(-90, min(200, round((speed - 1.0) * 100)))
        return f"{pct:+d}%"

    def synthesize(self, text: str, out_dir: Path, name: str) -> Path:
        import asyncio

        try:
            import edge_tts
        except ImportError:
            raise TTSError("Falta el paquete edge-tts (pip install edge-tts).") from None
        out = Path(out_dir) / f"{name}.mp3"

        async def run():
            comm = edge_tts.Communicate(text, self.voice, rate=self.rate_string(self.speed),
                                        pitch=self.pitch, proxy=self.proxy)
            await comm.save(str(out))

        try:
            asyncio.run(run())
        except Exception as e:  # edge-tts lanza varias clases (aiohttp, NoAudioReceived...)
            raise TTSError(_edge_message(e, self.voice)) from e
        if not out.exists() or out.stat().st_size == 0:
            raise TTSError(f"Edge no devolvió audio (¿la voz '{self.voice}' existe?).")
        return out


def _edge_message(e: Exception, voice: str) -> str:
    name = type(e).__name__
    text = str(e)
    if name == "NoAudioReceived":
        return f"Edge no devolvió audio. Revisá que la voz '{voice}' exista (AltR --list-voices)."
    if "403" in text or "WSServerHandshakeError" in name:
        return ("Microsoft rechazó la conexión (403). Suele arreglarse actualizando edge-tts: "
                "pip install -U edge-tts (o bajando la última versión de AltR).")
    if any(k in name for k in ("Connect", "Timeout", "ClientOS")):
        return "No pude conectar con el servicio de voz de Edge. ¿Hay internet?"
    return f"Falló la voz de Edge: {name}: {text}"[:300]


class OpenAIProvider:
    def __init__(self, cfg: Config):
        c = cfg.openai
        self.url = c.base_url.rstrip("/") + "/audio/speech"
        self.model = c.model
        self.voice = c.voice
        self.instructions = c.instructions
        self.fmt = c.response_format
        self.timeout = c.timeout
        self.speed = cfg.tts.speed
        self.key_env = c.api_key_env.strip()

    def _api_key(self) -> str:
        if not self.key_env:
            return ""
        key = os.environ.get(self.key_env, "").strip()
        if not key:
            raise TTSError(f"Falta la variable de entorno {self.key_env} con tu API key "
                           f"(PowerShell: setx {self.key_env} \"tu-clave\", y volvé a iniciar sesión).")
        return key

    def synthesize(self, text: str, out_dir: Path, name: str) -> Path:
        body = {"model": self.model, "input": text, "voice": self.voice,
                "response_format": self.fmt, "speed": self.speed}
        if self.instructions:
            body["instructions"] = self.instructions
        headers = {"Content-Type": "application/json"}
        key = self._api_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(), headers=headers,
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                audio = r.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:200]
            e.close()
            hint = " (¿API key incorrecta?)" if e.code in (401, 403) else ""
            raise TTSError(f"La API respondió {e.code}{hint}: {detail}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise TTSError(f"No pude conectar con {self.url}: {e}") from e
        if not audio:
            raise TTSError("La API devolvió un audio vacío.")
        out = Path(out_dir) / f"{name}.{self.fmt}"
        out.write_bytes(audio)
        return out


class CommandProvider:
    def __init__(self, cfg: Config):
        c = cfg.command
        self.args = list(c.args)
        self.stdin = c.stdin
        self.ext = c.output_ext
        self.voice = c.voice
        self.timeout = c.timeout
        self.speed = cfg.tts.speed

    def _expand(self, arg: str, text: str, text_file: Path, output: Path) -> str:
        repl = {"{output}": str(output), "{text}": text, "{text_file}": str(text_file),
                "{voice}": self.voice, "{speed}": f"{self.speed:g}",
                "{length_scale}": f"{1.0 / self.speed:.4f}"}
        for k, v in repl.items():
            arg = arg.replace(k, v)
        return arg

    def synthesize(self, text: str, out_dir: Path, name: str) -> Path:
        out = Path(out_dir) / f"{name}.{self.ext}"
        text_file = Path(out_dir) / f"{name}.txt"
        text_file.write_text(text, encoding="utf-8")
        argv = [self._expand(a, text, text_file, out) for a in self.args]
        # Texto en UTF-8 pase lo que pase con el codepage: stdin va en bytes UTF-8, los argumentos
        # viajan como UTF-16 en Windows, y los programas Python hijos hablan UTF-8.
        kwargs = {"env": {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}}
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        try:
            proc = subprocess.run(argv, input=text.encode("utf-8") if self.stdin else None,
                                  capture_output=True, timeout=self.timeout, **kwargs)
        except (FileNotFoundError, NotADirectoryError) as e:
            raise TTSError(f"No encuentro el programa '{argv[0]}' ([command] args): {e}") from None
        except subprocess.TimeoutExpired:
            raise TTSError(f"El programa '{Path(argv[0]).name}' tardó más de {self.timeout} s.") from None
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", "replace").strip()[-200:]
            raise TTSError(f"'{Path(argv[0]).name}' terminó con error {proc.returncode}: {err}")
        if not out.exists() or out.stat().st_size == 0:
            raise TTSError(f"'{Path(argv[0]).name}' no generó el archivo de salida "
                           "(¿usaste {output} en args?).")
        return out


def make_provider(cfg: Config):
    return {"edge": EdgeProvider, "openai": OpenAIProvider,
            "command": CommandProvider}[cfg.tts.provider](cfg)


def list_edge_voices(prefix: str = "") -> list[str]:
    import asyncio

    import edge_tts

    voices = asyncio.run(edge_tts.list_voices())
    prefix = prefix.lower()
    return sorted(f"{v['ShortName']}  ({v['Gender']}, {v['Locale']})"
                  for v in voices if v["ShortName"].lower().startswith(prefix))
