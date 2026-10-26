param([switch]$Dev, [string]$Registry, [switch]$ConfigureKeys)
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
if ($ConfigureKeys) {
    # Keys go to the encrypted profile store on stdin only (never argv, never .env).
    foreach ($key in @(@('anthropic_api_key','Anthropic API key'), @('gemini_api_key','Gemini API key'))) {
        $secure = Read-Host -AsSecureString -Prompt ($key[1] + ' (press Enter to skip)')
        if ($secure.Length -eq 0) { continue }
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try { $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
        $reply = $plain | & '.\.venv\Scripts\python.exe' -I -B 'scripts\inara-secrets.py' set $key[0] --verify
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
Write-Output 'INARA is ready. Run scripts/start.ps1. Local reminders work now; add AI keys with scripts/bootstrap.ps1 -ConfigureKeys or scripts/inara-secrets.py (see docs/AI_PROVIDERS.md).'
