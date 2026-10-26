# AltR — leer en voz alta con un atajo (Windows)

Seleccioná texto en **cualquier programa** (navegador, PDF, Word, Discord…), apretá **Alt+R** y una voz
natural te lo lee. Apretá **Ctrl+Alt+R** para cortar. Vive como un ícono junto al reloj.

- Gratis y **sin cuenta ni clave**: usa por defecto las voces neuronales de Microsoft Edge (necesita internet).
- Configurable en un solo archivo: voz, velocidad, volumen, atajos.
- Enchufable: también funciona con **OpenAI** (o cualquier API compatible, local o remota) y con motores
  locales por línea de comandos como **Piper**. El modelo lo elegís vos en el config, sin tocar código.
- Nativo de Windows 10/11. No hace falta WSL ni instalar Python (si usás el `.exe`).

Es el port a Windows de la función "Alt+R" de un asistente de voz para Linux.

---

## Instalación (Windows 10/11)

### Opción A — un comando (recomendada)

Abrí **PowerShell** (no hace falta ser administrador) y pegá:

```powershell
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; irm https://raw.githubusercontent.com/FeroxShark/alt-r-windows/main/install.ps1 | iex
```

(La primera parte fuerza TLS 1.2: Windows PowerShell 5.1 a veces arranca con un TLS viejo que GitHub rechaza.
Sirve en Windows PowerShell 5.1 y en PowerShell 7. Se baja de la rama `main` y no del release porque GitHub
entrega los archivos de un release como binario y `irm` no los lee como texto.) Descarga `AltR.exe`, lo deja en `%LOCALAPPDATA%\AltR`, crea un acceso directo en el menú Inicio y lo arranca.
Para que además **arranque solo con Windows**:

```powershell
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; & ([scriptblock]::Create((irm https://raw.githubusercontent.com/FeroxShark/alt-r-windows/main/install.ps1))) -Autostart
```

### Opción B — bajar el `.exe` a mano

