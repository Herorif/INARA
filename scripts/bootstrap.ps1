param([switch]$Dev, [string]$Registry)
$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectDirectory
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed' }
}
$lock = if ($Dev) { 'requirements-dev.lock' } else { 'requirements-core.lock' }
& '.\.venv\Scripts\python.exe' -m pip install -r $lock
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed' }
$portableNode = Get-ChildItem -LiteralPath '.tools' -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like 'node-*-win-x64' } | Sort-Object Name -Descending | Select-Object -First 1
if ($portableNode) { $env:Path = $portableNode.FullName + ';' + $env:Path }
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw 'Install Node.js 24 LTS, then run this script again. The backend environment is ready.'
}
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
if ($Registry) {
    npm.cmd ci --registry=$Registry --replace-registry-host=always
} else {
    npm.cmd ci
}
if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed' }
if (-not (Test-Path -LiteralPath 'node_modules/electron/dist/electron.exe')) {
    node node_modules/electron/install.js
    if ($LASTEXITCODE -ne 0) { throw 'Electron runtime installation failed' }
}
npm.cmd run build
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
Write-Output 'INARA is ready. Run scripts/start.ps1. Local reminders work now; configure the AI provider when ready.'
