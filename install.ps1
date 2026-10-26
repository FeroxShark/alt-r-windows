<#
.SYNOPSIS
  Instala (o desinstala) AltR: lectura en voz alta con un atajo global.

.EXAMPLE
  # Instalar la ultima version y arrancar (sin parametros: sirve con "irm | iex"):
  irm https://raw.githubusercontent.com/FeroxShark/alt-r-windows/main/install.ps1 | iex

.EXAMPLE
  # Con parametros (desde archivo o con scriptblock):
  .\install.ps1 -Autostart
  & ([scriptblock]::Create((irm <url>))) -Autostart

.EXAMPLE
  # Con "irm | iex" los parametros van por variables de entorno:
  $env:ALTR_AUTOSTART = "1"; irm <url> | iex

.NOTES
  Parametros: -Autostart, -FromSource, -Uninstall, -Purge, -Repo, -Version, -ExePath.
  Variables equivalentes: ALTR_AUTOSTART, ALTR_FROMSOURCE, ALTR_UNINSTALL, ALTR_PURGE,
  ALTR_REPO, ALTR_VERSION, ALTR_EXE (usar un AltR.exe local en vez de descargarlo).

  Sin permisos de administrador. Instala en %LOCALAPPDATA%\AltR.
  Dos modos:
   - Descarga el AltR.exe del ultimo release de GitHub (por defecto).
   - Desde el codigo fuente (si el script esta junto a pyproject.toml): crea un
     entorno de Python propio. Necesita Python 3.11 o mas nuevo.

  Este archivo es a proposito ASCII puro, sin BOM y sin bloque param() de primer nivel:
  asi lo puede leer y ejecutar "irm | iex" en Windows PowerShell 5.1 y en PowerShell 7.
  Todo corre dentro de una funcion: no deja variables ni $ErrorActionPreference en tu sesion,
  y nunca llama a "exit" (cerraria la consola).
#>

function Install-AltR {
    [CmdletBinding()]
    param(
        [switch]$Autostart,    # arrancar con Windows
        [switch]$FromSource,   # exigir el modo codigo fuente (falla si no esta junto a pyproject.toml)
        [switch]$Uninstall,    # quitar AltR
        [switch]$Purge,        # con -Uninstall: borrar tambien la configuracion
        [string]$Repo = "FeroxShark/alt-r-windows",
        [string]$Version = "latest",
        [string]$ExePath = "",  # AltR.exe local (en vez de descargarlo)
        [string]$ScriptDir = ""
    )

    $ErrorActionPreference = "Stop"
    # Windows PowerShell 5.1 puede arrancar con TLS 1.0/1.1, que GitHub rechaza.
    try {
        $tls = [Net.SecurityProtocolType]::Tls12
        try { $tls = $tls -bor [Net.SecurityProtocolType]::Tls13 } catch { }
        [Net.ServicePointManager]::SecurityProtocol = $tls
    } catch { }
    $ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest es muy lento en 5.1 con la barra

    $InstallDir = Join-Path $env:LOCALAPPDATA "AltR"
    $DataDir    = Join-Path $env:APPDATA "AltR"
    $Shortcut   = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\AltR.lnk"
    $RunKey     = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"

    function Stop-AltR {
        Get-Process -Name "AltR" -ErrorAction SilentlyContinue | Stop-Process -Force
        Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -match " -m altr" } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
        Start-Sleep -Milliseconds 400
    }

    if ($Uninstall) {
        Stop-AltR
        Remove-ItemProperty -Path $RunKey -Name "AltR" -ErrorAction SilentlyContinue
        Remove-Item $Shortcut -Force -ErrorAction SilentlyContinue
        Remove-Item $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
        if ($Purge) { Remove-Item $DataDir -Recurse -Force -ErrorAction SilentlyContinue }
        Write-Host "AltR desinstalado." -ForegroundColor Green
        if (-not $Purge -and (Test-Path $DataDir)) {
            Write-Host "Tu configuracion quedo en $DataDir (agrega -Purge para borrarla)."
        }
        return
    }

    # Modo codigo fuente: solo si corre desde un archivo junto a pyproject.toml.
    $SourceDir = $null
    if ($ScriptDir -and (Test-Path (Join-Path $ScriptDir "pyproject.toml"))) { $SourceDir = $ScriptDir }
    if ($FromSource -and -not $SourceDir) {
        throw "-FromSource necesita que install.ps1 este dentro de la carpeta del proyecto (junto a pyproject.toml)."
    }
    if ($ExePath) { $SourceDir = $null }

    Stop-AltR
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

    if ($SourceDir) {
        Write-Host "Instalando desde el codigo fuente ($SourceDir)..." -ForegroundColor Cyan
        $py = $null
        foreach ($cand in @(@("py", "-3"), @("python"))) {
            try {
                $exe = $cand[0]; $extra = @($cand | Select-Object -Skip 1)
                $ok = & $exe @extra -c "import sys; print(int(sys.version_info >= (3, 11)))" 2>$null
                if ($ok -eq "1") { $py = $cand; break }
            } catch { }
        }
        if (-not $py) {
            throw "No encontre Python 3.11 o mas nuevo. Instalalo con:  winget install Python.Python.3.12  (y abri una PowerShell nueva), o usa el modo .exe."
        }
        $venv = Join-Path $InstallDir "venv"
        & $py[0] @($py | Select-Object -Skip 1) -m venv $venv
        $vpy = Join-Path $venv "Scripts\python.exe"
        & $vpy -m pip --quiet install --upgrade pip
        & $vpy -m pip --quiet install --upgrade $SourceDir
        if ($LASTEXITCODE -ne 0) { throw "Fallo la instalacion de los paquetes de Python." }
        $Target = Join-Path $venv "Scripts\pythonw.exe"
        $TargetArgs = "-m altr"
    } else {
        $Target = Join-Path $InstallDir "AltR.exe"
        $TargetArgs = ""
        if ($ExePath) {
            Copy-Item -Path $ExePath -Destination $Target -Force
        } else {
            if ($Version -eq "latest") {
                $url = "https://github.com/$Repo/releases/latest/download/AltR.exe"
            } else {
                $url = "https://github.com/$Repo/releases/download/$Version/AltR.exe"
            }
            Write-Host "Descargando $url ..." -ForegroundColor Cyan
            Invoke-WebRequest -Uri $url -OutFile $Target -UseBasicParsing
        }
        Unblock-File -Path $Target
    }

    # Acceso directo en el menu Inicio
    $sh = New-Object -ComObject WScript.Shell
    $lnk = $sh.CreateShortcut($Shortcut)
    $lnk.TargetPath = $Target
    $lnk.Arguments = $TargetArgs
    $lnk.WorkingDirectory = $InstallDir
    $lnk.Description = "AltR - lectura en voz alta"
    $lnk.Save()

    if ($Autostart) {
        $cmd = if ($TargetArgs) { "`"$Target`" $TargetArgs" } else { "`"$Target`"" }
        New-Item -Path $RunKey -Force | Out-Null
        Set-ItemProperty -Path $RunKey -Name "AltR" -Value $cmd
        Write-Host "AltR arrancara con Windows."
    }

    if ($TargetArgs) {
        Start-Process -FilePath $Target -ArgumentList $TargetArgs -WorkingDirectory $InstallDir
    } else {
        Start-Process -FilePath $Target -WorkingDirectory $InstallDir
    }
    Write-Host ""
    Write-Host "Listo. AltR esta corriendo (icono junto al reloj, tal vez dentro de la flechita ^)." -ForegroundColor Green
    Write-Host "Selecciona texto en cualquier programa y aprieta Ctrl+Alt+R."
    Write-Host "Configuracion: $DataDir\config.toml  (clic derecho en el icono > Abrir configuracion)"
}