1. Entrá a la página de [Releases](https://github.com/FeroxShark/alt-r-windows/releases/latest) y bajá `AltR.exe`.
2. Ponelo en una carpeta que no se borre (por ejemplo `C:\Users\vos\AltR`) y hacé doble clic.
3. Para que arranque con Windows: clic derecho en el ícono de la bandeja → **Iniciar con Windows**.

> **Aviso de Windows (SmartScreen):** como el `.exe` no está firmado digitalmente, Windows puede decir
> "Windows protegió su PC". Tocá **Más información → Ejecutar de todas formas**. Algunos antivirus
> desconfían de los `.exe` hechos con PyInstaller; podés revisar el código y compilarlo vos (Opción C).

### Opción C — desde el código fuente

Necesitás Python 3.11 o más nuevo (`winget install Python.Python.3.12`).

```powershell
git clone https://github.com/FeroxShark/alt-r-windows
cd alt-r-windows
.\install.ps1 -Autostart      # crea un entorno propio en %LOCALAPPDATA%\AltR y lo arranca
```

O para probarlo sin instalar nada: `py -3 -m pip install .` y después `py -3 -m altr`.

> Si PowerShell dice que "la ejecución de scripts está deshabilitada", corré una vez
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` o ejecutá con
> `powershell -ExecutionPolicy Bypass -File .\install.ps1`.

### Primer uso

1. Después de instalar aparece un ícono (un parlante) junto al reloj. Si no lo ves, está dentro de la
   flechita **^** de la bandeja; arrastralo afuera para dejarlo fijo.
2. Seleccioná cualquier texto y apretá **Alt+R**. La primera vez tarda un segundo más.
3. **Ctrl+Alt+R** corta la lectura. Un Alt+R nuevo corta lo que esté sonando y lee lo nuevo.

---

## Atajos y menú de la bandeja

| Atajo (por defecto) | Qué hace |
|---|---|
| **Alt+R** | Lee el texto seleccionado (si no hay nada seleccionado, lee el portapapeles). |
| **Ctrl+Alt+R** | Corta la lectura. |

Clic derecho en el ícono: **Detener lectura** · **Leer el portapapeles** · **Abrir configuración** ·
**Recargar configuración** · **Abrir registro (log)** · **Iniciar con Windows** · **Salir**.
(Clic izquierdo = detener.) El ícono se pone verde mientras lee.

Cómo funciona: AltR simula un `Ctrl+C` en la ventana activa, lee lo copiado y te **devuelve el portapapeles
como estaba** (sólo texto; si tenías una imagen copiada, se pierde). En terminales (Windows Terminal, cmd,
PowerShell…) **no** manda `Ctrl+C`, porque ahí interrumpiría lo que esté corriendo: copiá vos el texto y
apretá Alt+R para leer el portapapeles.

---

## Configuración

El archivo está en **`%APPDATA%\AltR\config.toml`** (se crea solo la primera vez, con comentarios).
Ábrilo desde el ícono → *Abrir configuración*, editalo, guardalo y elegí *Recargar configuración*.
Lo que borres toma el valor por defecto. Si te equivocás, AltR te avisa y sigue con la configuración anterior.

### `[general]`

| Campo | Por defecto | Qué es |
|---|---|---|
| `hotkey` | `"alt+r"` | Atajo para leer. Modificadores `alt`, `ctrl`, `shift`, `win` + una tecla (letra, número, `f1`…`f24`, `space`, `enter`, flechas…). Ej.: `"ctrl+alt+l"`. |
| `stop_hotkey` | `"ctrl+alt+r"` | Atajo para cortar. `""` = ninguno. |
| `clipboard_fallback` | `true` | Sin selección, leer el portapapeles. |
| `restore_clipboard` | `true` | Devolver el portapapeles como estaba tras copiar la selección. |
| `clipboard_only_apps` | terminales | Programas donde no se manda `Ctrl+C` (se lee el portapapeles). |
| `notifications` | `true` | Globos de aviso cuando algo falla. |

### `[text]`

| Campo | Por defecto | Qué es |
|---|---|---|
| `max_chars` | `20000` | Máximo de caracteres por lectura. |
| `strip_markdown` | `true` | Quita `#`, `*`, `` ` ``, `[texto](enlace)` para que no los deletree. |
| `read_urls` | `false` | `false` = las direcciones web se dicen "enlace". |

### `[tts]` — lo común a todos los motores

| Campo | Por defecto | Qué es |
|---|---|---|
| `provider` | `"edge"` | `"edge"`, `"openai"` o `"command"`. |
| `speed` | `1.0` | Velocidad: `1.2` = 20 % más rápido, `0.8` = más lento. (0.25–4.0) |
| `volume` | `100` | Volumen de AltR, 0–100. |

### Motor `edge` (gratis, sin clave)

```toml
[tts]
provider = "edge"
speed = 1.15

[edge]
voice = "es-AR-ElenaNeural"   # argentina, mujer
pitch = "+0Hz"
proxy = ""
```

Voces en español que andan bien: `es-AR-ElenaNeural`, `es-AR-TomasNeural`, `es-ES-ElviraNeural`,
`es-ES-AlvaroNeural`, `es-MX-DaliaNeural`, `es-MX-JorgeNeural`, `es-CO-SalomeNeural`, `es-US-PalomaNeural`.
Las "multilingües" (`en-US-AvaMultilingualNeural`, `en-US-AndrewMultilingualNeural`) leen bien español e inglés mezclados.
Lista completa: `AltR.exe --list-voices es-` (o `--list-voices` solo, para todas; abre un bloc de notas con el resultado).

### Motor `openai` (OpenAI o cualquier API compatible)

```toml
[tts]
provider = "openai"

[openai]
base_url = "https://api.openai.com/v1"
model = "gpt-4o-mini-tts"       # o "tts-1", "tts-1-hd"…
voice = "coral"
api_key_env = "OPENAI_API_KEY"  # NOMBRE de la variable; la clave NO va en este archivo
instructions = "Hablá en español rioplatense, tranquilo y claro."   # sólo gpt-4o-mini-tts
```

La clave se guarda como variable de entorno. En PowerShell:

```powershell
setx OPENAI_API_KEY "sk-..."
```

y **cerrá sesión de Windows y volvé a entrar** (o salí de AltR y volvelo a abrir desde una consola nueva) para que la tome.

Servidores propios o locales que hablan el mismo protocolo (`/v1/audio/speech`), por ejemplo
[Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI), LocalAI u openedai-speech:

```toml
[openai]
base_url = "http://localhost:8880/v1"
model = "kokoro"
voice = "ef_dora"
api_key_env = ""                 # vacío = sin clave
```

Para usar **otro modelo** alcanza con cambiar `model` y `voice` a lo que acepte tu servidor.

### Motor `command` (Piper u otro programa local)

Cada trozo de texto se le pasa a un programa tuyo, que tiene que generar un `.wav` o `.mp3`.
Ejemplo con [Piper](https://github.com/rhasspy/piper) (descargá `piper.exe` y una voz `.onnx`; funciona sin internet):

```toml
[tts]
provider = "command"

[command]
args = ["C:/piper/piper.exe", "--model", "C:/piper/es_AR-daniela-high.onnx",
        "--length_scale", "{length_scale}", "--output_file", "{output}"]
stdin = true          # Piper recibe el texto por stdin
output_ext = "wav"
```

Se reemplazan: `{output}` (archivo a generar), `{text}`, `{text_file}`, `{voice}` (el campo `voice` de la sección),
`{speed}` y `{length_scale}` (= 1 / velocidad, lo que usa Piper). Usá barras normales `/` en las rutas.

### `[lexicon]` — pronunciación

Para palabras que el motor lee mal, escribí cómo suenan:

```toml
[lexicon]
github = "guitjab"
wifi = "uaifai"
```

---

## Línea de comandos

```text
AltR.exe                        arranca la aplicación residente (lo normal)
AltR.exe --check                valida el config
AltR.exe --say "Hola" [--out a.mp3]   lee un texto (o lo guarda) sin atajos ni bandeja: sirve para probar voces
AltR.exe --list-voices es-AR    voces de Edge
AltR.exe --config-path          dónde está el config
AltR.exe --install-autostart / --remove-autostart
AltR.exe --config otro.toml     usa otro archivo de configuración
```

Con la instalación desde código fuente: `py -3 -m altr …`. Sin consola (el `.exe` no tiene), los resultados de
`--check`, `--list-voices` y `--version` se abren en un bloc de notas.

---

## Problemas comunes

- **Alt+R choca con NVIDIA.** El overlay de rendimiento de la NVIDIA App / GeForce Experience usa Alt+R por
  defecto y se queda con el atajo (AltR lo avisa con un globo y en el registro: «No pude registrar el atajo»).
  Dos salidas: (1) cambiar el atajo de AltR: ícono → *Abrir configuración* → `hotkey = "ctrl+alt+l"` → ícono →
  *Recargar configuración*; o (2) apagar el de NVIDIA: NVIDIA App → *Configuración* → *Funciones* → *Overlay* →
  *Atajos de teclado* (o GeForce Experience → engranaje → *Superposición en el juego* → *Atajos de teclado*) y
  cambiá o quitá «Mostrar/Ocultar el rendimiento».
- **Con `alt+<letra>` en Firefox no lee (o se abre la barra de menús).** Firefox muestra su barra de menús al
  soltar Alt y esa pulsación se come el Ctrl+C. AltR mete una tecla intermedia para evitarlo; si en tu caso igual
  pasa, usá un atajo con `ctrl` (`"ctrl+alt+l"`), que Firefox no interpreta como menú.
- **Alt+R no hace nada.** Mirá el aviso del globo o el registro (ícono → *Abrir registro*). Si dice "otro programa ya
  usa ese atajo", cambiá `hotkey` en el config (por ejemplo `"ctrl+alt+l"`) y recargá.
- **Dice "No hay texto seleccionado".** Algunos programas no responden a `Ctrl+C` (juegos, apps con permisos de
  administrador: Windows no deja que un programa normal le mande teclas a uno elevado). Copiá el texto a mano y
  apretá Alt+R: lee el portapapeles.
- **No suena nada / error de conexión.** El motor `edge` necesita internet. Probá `AltR.exe --say "hola"`. Si Microsoft
  responde 403, actualizá AltR (a veces cambian el servicio y `edge-tts` se actualiza).
- **Al soltar Alt se abre un menú del programa.** AltR intenta evitarlo; si te pasa en algún programa, usá un atajo con
  `ctrl` (por ejemplo `"ctrl+alt+r"`).
- **El portapapeles quedó con otra cosa.** Sólo se restaura texto. Poné `restore_clipboard = false` si preferís que
  quede lo seleccionado.
- **Hay pausas entre frases.** Cada frase se genera por separado; con motores lentos (una API remota lejana) puede
  haber una pausa corta. Probá un motor más rápido o más cercano.
- **Sale "Falta la variable de entorno …".** Creaste la clave con `setx` pero no volviste a iniciar sesión.
- **"Windows protegió su PC".** Ver el aviso de SmartScreen más arriba.
- **Quiero ver qué pasa.** El registro está en `%APPDATA%\AltR\altr.log`.

---

## Desinstalar

Con el instalador:

```powershell
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; & ([scriptblock]::Create((irm https://raw.githubusercontent.com/FeroxShark/alt-r-windows/main/install.ps1))) -Uninstall
```

(agregá `-Purge` para borrar también tu configuración en `%APPDATA%\AltR`). A mano: ícono → *Iniciar con Windows*
(destildar) → *Salir*, y borrá `%LOCALAPPDATA%\AltR` y `%APPDATA%\AltR`.

---

## Para desarrolladores

```text
altr/
  cli.py        línea de comandos y arranque
  app.py        aplicación residente (atajos + lector + bandeja)
  reader.py     trocea, sintetiza por adelantado y reproduce; una lectura nueva corta la anterior
  providers.py  motores: edge, openai (API compatible), command
  config.py     lectura y validación del config (los valores por defecto salen de config.default.toml)
  text.py       limpieza de texto y troceado por frases
  hotkeys.py    parseo de atajos ("ctrl+alt+r")
  win.py        capa de Windows con ctypes: portapapeles, SendInput, RegisterHotKey, reproducción MCI, autoarranque
  tray.py       ícono de bandeja (pystray + Pillow)
tests/          unittest; todo menos test_win.py corre en cualquier sistema
altr.spec       PyInstaller;  install.ps1  instalador;  .github/workflows/build.yml  CI + release
```

```powershell
python -m unittest discover -s tests -t . -v      # tests (los de Windows sólo corren en Windows)
ALTR_TEST_NETWORK=1 python -m unittest tests.test_providers   # incluye una síntesis real con Edge
.\scripts\build-exe.ps1                           # arma dist\AltR.exe
```

**Publicar una versión:** subí el número en `altr/__init__.py`, hacé `git tag v0.1.0 && git push --tags`. El workflow
prueba en Windows, arma `AltR.exe` y crea el release con `AltR.exe`, `install.ps1` y `config.default.toml`.

Agregar un motor: una clase con `synthesize(text, out_dir, name) -> Path` en `providers.py` y una entrada en
`make_provider` y en `PROVIDERS` (`config.py`).

## Licencia

[MIT](LICENSE).
