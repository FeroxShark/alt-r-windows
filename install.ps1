<#
.SYNOPSIS
  Instala (o desinstala) AltR: lectura en voz alta con un atajo global.

.EXAMPLE
  # Instalar la última versión y arrancar con Windows:
  .\install.ps1 -Autostart

.EXAMPLE
  # Desinstalar (agregá -Purge para borrar también tu config):
  .\install.ps1 -Uninstall

.NOTES
  Sin permisos de administrador. Instala en %LOCALAPPDATA%\AltR.
  Dos modos:
   - Descarga el AltR.exe del último release de GitHub (por defecto).
   - Desde el código fuente (si el script está junto a pyproject.toml): crea un
     entorno de Python propio. Necesita Python 3.11 o más nuevo.
#>
[CmdletBinding()]
param(
    [switch]$Autostart,    # arrancar con Windows
    [switch]$FromSource,   # exigir el modo código fuente (falla si no está junto a pyproject.toml)
    [switch]$Uninstall,    # quitar AltR
    [switch]$Purge,        # con -Uninstall: borrar también la configuración
    [string]$Repo = "FeroxShark/alt-r-windows",
    [string]$Version = "latest"
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

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
        Write-Host "Tu configuración quedó en $DataDir (agregá -Purge para borrarla)."
    }
    return
}

$SourceDir = $null
if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot "pyproject.toml"))) { $SourceDir = $PSScriptRoot }
if ($FromSource -and -not $SourceDir) {
    throw "-FromSource necesita que install.ps1 esté dentro de la carpeta del proyecto (junto a pyproject.toml)."
}

Stop-AltR
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

if ($SourceDir) {
    Write-Host "Instalando desde el código fuente ($SourceDir)..." -ForegroundColor Cyan
    $py = $null
    foreach ($cand in @(@("py", "-3"), @("python"))) {
        try {
            $exe = $cand[0]; $extra = @($cand | Select-Object -Skip 1)
            $ok = & $exe @extra -c "import sys; print(int(sys.version_info >= (3, 11)))" 2>$null
            if ($ok -eq "1") { $py = $cand; break }
        } catch { }
    }
    if (-not $py) {
        throw "No encontré Python 3.11 o más nuevo. Instalalo con:  winget install Python.Python.3.12  (y abrí una PowerShell nueva), o usá el modo .exe."
    }
    $venv = Join-Path $InstallDir "venv"
    & $py[0] @($py | Select-Object -Skip 1) -m venv $venv
    $vpy = Join-Path $venv "Scripts\python.exe"
    & $vpy -m pip --quiet install --upgrade pip
    & $vpy -m pip --quiet install --upgrade $SourceDir
    if ($LASTEXITCODE -ne 0) { throw "Falló la instalación de los paquetes de Python." }
    $Target = Join-Path $venv "Scripts\pythonw.exe"
    $TargetArgs = "-m altr"
} else {
    $Target = Join-Path $InstallDir "AltR.exe"
    $TargetArgs = ""
    if ($Version -eq "latest") {
        $url = "https://github.com/$Repo/releases/latest/download/AltR.exe"
    } else {
        $url = "https://github.com/$Repo/releases/download/$Version/AltR.exe"
    }
    Write-Host "Descargando $url ..." -ForegroundColor Cyan
    Invoke-WebRequest -Uri $url -OutFile $Target -UseBasicParsing
    Unblock-File -Path $Target
}

# Acceso directo en el menú Inicio
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
    Write-Host "AltR arrancará con Windows."
}

if ($TargetArgs) {
    Start-Process -FilePath $Target -ArgumentList $TargetArgs -WorkingDirectory $InstallDir
} else {
    Start-Process -FilePath $Target -WorkingDirectory $InstallDir
}
Write-Host ""
Write-Host "Listo. AltR está corriendo (ícono junto al reloj, tal vez dentro de la flechita ^)." -ForegroundColor Green
Write-Host "Seleccioná texto en cualquier programa y apretá Alt+R."
Write-Host "Configuración: $DataDir\config.toml  (clic derecho en el ícono > Abrir configuración)"
