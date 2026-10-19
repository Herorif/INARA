param([switch]$ResolveDependencies)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$taskJava = Get-Command java -ErrorAction SilentlyContinue
$taskGradle = Get-Command gradle -ErrorAction SilentlyContinue
if (!$taskJava -or !$taskGradle) { throw 'Install JDK 17 and Gradle 8.11.1 separately. This script installs nothing.' }
$taskSdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { $env:ANDROID_SDK_ROOT }
if (!$taskSdk -or !(Test-Path -LiteralPath (Join-Path $taskSdk 'platforms/android-35/android.jar')) -or !(Test-Path -LiteralPath (Join-Path $taskSdk 'build-tools/35.0.0'))) {
    throw 'Configure an existing Android SDK with API 35 and Build Tools 35.0.0. No SDK is installed automatically.'
}
$taskGradleVersion = & $taskGradle.Source --version
if ($LASTEXITCODE -ne 0 -or !($taskGradleVersion -match 'Gradle 8.11.1')) { throw 'Use the pinned Gradle 8.11.1 toolchain.' }
$taskOptions = @('--no-daemon', '--max-workers=2', ':app:assembleDebug', ':app:testDebugUnitTest')
if (!$ResolveDependencies) { $taskOptions = @('--offline') + $taskOptions }
& $taskGradle.Source @taskOptions
exit $LASTEXITCODE
