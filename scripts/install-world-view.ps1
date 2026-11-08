<#
.SYNOPSIS
Sets up World view (docs/WORLD_VIEW.md): Node 24 and the God's Eye View globe in your tools folder.

.DESCRIPTION
You run this yourself; JARVIS never runs it and never downloads anything for World view.
It is safe to run again: each step that is already done is skipped.

  1. Downloads node-v24.22.2-win-x64.zip from nodejs.org, checks its SHA-256 and unzips it
     to %USERPROFILE%\tools.
  2. Fetches God's Eye View at one pinned commit (shallow, git's schannel TLS backend) into
     %USERPROFILE%\tools\gods-eye-view.
  3. Installs its packages with npm ci (PUPPETEER_SKIP_DOWNLOAD=true, install scripts off),
     using that Node.
  4. Builds the app (npm run build) and the panel (npm run build:panel).

Use -WhatIf to see every step without changing anything, and -Force to reinstall the
packages and rebuild even when they look done.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File scripts\install-world-view.ps1 -WhatIf
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Tools = (Join-Path $env:USERPROFILE 'tools'),
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 3.0

$NodeVersion = 'v24.22.2'
$NodeName = "node-$NodeVersion-win-x64"
$NodeUrl = "https://nodejs.org/dist/$NodeVersion/$NodeName.zip"
$NodeSha256 = 'ca1bff5d8ead13c9f2ea404a176db46bd430704d5b5113734049fa365e7799e2'
$GevRepository = 'https://github.com/bilawalsidhu/gods-eye-view.git'
$GevCommit = '52187c91d188504188ea9e9ae33e5b6e24cab7f2'

$NodeDir = Join-Path $Tools $NodeName
$Node = Join-Path $NodeDir 'node.exe'
$NpmCli = Join-Path $NodeDir 'node_modules\npm\bin\npm-cli.js'
$Root = Join-Path $Tools 'gods-eye-view'
$Dry = [bool]$WhatIfPreference

function Step([string]$Number, [string]$Text) { Write-Host ""; Write-Host "[$Number/4] $Text" -ForegroundColor Cyan }
function Done([string]$Text) { Write-Host "  Done: $Text" -ForegroundColor Green }
function Skip([string]$Text) { Write-Host "  Already done: $Text" }
function Plan([string]$Text) { Write-Host "  Would: $Text" -ForegroundColor Yellow }
function Fail([string]$Text) { Write-Host "  Stopped: $Text" -ForegroundColor Red; exit 1 }

function Invoke-Checked([string]$Program, [string[]]$Arguments, [string]$What) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { Fail "$What failed (exit code $LASTEXITCODE)." }
}

function Invoke-Npm([string[]]$Arguments, [string]$What) {
    # That Node runs npm's own script: no npm.cmd and no other Node on PATH.
    $saved = $env:PATH
    $env:PATH = "$NodeDir;$env:SystemRoot\System32;$env:SystemRoot"
    $env:PUPPETEER_SKIP_DOWNLOAD = 'true'
    try {
        Push-Location $Root
        try { Invoke-Checked $Node (@($NpmCli) + $Arguments) $What } finally { Pop-Location }
    } finally {
        $env:PATH = $saved
        Remove-Item Env:PUPPETEER_SKIP_DOWNLOAD -ErrorAction SilentlyContinue
    }
}

Write-Host "World view setup for JARVIS"
Write-Host "Tools folder: $Tools"
if ($Dry) { Write-Host "Dry run: nothing is downloaded or changed." -ForegroundColor Yellow }

