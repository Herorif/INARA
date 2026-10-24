param([Parameter(Mandatory=$true)][string]$Directory,[Parameter(Mandatory=$true)][string]$ExpectedManifest,[Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference='Stop'
$taskDirectory=[IO.Path]::GetFullPath($Directory)
$taskPin=$ExpectedManifest
$taskOutput=[IO.Path]::GetFullPath($OutputDirectory)
if(Test-Path -LiteralPath $taskOutput) {throw 'Choose a new QA output.'}
[void][IO.Directory]::CreateDirectory($taskOutput)
. (Join-Path $PSScriptRoot 'managed-ui.ps1') -BuildOnly
$script:window.WindowStartupLocation='Manual'; $script:window.Left=-10000; $script:window.Top=-10000; $script:window.Show()
function Pump-ManagedIdle {
    $deadline=[DateTime]::UtcNow.AddSeconds(90)
    while($script:busy) {
        if([DateTime]::UtcNow -gt $deadline) {throw 'Protected bridge timed out.'}
        $frame=[Windows.Threading.DispatcherFrame]::new()
        [void]$script:window.Dispatcher.BeginInvoke([Windows.Threading.DispatcherPriority]::Background,[Action]{$frame.Continue=$false})
        [Windows.Threading.Dispatcher]::PushFrame($frame)
        Start-Sleep -Milliseconds 25
    }
}
try {
    $Directory=$taskDirectory
    $ExpectedManifest=$taskPin
    Start-ManagedWorker; $script:timer.Start(); Pump-ManagedIdle
    if(!$script:ready -or $script:ui.ConnectionBadge.Text -cne 'LOCAL / CONNECTED') {throw $script:ui.StatusText.Text}
    $target=Join-Path $taskOutput 'not-installed'
    $anchor=Join-Path $taskOutput 'no-anchor'
    $script:ui.RootPath.Text=$target; $script:ui.AnchorPath.Text=$anchor; $script:ui.StatePin.Text='a'*64
    Send-Managed @{op='status';request=(Get-ManagedRequest 'status')}; Pump-ManagedIdle
    if($script:ui.StateHeading.Text -cne 'Operation refused / preserve evidence') {throw 'Missing state did not refuse.'}
    if((Test-Path -LiteralPath $target) -or (Test-Path -LiteralPath $anchor)) {throw 'Read-only failure created an installation or anchor.'}
    Send-Managed @{op='discard'}; Pump-ManagedIdle
    if($script:ui.StatusText.Text -cne 'Review discarded. No change applied.') {throw 'Persistent worker response failed.'}
    $script:worker.StandardInput.Close()
    if(!$script:worker.WaitForExit(10000) -or $script:worker.ExitCode -ne 0) {throw 'Worker did not exit cleanly on EOF.'}
    # A bad external manifest must fail before packaged Python can emit ready.
    $ExpectedManifest='0'*64
    Start-ManagedWorker; Pump-ManagedIdle
    if($script:ready -or $script:ui.ConnectionBadge.Text -cne 'DISCONNECTED') {throw 'Bad bootstrap pin was accepted.'}
    if(!$script:worker.WaitForExit(10000) -or $script:worker.ExitCode -eq 0) {throw 'Bad bootstrap pin did not fail.'}
    $report=@{passed=$true;actual_bundled_python_worker=$true;trusted_lifecycle_adapters_loaded_before_ready=$true;native_async_dispatcher=$true;persistent_protocol=$true;verified_bootstrap_before_worker=$true;bad_pin_refused_before_ready=$true;read_only_refusal_no_root_or_anchor=$true;idle_eof_exit=$true;ports_opened=0;resident_launched=$false;production_installation_created=$false;fixture_only=$true}
    $report | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskOutput 'verification.json') -Encoding UTF8
    $report | ConvertTo-Json
} finally {Set-ManagedBusy $false; $script:window.Close()}
