# Creates "JARVIS" shortcuts on the Desktop and in the Start menu that start JARVIS with no
# console window: .venv\Scripts\pythonw.exe backend\resident_main.py, exactly what `npm start`
# runs (scripts/launch-native.cjs). Run it once from a normal terminal (not from inside the
# Claude desktop app, whose Start-menu writes go to a private copy of AppData); run it again
# after moving the project folder. -NoDesktop / -NoStartMenu skip either shortcut; -Folder
# creates the one shortcut in that folder instead (for a custom place, or a check).
param([switch]$NoDesktop, [switch]$NoStartMenu, [string]$Folder)
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\pythonw.exe'
$entry = Join-Path $root 'backend\resident_main.py'
$icon = Join-Path $root 'assets\icons\jarvis.ico'
foreach ($file in @($python, $entry, $icon)) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
        throw "Missing $file. Set up the project first (scripts\bootstrap.ps1)."
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $root 'dist\index.html') -PathType Leaf)) {
    Write-Warning 'The workspace is not built yet (dist\index.html). Run "npm run build" before opening JARVIS.'
}

$targets = @()
if ($Folder) {
    $targets += Join-Path (Resolve-Path -LiteralPath $Folder).Path 'JARVIS.lnk'
} else {
    if (-not $NoDesktop) { $targets += Join-Path ([Environment]::GetFolderPath('Desktop')) 'JARVIS.lnk' }
    if (-not $NoStartMenu) { $targets += Join-Path ([Environment]::GetFolderPath('Programs')) 'JARVIS.lnk' }
}

$shell = New-Object -ComObject WScript.Shell
foreach ($path in $targets) {
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = $python
    $link.Arguments = '"' + $entry + '"'
    $link.WorkingDirectory = $root
    $link.IconLocation = "$icon,0"
    $link.Description = 'JARVIS'
    $link.Save()
    Write-Output "Created $path"
}
