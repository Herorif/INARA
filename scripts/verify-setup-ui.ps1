param([string]$OutputDirectory)
$ErrorActionPreference='Stop'
if (!$OutputDirectory) {throw 'Provide a new QA output directory.'}
$taskOutput=[IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $taskOutput) {throw 'QA output must be new.'}
New-Item -ItemType Directory -Path $taskOutput | Out-Null
. (Join-Path $PSScriptRoot 'setup-ui.ps1') -BuildOnly -InstallationRoot 'C:\INARA UI fixture'
$script:window.Left=-10000; $script:window.Top=-10000
$script:window.Show()
$script:window.UpdateLayout()
$script:requests = New-Object Collections.Generic.List[object]
function Send-Control($value) { $script:requests.Add($value) }
function Click([string]$name) {$script:ui[$name].RaiseEvent((New-Object Windows.RoutedEventArgs([Windows.Controls.Button]::ClickEvent)))}
function Save-Frame([string]$name,[int]$width,[int]$height) {
    $script:window.Width=$width; $script:window.Height=$height; $script:window.UpdateLayout()
    $content=$script:window.Content
    $image=New-Object Windows.Media.Imaging.RenderTargetBitmap([int]$content.ActualWidth,[int]$content.ActualHeight,96,96,[Windows.Media.PixelFormats]::Pbgra32)
    $image.Render($content)
    $encoder=New-Object Windows.Media.Imaging.PngBitmapEncoder
    $encoder.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($image))
    $stream=[IO.File]::OpenWrite((Join-Path $taskOutput $name));try {$encoder.Save($stream)} finally {$stream.Close()}
}
try {
    $slot='a'*64
    Set-SetupStatus ([pscustomobject]@{exists=$true;versions=@([pscustomobject]@{slot=$slot;label='Build aaaaaaaaaaaa / Selected';selected=$true});selected=$slot;previous=$null;needs_resume=$false})
    $script:ui.StatusText.Text='UI fixture / no installation or data changes'
    Save-Frame 'setup-overview.png' 1120 850
    Click 'LaunchButton'
    if ($script:requests[-1].request.resident_only -ne $true) {throw 'Tray must be the default launch mode.'}
    $script:ui.OpenWorkspace.IsChecked=$true;Click 'LaunchButton'
    if ($script:requests[-1].request.resident_only -ne $false) {throw 'Workspace preference was not carried.'}
    Click 'NavRecovery'
    $script:ui.BackupPath.Text='C:\Private fixture\profile.inara'
    Click 'PrepareButton'
    if ($script:requests[-1].request.action -ne 'prepare_recovery') {throw 'Recovery route failed.'}
    Click 'NavRemove';Click 'EraseButton'
    if ($script:requests[-1].request.action -ne 'erase_data') {throw 'Separate erasure route failed.'}
    Show-SetupReview ([pscustomobject]@{token='fixture-only';plan=[pscustomobject]@{action='erase_data';installation='C:\INARA UI fixture';result='Permanently erase retained profiles and recovery copies';data_policy='Permanent erasure';confirmation_required=$true;files=12;bytes=16384}})
    if ($script:ui.ConfirmReview.IsEnabled) {throw 'Erasure must require typing.'}
    $script:ui.EraseConfirmation.Text='yes'
    if ($script:ui.ConfirmReview.IsEnabled) {throw 'Partial confirmation was accepted.'}
    $script:ui.StatusText.Text='UI fixture / permanent-erasure review; nothing is deleted'
    $script:window.Width=780; $script:window.Height=760; $script:window.UpdateLayout(); $script:ui.PageScroll.ScrollToEnd(); $script:window.UpdateLayout()
    Save-Frame 'setup-erasure-780.png' 780 760
    $script:ui.EraseConfirmation.Text='ERASE INARA DATA'
    if (!$script:ui.ConfirmReview.IsEnabled) {throw 'Exact confirmation was not accepted.'}
    Click 'ConfirmReview'
    if ($script:requests[-1].confirmation -cne 'ERASE INARA DATA' -or $script:requests[-1].token -ne 'fixture-only') {throw 'Confirmation payload changed.'}
    Show-SetupReview ([pscustomobject]@{token='fixture-two';plan=[pscustomobject]@{result='Use this version';installation='C:\INARA UI fixture';data_policy='Keep existing profiles';confirmation_required=$false}})
    $script:ui.RootPath.Text='C:\Changed fixture'
    if ($script:reviewToken -or $script:ui.ConfirmReview.IsEnabled) {throw 'Input edits must invalidate the review.'}
    Set-Busy $true
    if ($script:ui.InstallButton.IsEnabled -or $script:ui.RootPath.IsEnabled) {throw 'Busy controls permit overlapping actions.'}
    Set-Busy $false
    $report=@{passed=$true;native_wpf_rendered=$true;widths=@(1120,780);review_invalidated_on_edit=$true;separate_erasure_confirmation=$true;tray_launch_default=$true;recovery_route=$true;busy_action_lock=$true;fixture_only=$true;backend_mutations=0}
    $report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $taskOutput 'verification.json') -Encoding UTF8
    $report | ConvertTo-Json -Depth 4
} finally {$script:window.Close()}
