# Arma dist\AltR.exe en tu PC (necesita Python 3.11+). Uso:  .\scripts\build-exe.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
python -m venv .venv-build
$py = ".\.venv-build\Scripts\python.exe"
& $py -m pip --quiet install --upgrade pip
& $py -m pip --quiet install . pyinstaller
& $py -m PyInstaller --noconfirm --clean altr.spec
Write-Host "Listo: dist\AltR.exe"