# --- Punto de entrada. Sin param() de primer nivel: con "irm | iex" no existe $PSScriptRoot
# ni se pueden pasar parametros, asi que se leen de $args (archivo / scriptblock) y de
# variables de entorno ALTR_* (irm | iex).
function Invoke-AltRMain {
    param([object[]]$Arguments, [string]$ScriptDir)
    $p = @{}
    foreach ($n in "AUTOSTART", "FROMSOURCE", "UNINSTALL", "PURGE") {
        $v = [Environment]::GetEnvironmentVariable("ALTR_$n")
        if ($v -and $v -notin @("0", "false", "no")) { $p[$n.Substring(0, 1) + $n.Substring(1).ToLower()] = [switch]$true }
    }
    if ($p.ContainsKey("Fromsource")) { $p["FromSource"] = $p["Fromsource"]; $p.Remove("Fromsource") }
    foreach ($pair in @(@("REPO", "Repo"), @("VERSION", "Version"), @("EXE", "ExePath"))) {
        $v = [Environment]::GetEnvironmentVariable("ALTR_" + $pair[0])
        if ($v) { $p[$pair[1]] = $v }
    }
    $list = @($Arguments)
    for ($i = 0; $i -lt $list.Count; $i++) {
        $a = [string]$list[$i]
        if ($a -notmatch '^-(\w+)$') { throw "Argumento no reconocido: $a" }
        $name = $Matches[1]
        $canon = @("Autostart", "FromSource", "Uninstall", "Purge", "Repo", "Version", "ExePath") |
            Where-Object { $_ -ieq $name }
        if (-not $canon) { throw "Parametro no reconocido: -$name" }
        if ($canon -in @("Repo", "Version", "ExePath")) { $i++; $p[$canon] = [string]$list[$i] }
        else { $p[$canon] = [switch]$true }
    }
    if ($ScriptDir) { $p["ScriptDir"] = $ScriptDir }
    Install-AltR @p
}

$altrDir = ""
if ($PSScriptRoot) { $altrDir = $PSScriptRoot }
try {
    Invoke-AltRMain -Arguments $args -ScriptDir $altrDir
} finally {
    # no dejar las funciones en la sesion de quien uso "irm | iex"
    Remove-Item Function:\Install-AltR, Function:\Invoke-AltRMain -ErrorAction SilentlyContinue
}
