param([switch]$ResolveDependencies, [switch]$RecordDependencies, [switch]$Preflight)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskPython = Join-Path $taskRoot '.venv/Scripts/python.exe'
$taskEvidenceTool = Join-Path $taskRoot 'scripts/android-build.py'
if (!(Test-Path -LiteralPath $taskPython)) { throw 'Provide the existing INARA Python environment first. This script installs nothing.' }
if ($Preflight) { & $taskPython $taskEvidenceTool preflight; exit $LASTEXITCODE }
if ($ResolveDependencies -and !$RecordDependencies) { throw 'Dependency resolution is allowed only with explicit -RecordDependencies. Normal builds are strict and offline.' }
$taskJava = Get-Command javac -ErrorAction SilentlyContinue
$taskGradle = Get-Command gradle -ErrorAction SilentlyContinue
if (!$taskJava -or !$taskGradle) { throw 'Provide JDK 17 and Gradle 8.14.6 separately. No tool is installed automatically.' }
$taskJavaVersion = (& $taskJava.Source -version 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or $taskJavaVersion -notmatch '(?m)^javac 17(?:\.|\s|$)') { throw 'Use the pinned JDK 17.' }
$taskJdk = Split-Path -Parent (Split-Path -Parent $taskJava.Source)
$taskSdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { $env:ANDROID_SDK_ROOT }
if (!$taskSdk -or !(Test-Path -LiteralPath (Join-Path $taskSdk 'platforms/android-35/android.jar'))) { throw 'Provide the existing API 35 SDK. No SDK is installed automatically.' }
$taskSigner = Join-Path $taskSdk 'build-tools/35.0.0/apksigner.bat'
if (!(Test-Path -LiteralPath $taskSigner)) { throw 'Provide existing Build Tools 35.0.0 including apksigner.' }
Push-Location $PSScriptRoot
try {
    $taskGradleVersion = (& $taskGradle.Source --no-daemon --version 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0 -or $taskGradleVersion -notmatch '(?m)^Gradle 8\.14\.6\s*$' -or $taskGradleVersion -notmatch '(?m)^(?:Launcher )?JVM:\s+17(?:\.|\s|$)') {
        throw 'Use Gradle 8.14.6 running on JDK 17; PATH javac alone does not establish the Gradle JVM.'
    }
    $taskBeginOptions = @('begin')
    if ($RecordDependencies) { $taskBeginOptions += '--record-dependencies' }
    $taskRun = (& $taskPython $taskEvidenceTool @taskBeginOptions | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $taskRun -notmatch '^[a-f0-9-]{36}$') { throw 'Build admission failed. Run -Preflight and inspect dependency locks/verification metadata.' }
    $taskEvidence = Join-Path $taskRoot ".runtime/android-build/$taskRun"
    @{java='17';gradle='8.14.6'} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskEvidence 'toolchain.json') -Encoding UTF8
    $taskOptions = @('--no-daemon', '--no-watch-fs', '--max-workers=1', '--console=plain', '--stacktrace', "-Dorg.gradle.java.home=$taskJdk", '-Pandroid.builder.sdkDownload=false', '-Pkotlin.compiler.execution.strategy=in-process')
    if (!$ResolveDependencies) { $taskOptions += '--offline' }
    if ($RecordDependencies) { $taskOptions += @('--write-locks', '--write-verification-metadata', 'sha256') }
    else { $taskOptions += '--dependency-verification=strict' }
    $taskOptions += @(':app:clean', ':app:assembleDebug', ':app:testDebugUnitTest')
    & $taskGradle.Source @taskOptions
    $taskBuildExit = $LASTEXITCODE
    $taskSignatureExit = -1
    if ($taskBuildExit -eq 0) {
        & $taskSigner verify --verbose --print-certs (Join-Path $PSScriptRoot 'app/build/outputs/apk/debug/app-debug.apk') 2>&1 | Out-File -LiteralPath (Join-Path $taskEvidence 'apksigner.txt') -Encoding UTF8
        $taskSignatureExit = $LASTEXITCODE
    }
    & $taskPython $taskEvidenceTool complete --run $taskRun --build-exit $taskBuildExit --signature-exit $taskSignatureExit
    if ($LASTEXITCODE -ne 0) { throw 'Android debug build acceptance failed. Inspect local evidence; no device was contacted.' }
    if ($RecordDependencies) { Write-Output 'Dependency metadata was recorded; independently review its source/checksums, then run a normal offline strict build. Recording is not accepted build status.' }
} finally { Pop-Location }
