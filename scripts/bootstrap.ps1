param([switch]$Dev, [string]$Registry, [switch]$ConfigureKeys)
$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectDirectory
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    # Packaging and part of the runtime tests are pinned to Python 3.12; prefer it through the launcher.
    $pythonExe = 'python'
    $pythonArgs = @()
    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        $launcherHas312 = $false
        try {
            $null = & py.exe -3.12 -c 'import sys' 2>&1
            $launcherHas312 = ($LASTEXITCODE -eq 0)
        } catch { $launcherHas312 = $false }
        if ($launcherHas312) { $pythonExe = 'py.exe'; $pythonArgs = @('-3.12') }
    }
    try {
        $pythonVersion = (& $pythonExe @pythonArgs -c 'import sys; print(*sys.version_info[:2], sep=chr(46))' | Select-Object -Last 1)
    } catch { $pythonVersion = $null }
    if (-not $pythonVersion -or $LASTEXITCODE -ne 0) { throw 'Python was not found. Install Python 3.12, then run this script again.' }
    if ($pythonVersion -ne '3.12') {
        Write-Warning ("Python $pythonVersion found, but JARVIS is built and tested on Python 3.12. " +
            '3.13 works for development, but packaging and some runtime tests expect 3.12. Install Python 3.12 for the supported setup.')
    }
    & $pythonExe @pythonArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed' }
}
$lock = if ($Dev) { 'requirements-dev.lock' } else { 'requirements-core.lock' }
& '.\.venv\Scripts\python.exe' -m pip install -r $lock
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed' }
if ($ConfigureKeys) {
    # Keys go to the encrypted profile store on stdin only (never argv, never .env).
    foreach ($key in @(@('anthropic_api_key','Anthropic API key'), @('gemini_api_key','Gemini API key'))) {
        $secure = Read-Host -AsSecureString -Prompt ($key[1] + ' (press Enter to skip)')
        if ($secure.Length -eq 0) { continue }
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try { $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
        $reply = $plain | & '.\.venv\Scripts\python.exe' -I -B 'scripts\jarvis-secrets.py' set $key[0] --verify
        $code = $LASTEXITCODE
        $plain = $null
        try { $message = ($reply | Select-Object -Last 1 | ConvertFrom-Json).message } catch { $message = 'The key tool did not answer.' }
        Write-Output ($key[1] + ': ' + $message)
        if ($code -ne 0 -and $code -ne 3) { Write-Warning ($key[1] + ' was not saved.') }
    }
}
$portableNode = Get-ChildItem -LiteralPath '.tools' -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like 'node-*-win-x64' } | Sort-Object Name -Descending | Select-Object -First 1
if ($portableNode) { $env:Path = $portableNode.FullName + ';' + $env:Path }
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw 'Install Node.js 24 LTS, then run this script again. The backend environment is ready.'
}
$nodeVersion = [version]((node --version).TrimStart('v'))
if ($nodeVersion -lt [version]'22.12.0') {
    throw "Node.js $nodeVersion is too old: Electron's installer needs Node.js 22.12 or newer. Install Node.js 24 LTS, then run this script again. The backend environment is ready."
}
$nodeNeedsFlags = $nodeVersion -lt [version]'22.18.0'
if ($nodeNeedsFlags) {
    Write-Warning "Node.js $nodeVersion works, but the client tests need extra flags below 22.18 (npm run test:client passes them). Node.js 24 LTS is recommended."
}
if ($Registry) {
    npm.cmd ci --registry=$Registry --replace-registry-host=always
} else {
    npm.cmd ci
}
if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed' }
if (-not (Test-Path -LiteralPath 'node_modules/electron/dist/electron.exe')) {
    if ($nodeNeedsFlags) {
        node --experimental-require-module node_modules/electron/install.js
    } else {
        node node_modules/electron/install.js
    }
    if ($LASTEXITCODE -ne 0) { throw 'Electron runtime installation failed' }
}
npm.cmd run build
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
Write-Output 'JARVIS is ready. Run scripts/start.ps1. Local reminders work now; add AI keys with scripts/bootstrap.ps1 -ConfigureKeys or scripts/jarvis-secrets.py (see docs/AI_PROVIDERS.md).'
