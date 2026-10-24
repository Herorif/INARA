param([string]$InstallationRoot)
$ErrorActionPreference='Stop'
try { & (Join-Path $PSScriptRoot 'scripts/setup-ui.ps1') -InstallationRoot $InstallationRoot }
catch {
    Add-Type -AssemblyName PresentationFramework
    [Windows.MessageBox]::Show('Setup could not verify its local controls. Use an intact bundled core candidate and preserve your installation/data.','INARA Setup','OK','Error') | Out-Null
}
