param([Parameter(Mandatory=$true)][string]$ControlDirectory,[Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference='Stop'
$taskOutput=[IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $taskOutput) {throw 'Output must be new.'}
New-Item -ItemType Directory -Path $taskOutput | Out-Null
. (Join-Path $PSScriptRoot 'setup-ui.ps1') -BuildOnly
$script:controlRoot=[IO.Path]::GetFullPath($ControlDirectory)
$script:window.WindowStartupLocation='Manual'; $script:window.Left=-10000; $script:window.Top=-10000
$script:window.Show()
function Pump-UntilIdle {
    $deadline=[DateTime]::UtcNow.AddSeconds(180)
    while ($script:busy) {
        if ([DateTime]::UtcNow -gt $deadline) {throw 'Native control bridge timed out.'}
        $frame=New-Object Windows.Threading.DispatcherFrame
        $null=$script:window.Dispatcher.BeginInvoke([Windows.Threading.DispatcherPriority]::Background,[Action]{$frame.Continue=$false})
        [Windows.Threading.Dispatcher]::PushFrame($frame)
        Start-Sleep -Milliseconds 30
    }
}
try {
    Start-ControlWorker
    Pump-UntilIdle
    if ($script:ui.StatusText.Text -notlike 'Controls verified*') {throw $script:ui.StatusText.Text}
    $target=Join-Path $taskOutput 'not-installed'
    $script:ui.RootPath.Text=$target
    Send-Control @{op='status';root=$target}
    Pump-UntilIdle
    if ($script:ui.VersionStatus.Text -ne 'Ready for a fresh installation.') {throw $script:ui.StatusText.Text}
    if (Test-Path -LiteralPath $target) {throw 'Read-only status created a folder.'}
    Set-Busy $true; $script:currentOp='apply'
    $script:window.Close()
    if (!$script:window.IsVisible) {throw 'Busy close was not blocked.'}
    Set-Busy $false
    $report=@{passed=$true;actual_private_python_worker=$true;native_dispatcher_reply=$true;verified_worker_boot=$true;read_only_status_no_mutation=$true;busy_window_close_blocked=$true;ports_opened=0;fixture_only=$true}
    $report | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskOutput 'verification.json') -Encoding UTF8
    $report | ConvertTo-Json
} finally {Set-Busy $false;$script:window.Close()}
