param([switch]$Dev, [switch]$BackendOnly)
$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectDirectory
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    throw 'Run scripts/bootstrap.ps1 first.'
}
if ($BackendOnly) {
    & '.\.venv\Scripts\python.exe' backend/server.py
    exit $LASTEXITCODE
}
$portableNode = Get-ChildItem -LiteralPath '.tools' -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like 'node-*-win-x64' } | Sort-Object Name -Descending | Select-Object -First 1
if ($portableNode) { $env:Path = $portableNode.FullName + ';' + $env:Path }
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw 'Install Node.js 24 LTS or run bootstrap in a configured terminal.'
}
$command = if ($Dev) { 'dev' } else { 'start' }
$env:ELECTRON_RUN_AS_NODE = $null
npm.cmd run $command
exit $LASTEXITCODE