# --- 1. Node 24 -----------------------------------------------------------------------------
Step 1 "Node $NodeVersion"
$haveNode = (Test-Path -LiteralPath $Node -PathType Leaf) -and ((& $Node --version 2>$null) -eq $NodeVersion)
if ($haveNode) {
    Skip "$Node"
} elseif ($Dry) {
    Plan "download $NodeUrl, check SHA-256 $NodeSha256, unzip to $Tools"
} elseif ($PSCmdlet.ShouldProcess($NodeDir, "Download and unzip Node $NodeVersion")) {
    $download = Join-Path ([IO.Path]::GetTempPath()) ("jarvis-world-view-" + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $download | Out-Null
    try {
        $zip = Join-Path $download "$NodeName.zip"
        Write-Host "  Downloading $NodeUrl"
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -UseBasicParsing -Uri $NodeUrl -OutFile $zip
        $hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($hash -ne $NodeSha256) { Fail "the download's SHA-256 is $hash, not $NodeSha256. Nothing was unzipped." }
        Write-Host "  SHA-256 matches."
        New-Item -ItemType Directory -Force -Path $Tools | Out-Null
        if (Test-Path -LiteralPath $NodeDir) { Remove-Item -LiteralPath $NodeDir -Recurse -Force }
        Expand-Archive -LiteralPath $zip -DestinationPath $Tools
        if ((& $Node --version) -ne $NodeVersion) { Fail "the unzipped Node isn't $NodeVersion." }
        Done "$Node"
    } finally {
        Remove-Item -LiteralPath $download -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# --- 2. God's Eye View at the pinned commit ------------------------------------------------
Step 2 "God's Eye View at $GevCommit"
$git = Get-Command git.exe -ErrorAction SilentlyContinue
if (-not $git) { Fail "Git isn't installed. Install Git for Windows, then run this again." }
$head = $null
if (Test-Path -LiteralPath (Join-Path $Root '.git')) {
    $head = (& git -C $Root rev-parse HEAD 2>$null)
} elseif ((Test-Path -LiteralPath $Root) -and (Get-ChildItem -LiteralPath $Root -Force | Select-Object -First 1)) {
    Fail "$Root exists but isn't a Git checkout. Move it aside, then run this again."
}
if ($head -eq $GevCommit) {
    Skip "$Root"
} elseif ($Dry) {
    Plan "git fetch --depth 1 $GevRepository $GevCommit into $Root (schannel), then check it out"
} elseif ($PSCmdlet.ShouldProcess($Root, "Fetch God's Eye View $GevCommit")) {
    if ($head) {
        $changes = (& git -C $Root status --porcelain --untracked-files=no)
        if ($changes) { Fail "$Root has local changes. Commit or discard them, then run this again." }
    } else {
        Invoke-Checked git @('init', '--quiet', $Root) 'git init'
        Invoke-Checked git @('-C', $Root, 'remote', 'add', 'origin', $GevRepository) 'git remote add'
    }
    Invoke-Checked git @('-C', $Root, '-c', 'http.sslBackend=schannel', 'fetch', '--depth', '1', 'origin', $GevCommit) 'git fetch'
    Invoke-Checked git @('-C', $Root, '-c', 'core.longpaths=true', '-c', 'advice.detachedHead=false', 'checkout', '--detach', 'FETCH_HEAD') 'git checkout'
    if ((& git -C $Root rev-parse HEAD) -ne $GevCommit) { Fail "the checkout isn't at $GevCommit." }
    $Force = $true  # new sources: install and build again
    Done "$Root"
}

# --- 3. Packages ------------------------------------------------------------------------------
Step 3 "Packages (npm ci)"
$lock = Join-Path $Root 'package-lock.json'
$installed = Join-Path $Root 'node_modules\.package-lock.json'
$haveModules = (Test-Path -LiteralPath $installed) -and (Test-Path -LiteralPath $lock) -and
    ((Get-Item -LiteralPath $installed).LastWriteTimeUtc -ge (Get-Item -LiteralPath $lock).LastWriteTimeUtc)
if ($haveModules -and -not $Force) {
    Skip "$Root\node_modules"
} elseif ($Dry) {
    Plan "run npm ci --ignore-scripts with PUPPETEER_SKIP_DOWNLOAD=true in $Root, using $Node"
} elseif ($PSCmdlet.ShouldProcess($Root, 'npm ci')) {
    Invoke-Npm @('ci', '--ignore-scripts', '--no-audit', '--no-fund') 'npm ci'
    Done "$Root\node_modules"
}

# --- 4. Build -------------------------------------------------------------------------------
Step 4 "Build (npm run build, npm run build:panel)"
$built = (Test-Path -LiteralPath (Join-Path $Root 'dist\index.html')) -and (Test-Path -LiteralPath (Join-Path $Root 'dist\panel'))
if ($built -and -not $Force) {
    Skip "$Root\dist"
} elseif ($Dry) {
    Plan "run npm run build and npm run build:panel in $Root, using $Node"
} elseif ($PSCmdlet.ShouldProcess($Root, 'npm run build; npm run build:panel')) {
    Invoke-Npm @('run', 'build') 'npm run build'
    Invoke-Npm @('run', 'build:panel') 'npm run build:panel'
    Done "$Root\dist"
}

Write-Host ""
if ($Dry) { Write-Host "Dry run finished. Run it again without -WhatIf to set up World view." -ForegroundColor Yellow }
else { Write-Host "World view is set up. Open Studio > World in JARVIS." -ForegroundColor Green }
