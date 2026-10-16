$ErrorActionPreference = "Stop"

$pluginRoot = Split-Path -Parent $PSScriptRoot
$hostRoot = (Resolve-Path (Join-Path $pluginRoot "..\..")).Path
$venvPath = Join-Path $hostRoot ".venv"
$python = Join-Path $venvPath "Scripts\python.exe"

if (-not (Test-Path $python)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.11 -m venv $venvPath
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv $venvPath
    } else {
        throw "Python 3.11 or newer is required to create the RetroArchOverlay environment."
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create the RetroArchOverlay virtual environment."
    }
}

Push-Location $hostRoot
try {
    & $python -m pip install -e ".[dev]" -r (Join-Path $pluginRoot "scripts\requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "Could not install RetroArchOverlay and Dragon Quest V development dependencies."
    }
} finally {
    Pop-Location
}