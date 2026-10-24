param([ValidateSet('sdk', 'record', 'build', 'preflight')][string]$Step = 'preflight')
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Push-Location $taskRoot
try {
    . (Join-Path $taskRoot '.tools/local-env.ps1')
    $taskPython = Join-Path $taskRoot '.venv/Scripts/python.exe'
    if ($Step -eq 'sdk') {
        & $taskPython 'scripts/setup-local-tools.py' sdk
        if ($LASTEXITCODE -ne 0) { throw 'SDK installation failed; inspect .runtime/local-setup/android-sdk.log.' }
        & $taskPython 'scripts/android-build.py' preflight
    } elseif ($Step -eq 'record') {
        & './android/build.ps1' -RecordDependencies -ResolveDependencies
    } elseif ($Step -eq 'build') {
        & './android/build.ps1'
    } else {
        & $taskPython 'scripts/android-build.py' preflight
    }
    if ($LASTEXITCODE -ne 0) { throw 'Android setup/build step refused; preserve local evidence.' }
} finally { Pop-Location }
