param([Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference='Stop'
$taskOutput=[IO.Path]::GetFullPath($OutputDirectory)
if(Test-Path -LiteralPath $taskOutput) {throw 'Choose a new QA output.'}
$parseErrors=$null
[void][Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'managed-ui.ps1'),[ref]$null,[ref]$parseErrors)
if($parseErrors.Count) {throw 'Management PowerShell parser failed.'}
[void][IO.Directory]::CreateDirectory($taskOutput)
. (Join-Path $PSScriptRoot 'managed-ui.ps1') -BuildOnly
$script:window.Left=-10000; $script:window.Top=-10000
$script:window.Show(); $script:window.UpdateLayout()
$script:requests=[Collections.Generic.List[object]]::new()
function Send-Managed($message) {$script:requests.Add($message)}
function Click([string]$name) {$script:ui[$name].RaiseEvent([Windows.RoutedEventArgs]::new([Windows.Controls.Button]::ClickEvent))}
function Save-Frame([string]$name,[int]$width,[int]$height) {
    $script:window.Width=$width; $script:window.Height=$height; $script:window.UpdateLayout()
    $image=[Windows.Media.Imaging.RenderTargetBitmap]::new([int]$script:window.ActualWidth,[int]$script:window.ActualHeight,96,96,[Windows.Media.PixelFormats]::Pbgra32)
    $image.Render($script:window)
    $encoder=[Windows.Media.Imaging.PngBitmapEncoder]::new(); $encoder.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($image))
    $stream=[IO.File]::OpenWrite((Join-Path $taskOutput $name)); try{$encoder.Save($stream)}finally{$stream.Dispose()}
}
try {
    $script:ready=$true; Set-ManagedBusy $false
    $script:ui.RootPath.Text='C:\INARA UI fixture'; $script:ui.AnchorPath.Text='C:\Retained checkpoints'
    $script:ui.StatePin.Text='a'*64; $script:ui.HeadPin.Text='b'*64
    $script:ui.GrantPath.Text='C:\External evidence\grant.json'; $script:ui.ChangePath.Text='C:\External evidence\change.json'
    $script:ui.PolicyPath.Text='C:\External evidence\release.json'; $script:ui.PolicyPin.Text='c'*64
    $script:ui.WindowsPath.Text='C:\External evidence\windows.json'; $script:ui.WindowsPin.Text='d'*64
    $script:ui.PackagePath.Text='C:\External evidence\signed package'
    $script:ui.ConnectionBadge.Text='LOCAL / UI FIXTURE'
    $script:currentOp='status'
    Receive-Managed ([pscustomobject]@{ok=$true;result=[pscustomobject]@{number=7;sequence_floor=12;selected=('e'*64);checkpoint=('a'*64)}})
    Save-Frame 'managed-overview.png' 1120 900
    Click 'ReviewChange'
    if($script:requests[-1].request.action -cne 'update' -or $script:requests[-1].request.expected_state -cne ('a'*64)) {throw 'Signed change inputs failed.'}
    $request=$script:requests[-1].request
    $value=[pscustomobject]@{token='fixture-only';operation='change';action='update';root=$request.root;anchor=$request.anchor;expires_in_seconds=300;review_sha256=('f'*64);plan=[pscustomobject]@{checkpoint=('1'*64);previous=('a'*64);select=('e'*64);package=$request.package;profile='C:\INARA UI fixture\data\synthetic';launch=$false}}
    Show-ManagedReview $value
    $script:window.Width=780; $script:window.Height=800; $script:window.UpdateLayout(); $script:ui.PageScroll.ScrollToEnd(); $script:window.UpdateLayout()
    Save-Frame 'managed-review-780.png' 780 800
    Click 'ConfirmReview'
    if($script:requests[-1].op -cne 'apply' -or $script:requests[-1].token -cne 'fixture-only' -or $script:requests[-1].request.expected_state -cne ('a'*64)) {throw 'Review/apply binding failed.'}
    if($script:review -or $script:ui.ConfirmReview.IsEnabled) {throw 'Review was not consumed.'}
    $script:currentOp='apply'; Receive-Managed ([pscustomobject]@{ok=$false;error='Synthetic interrupted operation'})
    if($script:ui.ReviewCard.Visibility -ne 'Visible' -or $script:ui.ConfirmReview.IsEnabled -or $script:returnedCheckpoint -cne ('1'*64) -or $script:ui.CopyCheckpoint.Content -cne 'Copy prepared checkpoint') {throw 'Interrupted apply lost reviewed recovery evidence or retained confirmation.'}
    $script:reviewRequest=$request; Show-ManagedReview $value
    $script:ui.PolicyPin.Text='9'*64
    if($script:review -or $script:ui.ConfirmReview.IsEnabled) {throw 'Editing inputs retained review.'}
    $script:reviewRequest=$request; Show-ManagedReview $value
    $script:reviewDeadline=[DateTime]::UtcNow.AddSeconds(-1); $count=$script:requests.Count; Click 'ConfirmReview'
    if($script:requests.Count -ne $count -or $script:review) {throw 'Expired review applied.'}
    $script:ui.Pages.SelectedIndex=1; $script:ui.PreviousPin.Text='new'
    Click 'ReviewResume'; if($script:requests[-1].request.operation -cne 'resume' -or $script:requests[-1].request.previous_state -cne 'new') {throw 'Recovery routing failed.'}
    Click 'ReviewAbort'; if($script:requests[-1].request.operation -cne 'abort') {throw 'Cancellation routing failed.'}
    $script:currentOp='apply'; Receive-Managed ([pscustomobject]@{ok=$true;result=[pscustomobject]@{checkpoint=('2'*64);applied=$true}})
    if($script:ui.StatePin.Text -cne ('a'*64) -or $script:returnedCheckpoint -cne ('2'*64)) {throw 'Returned pin was automatically adopted or lost.'}
    $script:currentOp='review'; Receive-Managed ([pscustomobject]@{ok=$false;error='Fixture refusal'})
    if($script:review -or $script:ui.CopyCheckpoint.IsEnabled) {throw 'Refusal retained stale results.'}
    Set-ManagedBusy $true
    if($script:ui.RootPath.IsEnabled -or $script:ui.ReviewChange.IsEnabled -or $script:ui.Pages.IsEnabled) {throw 'Busy inputs permit changes.'}
    $script:window.Close(); if(!$script:window.IsVisible) {throw 'Busy close was permitted.'}
    Set-ManagedBusy $false
    $script:ui.Pages.SelectedIndex=2
    $script:ui.ProfileSlot.Text='e'*64; $script:ui.BackupFile.Text='C:\External evidence\profile.inara'
    Click 'NewProfileId'; Click 'ReviewBackup'
    if($script:requests[-1].request.operation -cne 'copy' -or $script:requests[-1].request.copy_action -cne 'backup') {throw 'Backup route failed.'}
    Click 'ReviewPrepareProfile'
    if($script:requests[-1].request.copy_action -cne 'prepare-profile' -or $script:requests[-1].request.profile.Length -ne 32) {throw 'Typed preparation route failed.'}
    $script:ui.RecoveryProfile.Text='3'*32
    $script:ui.StatusText.Text='UI fixture / encrypted backup and recovery preparation; no profile changes'
    $script:window.Width=1120; $script:window.Height=900; $script:window.UpdateLayout(); $script:ui.PageScroll.ScrollToEnd(); $script:window.UpdateLayout()
    Save-Frame 'managed-profiles.png' 1120 900
    $script:ui.Pages.SelectedIndex=3; $script:ui.LifecyclePath.Text='C:\External evidence\signed-lifecycle.json'; Click 'ReviewLifecycle'
    if($script:requests[-1].request.operation -cne 'lifecycle') {throw 'Signed lifecycle route failed.'}
    Show-ManagedReview ([pscustomobject]@{token='erase-fixture';operation='lifecycle';root='C:\INARA UI fixture';anchor='C:\Retained checkpoints';expires_in_seconds=300;review_sha256=('f'*64);plan=[pscustomobject]@{action='erase-data';confirmation_required=$true;checkpoint=('4'*64);previous=('a'*64);files=21;bytes=8192;data_preserved=$false;trust_evidence_retained=$true}})
    if($script:ui.ConfirmReview.IsEnabled) {throw 'Erasure requires exact phrase.'}
    $script:ui.EraseConfirmation.Text='yes'; if($script:ui.ConfirmReview.IsEnabled) {throw 'Partial phrase accepted.'}
    $script:window.Width=780; $script:window.Height=800; $script:window.UpdateLayout(); $script:ui.PageScroll.ScrollToEnd(); $script:window.UpdateLayout()
    Save-Frame 'managed-erasure-780.png' 780 800
    $script:ui.EraseConfirmation.Text='ERASE INARA DATA'
    if(!$script:ui.ConfirmReview.IsEnabled) {throw 'Exact phrase refused.'}
    Click 'ConfirmReview'
    if($script:requests[-1].confirmation -cne 'ERASE INARA DATA' -or $script:requests[-1].token -cne 'erase-fixture') {throw 'Erasure confirmation binding failed.'}
    $report=@{passed=$true;native_wpf_rendered=$true;widths=@(1120,780);review_apply_binding=$true;review_consumed=$true;interrupted_apply_preserves_review_evidence=$true;edit_invalidates=$true;expired_review_refused=$true;resume_abort_routes=$true;backup_prepare_routes=$true;signed_lifecycle_route=$true;separate_exact_erasure_confirmation=$true;returned_pin_not_adopted=$true;refusal_clears_stale_result=$true;busy_inputs_and_close_blocked=$true;backend_mutations=0;fixture_only=$true}
    $report | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskOutput 'verification.json') -Encoding UTF8
    $report | ConvertTo-Json
} finally {Set-ManagedBusy $false; $script:window.Close()}
