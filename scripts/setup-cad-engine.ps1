<#
.SYNOPSIS
Sets up the JARVIS CAD engine (docs/CAD_STUDIO.md): build123d in .venv-cad at the repo root.

.DESCRIPTION
You run this yourself; JARVIS never runs it and never downloads anything for the CAD engine.
It is safe to run again: if .venv-cad already passes the smoke check it says so and stops.

  1. Finds Python 3.13 (the py launcher's -3.13, else python on PATH). Nothing is installed
     system-wide; without Python 3.13 it stops.
  2. Creates .venv-cad at the repo root.
  3. Installs requirements-cad-kernel.lock with --require-hashes --only-binary=:all:
     (57 wheels, about 227 MB to download) after you type Y. Use -Yes to skip the prompt.
  4. Smoke check: Box(20,20,10) - Cylinder(3,10) has a volume of about 3717.3 mm3.

It never changes PATH, system settings, the core's .venv or any other environment.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File scripts\setup-cad-engine.ps1
#>
[CmdletBinding()]
param(
    [switch]$Yes
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 3.0

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $RepoRoot '.venv-cad'
$VenvPython = Join-Path $Venv 'Scripts\python.exe'
$Lock = Join-Path $RepoRoot 'requirements-cad-kernel.lock'
$DownloadSize = 'about 227 MB'
$SmokeCode = 'from build123d import Box, Cylinder; v = (Box(20, 20, 10) - Cylinder(3, 10)).volume; print(round(v, 1)); raise SystemExit(0 if abs(v - 3717.3) < 0.5 else 1)'

function Step([string]$Number, [string]$Text) { Write-Host ""; Write-Host "[$Number/4] $Text" -ForegroundColor Cyan }
function Done([string]$Text) { Write-Host "  Done: $Text" -ForegroundColor Green }
function Fail([string]$Text) { Write-Host "  Stopped: $Text" -ForegroundColor Red; exit 1 }

function Test-Smoke {
    if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) { return $false }
    $output = & $VenvPython -I -c $SmokeCode 2>$null
    if ($LASTEXITCODE -eq 0) { Write-Host "  Smoke check volume: $output mm3"; return $true }
    return $false
}

Write-Host "CAD engine setup for JARVIS"
Write-Host "Environment: $Venv"

if (Test-Smoke) {
    Write-Host "The CAD engine is already set up and its smoke check passes. Nothing to do." -ForegroundColor Green
    exit 0
}

if (-not (Test-Path -LiteralPath $Lock -PathType Leaf)) { Fail "$Lock is missing." }
$packages = @(Get-Content -LiteralPath $Lock | Where-Object { $_ -match '^[A-Za-z0-9]' }).Count

# --- 1. Python 3.13 -------------------------------------------------------------------------
Step 1 "Python 3.13"
$pythonExe = $null
$pythonArgs = @()
if (Get-Command py.exe -ErrorAction SilentlyContinue) {
    $null = & py.exe -3.13 -c 'import sys' 2>$null
    if ($LASTEXITCODE -eq 0) { $pythonExe = 'py.exe'; $pythonArgs = @('-3.13') }
}
if (-not $pythonExe -and (Get-Command python.exe -ErrorAction SilentlyContinue)) {
    $version = (& python.exe -c 'import sys; print(*sys.version_info[:2], sep=chr(46))' 2>$null | Select-Object -Last 1)
    if ($LASTEXITCODE -eq 0 -and $version -eq '3.13') { $pythonExe = 'python.exe' }
}
if (-not $pythonExe) { Fail "Python 3.13 was not found. Install Python 3.13 for Windows x64, then run this again. Nothing was changed." }
Done "$pythonExe $($pythonArgs -join ' ')"

# --- 2. .venv-cad -----------------------------------------------------------------------------
Step 2 ".venv-cad"
if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    & $pythonExe @pythonArgs -m venv $Venv
    if ($LASTEXITCODE -ne 0) { Fail "creating $Venv failed (exit code $LASTEXITCODE)." }
    Done "$Venv"
} else {
    Write-Host "  Already exists; its packages will be installed again from the lock."
}

# --- 3. Packages ------------------------------------------------------------------------------
Step 3 "Packages from requirements-cad-kernel.lock"
Write-Host "  This downloads $packages pinned wheels from PyPI ($DownloadSize) into $Venv."
if (-not $Yes) {
    $answer = Read-Host "  Type Y to continue"
    if ($answer -ne 'Y' -and $answer -ne 'y') { Fail "you did not type Y. Nothing was downloaded." }
}
& $VenvPython -m pip install --use-feature=truststore --require-hashes --only-binary=:all: --no-deps -r $Lock
if ($LASTEXITCODE -ne 0) { Fail "pip install failed (exit code $LASTEXITCODE)." }
Done "$packages packages"

# --- 4. Smoke check ---------------------------------------------------------------------------
Step 4 "Smoke check"
if (-not (Test-Smoke)) { Fail "Box(20,20,10) - Cylinder(3,10) did not give about 3717.3 mm3. See docs/CAD_STUDIO.md, Troubleshooting." }
Write-Host ""
Write-Host "The CAD engine is set up. Restart JARVIS to use it in Live design." -ForegroundColor Green
