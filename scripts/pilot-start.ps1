param([string]$PythonExecutable, [Parameter(Mandatory=$true)][string]$PilotDataDirectory)
$ErrorActionPreference = 'Stop'
$taskPilotRoot = Split-Path -Parent $PSScriptRoot
$taskManifestPath = Join-Path $taskPilotRoot 'desktop-pilot.json'
if ((Get-Item -LiteralPath $taskManifestPath).Length -gt 4194304) { throw 'Pilot manifest is excessive.' }
$taskManifest = Get-Content -LiteralPath $taskManifestPath -Raw | ConvertFrom-Json
if ($taskManifest.kind -eq 'desktop-core-pilot') {
    if ($PythonExecutable) { throw 'A bundled core pilot never substitutes development Python.' }
    $taskPython = Join-Path $taskPilotRoot 'runtime/python/python.exe'
    $taskBootstrap = @($taskManifest.files | Where-Object { $_.path -ceq 'runtime/python/python.exe' })
    if ($taskBootstrap.Count -ne 1 -or (Get-FileHash -LiteralPath $taskPython -Algorithm SHA256).Hash.ToLowerInvariant() -cne $taskBootstrap[0].sha256) { throw 'Bundled Python bootstrap integrity failed.' }
} else {
    if (!$PythonExecutable) { throw 'This workspace-only pilot needs an explicit configured Python executable.' }
    $taskPython = (Resolve-Path -LiteralPath $PythonExecutable).Path
}
if ([System.IO.Path]::GetFileName($taskPython) -ne 'python.exe') { throw 'Provide a configured Python 3.12 python.exe explicitly; no runtime is downloaded.' }
& $taskPython -I -B -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3,12) else 1)'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 is required.' }
& $taskPython -I -B (Join-Path $PSScriptRoot 'desktop-package.py') verify --directory $taskPilotRoot
if ($LASTEXITCODE -ne 0) { throw 'Pilot integrity failed; preserve the pilot and existing profiles.' }
$taskPilotData = [System.IO.Path]::GetFullPath($PilotDataDirectory)
if (!$taskPilotData.StartsWith([System.IO.Path]::GetPathRoot($taskPilotData)) -or (Test-Path -LiteralPath $taskPilotData) -or $taskPilotData.StartsWith($taskPilotRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase) -or $taskPilotData -eq $taskPilotRoot) {
    throw 'Choose a NEW isolated data directory outside this pilot. Existing profiles are never adopted or migrated.'
}
$taskParent = Split-Path -Parent $taskPilotData
while ($taskParent) {
    if ((Test-Path -LiteralPath $taskParent) -and ((Get-Item -LiteralPath $taskParent).Attributes -band [System.IO.FileAttributes]::ReparsePoint)) { throw 'Linked pilot data parent is not accepted.' }
    $taskParent = Split-Path -Parent $taskParent
}
New-Item -ItemType Directory -Path $taskPilotData | Out-Null
$taskEnvironment = @('JARVIS_DATA_DIR','JARVIS_SETTINGS_FILE','JARVIS_PROJECT_ROOT','JARVIS_LEGACY_DATA_DIR','JARVIS_DESKTOP_DATA_DIR','PYTHONDONTWRITEBYTECODE','JARVIS_DEV_SERVER','ELECTRON_RUN_AS_NODE')
# Pre-rename INARA_* names are still read as a one-release fallback: clear them for the pilot.
$taskEnvironment += @('INARA_DATA_DIR','INARA_SETTINGS_FILE','INARA_PROJECT_ROOT','INARA_LEGACY_DATA_DIR','INARA_DESKTOP_DATA_DIR','INARA_DEV_SERVER')
$taskPrevious = @{}
foreach ($taskName in $taskEnvironment) { $taskPrevious[$taskName] = [Environment]::GetEnvironmentVariable($taskName,'Process') }
try {
    $env:JARVIS_DATA_DIR = Join-Path $taskPilotData 'database'
    $env:JARVIS_SETTINGS_FILE = Join-Path $taskPilotData 'settings.json'
    $env:JARVIS_PROJECT_ROOT = Join-Path $taskPilotData 'projects'
    $env:JARVIS_LEGACY_DATA_DIR = Join-Path $taskPilotData 'legacy'
    $env:JARVIS_DESKTOP_DATA_DIR = Join-Path $taskPilotData 'desktop-profile'
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:JARVIS_DEV_SERVER = $null
    foreach ($taskName in $taskEnvironment) { if ($taskName.StartsWith('INARA_')) { [Environment]::SetEnvironmentVariable($taskName, $null, 'Process') } }
    $env:ELECTRON_RUN_AS_NODE = $null
    & $taskPython -I -B (Join-Path $taskPilotRoot 'backend/resident_main.py')
    if ($LASTEXITCODE -ne 0) { throw 'Pilot stopped with an error. Preserve its isolated data directory for inspection.' }
} finally {
    foreach ($taskName in $taskEnvironment) { [Environment]::SetEnvironmentVariable($taskName,$taskPrevious[$taskName],'Process') }
}
