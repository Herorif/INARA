param([string]$Directory, [string]$ExpectedManifest, [switch]$BuildOnly)
# Open production UI only through the independently trusted bootstrap: managed-setup.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationFramework,PresentationCore,WindowsBase,System.Windows.Forms
$script:managedRoot = Split-Path -Parent $PSScriptRoot
[xml]$taskXaml = Get-Content -LiteralPath (Join-Path $script:managedRoot 'native/setup/Managed.xaml') -Raw -Encoding UTF8
$script:window = [Windows.Markup.XamlReader]::Load([Xml.XmlNodeReader]::new($taskXaml))
$script:ui = @{}
foreach ($element in $taskXaml.SelectNodes('//*')) {
    $name = $element.GetAttribute('Name','http://schemas.microsoft.com/winfx/2006/xaml')
    if ($name) {$script:ui[$name] = $script:window.FindName($name)}
}
$script:inputs = @('RootPath','AnchorPath','StatePin','HeadPin','GrantPath','ChangePath','PackagePath','PolicyPath','PolicyPin','WindowsPath','WindowsPin','NextPolicyPath','NextPolicyPin','NextWindowsPath','NextWindowsPin','PreviousPin','ProfileSlot','BackupFile','RecoveryProfile','LifecyclePath')
$script:actions = @('ActionUpdate','ActionRollback','ActionRenew','ActionRotate','ActionEnroll')
$script:buttons = @('CheckStatus','ReviewChange','ReviewResume','ReviewAbort','ReviewBackup','ReviewPrepareProfile','ReviewLifecycle')
$script:browsers = @('BrowseRoot','BrowseAnchor','BrowseGrant','BrowseChange','BrowsePackage','NewBackupFile','OpenBackupFile','NewProfileId','BrowseLifecycle')
$script:busy=$false; $script:ready=$false; $script:worker=$null; $script:readTask=$null
$script:review=$null; $script:reviewRequest=$null; $script:reviewDeadline=$null; $script:returnedCheckpoint=$null; $script:currentOp=$null
$script:reviewEvidence=$null; $script:inFlightReview=$null
$script:eraseRequired=$false

function Reset-ManagedReview {
    $script:review=$null; $script:reviewRequest=$null; $script:reviewDeadline=$null
    $script:reviewEvidence=$null
    $script:eraseRequired=$false; $script:ui.ErasePrompt.Visibility='Collapsed'; $script:ui.EraseConfirmation.Text=''
    $script:ui.ReviewCard.Visibility='Collapsed'; $script:ui.ConfirmReview.IsEnabled=$false
}
function Set-ManagedBusy([bool]$value) {
    $script:busy=$value
    $script:ui.Progress.Visibility=$(if($value){'Visible'}else{'Collapsed'})
    foreach($name in ($script:inputs + $script:actions + $script:browsers)) {$script:ui[$name].IsEnabled=!$value}
    foreach($name in $script:buttons) {$script:ui[$name].IsEnabled=!$value -and $script:ready}
    $script:ui.Pages.IsEnabled=!$value
    $script:ui.CancelReview.IsEnabled=!$value
    $script:ui.CopyCheckpoint.IsEnabled=!$value -and $null -ne $script:returnedCheckpoint
    $script:ui.EraseConfirmation.IsEnabled=!$value
    $script:ui.ConfirmReview.IsEnabled=!$value -and $script:ready -and $null -ne $script:review -and (!$script:eraseRequired -or $script:ui.EraseConfirmation.Text -ceq 'ERASE INARA DATA')
}
function Get-ManagedRequest([string]$operation) {
    $request=@{operation=$operation;root=$script:ui.RootPath.Text;anchor=$script:ui.AnchorPath.Text;expected_state=$script:ui.StatePin.Text}
    if ($operation -in @('resume','abort')) {$request.previous_state=$script:ui.PreviousPin.Text}
    if ($operation -eq 'lifecycle') {$request.change=$script:ui.LifecyclePath.Text}
    if ($operation -in @('backup','prepare-profile')) {
        $request.operation='copy'; $request.copy_action=$operation; $request.slot=$script:ui.ProfileSlot.Text; $request.file=$script:ui.BackupFile.Text
        if($operation -eq 'prepare-profile') {$request.profile=$script:ui.RecoveryProfile.Text}
    }
    if ($operation -eq 'change') {
        $request.action='update'
        foreach($name in $script:actions) {if($script:ui[$name].IsChecked) {$request.action=[string]$script:ui[$name].Tag}}
        foreach($entry in @(@('expected_head','HeadPin'),@('grant','GrantPath'),@('change','ChangePath'),@('policy','PolicyPath'),@('expected_policy','PolicyPin'),@('windows_policy','WindowsPath'),@('expected_windows_policy','WindowsPin'))) {$request[$entry[0]]=$script:ui[$entry[1]].Text}
        foreach($entry in @(@('package','PackagePath'),@('next_policy','NextPolicyPath'),@('expected_next_policy','NextPolicyPin'),@('next_windows_policy','NextWindowsPath'),@('expected_next_windows_policy','NextWindowsPin'))) {if($script:ui[$entry[1]].Text) {$request[$entry[0]]=$script:ui[$entry[1]].Text}}
    }
    return $request
}
function Send-Managed($message) {
    if($script:busy -or !$script:ready -or !$script:worker -or $script:worker.HasExited) {return}
    $script:currentOp=$message.op
    if($message.op -ne 'apply') {$script:inFlightReview=$null}
    $script:returnedCheckpoint=$null
    Set-ManagedBusy $true
    $script:ui.StatusText.Text='Verifying local evidence. Wait for the result before closing.'
    try {
        $raw=[Text.Encoding]::UTF8.GetBytes(($message | ConvertTo-Json -Depth 16 -Compress)+"`n")
        if($raw.Length -gt 65536) {throw 'Request is excessive.'}
        $script:worker.StandardInput.BaseStream.Write($raw,0,$raw.Length)
        $script:worker.StandardInput.BaseStream.Flush()
        $script:readTask=$script:worker.StandardOutput.ReadLineAsync()
    } catch {
        $script:ready=$false; Reset-ManagedReview; Set-ManagedBusy $false
        $script:ui.StatusText.Text='Connection failed. Preserve retained checkpoints and any interrupted transaction. Reopen management before retrying.'
        Show-ManagedUncertainty
    }
}
function Request-ManagedReview([string]$operation) {
    if($script:busy) {return}
    Reset-ManagedReview
    $script:reviewRequest=Get-ManagedRequest $operation
    Send-Managed @{op='review';request=$script:reviewRequest}
}
function Pick-ManagedPath([string]$field,[bool]$folder) {
    if($script:busy) {return}
    if($folder) {
        $dialog=[Windows.Forms.FolderBrowserDialog]::new()
        $dialog.ShowNewFolderButton=$false
        try {if($dialog.ShowDialog() -eq 'OK') {$script:ui[$field].Text=$dialog.SelectedPath}} finally {$dialog.Dispose()}
    } else {
        $dialog=[Microsoft.Win32.OpenFileDialog]::new(); $dialog.Filter='Signed JSON evidence (*.json)|*.json|All files (*.*)|*.*'
        if($dialog.ShowDialog($script:window)) {$script:ui[$field].Text=$dialog.FileName}
    }
}
function Show-ManagedReview($value) {
    $script:reviewEvidence=$value
    $script:review=$value.token; $script:reviewDeadline=[DateTime]::UtcNow.AddSeconds([int]$value.expires_in_seconds)
    $script:ui.ReviewHeading.Text= switch($value.operation) {'copy' {'Review this protected profile copy.'} 'lifecycle' {([string]$value.plan.action).ToUpperInvariant()+' / review lifecycle change'} 'resume' {'Resume this interrupted change?'} 'abort' {'Cancel this prepared change?'} default {([string]$value.action).ToUpperInvariant()+' / confirm the exact change'}}
    $lines=@(('Installation: '+$value.root),('Checkpoint folder: '+$value.anchor))
    foreach($entry in @(@('checkpoint','Resulting checkpoint'),@('previous','Previous checkpoint'),@('select','Selected version'),@('package','Original package'),@('profile','Profile'),@('file','Encrypted backup'),@('destination','Recovery destination'),@('owner_fingerprint','Owner fingerprint'),@('files','Files'),@('bytes','Bytes'),@('data_preserved','Profile data retained'),@('trust_evidence_retained','Trust evidence retained'),@('selection_unchanged','Profile selection unchanged'),@('journal_sha256','Retained journal'),@('installation_sha256','Installation state'),@('authorization_sha256','Grant state'),@('anchor_head_sha256','Checkpoint pointer'),@('change_sha256','Signed change'))) {
        $property=$value.plan.PSObject.Properties[$entry[0]]
        if($property -and $null -ne $property.Value) {$lines += $entry[1]+': '+[string]$property.Value}
    }
    if($value.plan.copies_retained) {$lines += 'Staged files and evidence remain retained.'}
    $lines += @('Launch: no','Review digest: '+$value.review_sha256)
    $script:ui.ReviewDetails.Text=$lines -join [Environment]::NewLine
    $script:eraseRequired=[bool]$value.plan.confirmation_required
    $script:ui.EraseConfirmation.Text=''; $script:ui.ErasePrompt.Visibility=$(if($script:eraseRequired){'Visible'}else{'Collapsed'})
    $script:ui.ReviewCard.Visibility='Visible'; $script:ui.ConfirmReview.IsEnabled=!$script:eraseRequired
    $script:ui.StatusText.Text='Review the exact change below. Nothing has been applied.'
    $script:ui.ReviewCard.BringIntoView(); [void]$script:ui.CancelReview.Focus()
}
function Set-ReturnedCheckpoint($value) {
    if($value -cmatch '^[a-f0-9]{64}$') {
        $script:returnedCheckpoint=$value
        $script:ui.CopyCheckpoint.IsEnabled=$true
        $script:ui.CopyCheckpoint.Content='Copy returned checkpoint'
    }
}
function Show-ManagedUncertainty {
    if(!$script:inFlightReview) {return}
    $script:ui.ReviewHeading.Text='Outcome uncertain / retain this review'
    $script:ui.ReviewDetails.Text=$script:inFlightReview.details
    $script:ui.ReviewCard.Visibility='Visible'; $script:ui.ConfirmReview.IsEnabled=$false
    $pin=$script:inFlightReview.value.plan.checkpoint
    if($pin -cmatch '^[a-f0-9]{64}$') {
        $script:returnedCheckpoint=$pin; $script:ui.CopyCheckpoint.Content='Copy prepared checkpoint'; $script:ui.CopyCheckpoint.IsEnabled=$true
    }
    $script:ui.StatusText.Text+=' Retain this prepared checkpoint and previous pin. It is not proof of commit; check status or review interrupted-change recovery before retrying.'
    $script:ui.ReviewCard.BringIntoView()
}
function Receive-Managed($response) {
    Set-ManagedBusy $false
    if(!$response.ok) {
        Reset-ManagedReview
        $script:returnedCheckpoint=$null; $script:ui.CopyCheckpoint.IsEnabled=$false
        $script:ui.StateHeading.Text='Operation refused / preserve evidence'
        $script:ui.StatusText.Text=[string]$response.error
        Show-ManagedUncertainty
        return
    }
    $value=$response.result
    if($script:currentOp -eq 'review') {Show-ManagedReview $value; return}
    if($script:currentOp -eq 'discard') {$script:ui.StatusText.Text='Review discarded. No change applied.'; return}
    Set-ReturnedCheckpoint $value.checkpoint
    if($script:currentOp -eq 'status') {
        $script:ui.StateHeading.Text='Protected metadata verified'
        $script:ui.StateDetails.Text=('Checkpoint '+$value.number+' / minimum accepted sequence '+$value.sequence_floor+[Environment]::NewLine+'Selected version: '+$value.selected+[Environment]::NewLine+'Checkpoint: '+$value.checkpoint)
        $script:ui.StatusText.Text='Protected metadata matches your retained pin. Current launch eligibility was not checked.'
    } else {
        $script:inFlightReview=$null
        $script:ui.StateHeading.Text=$(if($value.backup_created){'Encrypted backup created'}elseif($value.prepared){'Recovery copy prepared / selection unchanged'}elseif($value.cancelled){'Prepared change cancelled'}elseif($value.resumed){'Interrupted change completed'}else{'Reviewed change applied'})
        $script:ui.StateDetails.Text='Returned checkpoint: '+$value.checkpoint+[Environment]::NewLine+'Retain this result independently. Copy it and explicitly enter your retained pin before the next check. Existing inputs have not changed.'
        $script:ui.StatusText.Text='Operation completed. INARA was not launched. Retain the returned checkpoint before continuing.'
    }
}
foreach($name in $script:inputs) {$script:ui[$name].Add_TextChanged({Reset-ManagedReview; $script:returnedCheckpoint=$null; $script:ui.CopyCheckpoint.IsEnabled=$false; $script:ui.StateHeading.Text='Inputs changed / check again'; $script:ui.StateDetails.Text='The previous result does not describe these edited inputs.'})}
foreach($name in $script:actions) {$script:ui[$name].Add_Checked({Reset-ManagedReview})}
$script:ui.Pages.Add_SelectionChanged({if($this -eq $_.Source){Reset-ManagedReview}})
$script:ui.CheckStatus.Add_Click({Reset-ManagedReview; Send-Managed @{op='status';request=(Get-ManagedRequest 'status')}})
$script:ui.ReviewChange.Add_Click({Request-ManagedReview 'change'})
$script:ui.ReviewResume.Add_Click({Request-ManagedReview 'resume'})
$script:ui.ReviewAbort.Add_Click({Request-ManagedReview 'abort'})
$script:ui.ReviewBackup.Add_Click({Request-ManagedReview 'backup'})
$script:ui.ReviewPrepareProfile.Add_Click({Request-ManagedReview 'prepare-profile'})
$script:ui.ReviewLifecycle.Add_Click({Request-ManagedReview 'lifecycle'})
$script:ui.BrowseLifecycle.Add_Click({Pick-ManagedPath 'LifecyclePath' $false})
$script:ui.OpenBackupFile.Add_Click({$dialog=[Microsoft.Win32.OpenFileDialog]::new(); $dialog.Filter='INARA backup (*.inara)|*.inara'; if($dialog.ShowDialog($script:window)) {$script:ui.BackupFile.Text=$dialog.FileName}})
$script:ui.NewBackupFile.Add_Click({$dialog=[Microsoft.Win32.SaveFileDialog]::new(); $dialog.Filter='INARA backup (*.inara)|*.inara'; $dialog.FileName='inara-profile.inara'; if($dialog.ShowDialog($script:window)) {$script:ui.BackupFile.Text=$dialog.FileName}})
$script:ui.NewProfileId.Add_Click({$script:ui.RecoveryProfile.Text=[Guid]::NewGuid().ToString('N')})
$script:ui.BrowseRoot.Add_Click({Pick-ManagedPath 'RootPath' $true})
$script:ui.BrowseAnchor.Add_Click({Pick-ManagedPath 'AnchorPath' $true})
$script:ui.BrowsePackage.Add_Click({Pick-ManagedPath 'PackagePath' $true})
$script:ui.BrowseGrant.Add_Click({Pick-ManagedPath 'GrantPath' $false})
$script:ui.BrowseChange.Add_Click({Pick-ManagedPath 'ChangePath' $false})
$script:ui.CancelReview.Add_Click({Reset-ManagedReview; Send-Managed @{op='discard'}})
$script:ui.ConfirmReview.Add_Click({
    if($script:review -and !$script:busy) {
        if([DateTime]::UtcNow -ge $script:reviewDeadline) {Reset-ManagedReview; $script:ui.StatusText.Text='Review expired. Review the change again.'; return}
        $message=@{op='apply';token=$script:review;request=$script:reviewRequest}
        if($script:eraseRequired) {
            if($script:ui.EraseConfirmation.Text -cne 'ERASE INARA DATA') {return}
            $message.confirmation=$script:ui.EraseConfirmation.Text
        }
        $script:inFlightReview=@{value=$script:reviewEvidence;details=$script:ui.ReviewDetails.Text}
        Reset-ManagedReview
        Send-Managed $message
    }
})
$script:ui.EraseConfirmation.Add_TextChanged({$script:ui.ConfirmReview.IsEnabled=!$script:busy -and $script:ready -and $null -ne $script:review -and (!$script:eraseRequired -or $script:ui.EraseConfirmation.Text -ceq 'ERASE INARA DATA')})
$script:ui.CopyCheckpoint.Add_Click({if($script:returnedCheckpoint){[Windows.Clipboard]::SetText($script:returnedCheckpoint); $script:ui.StatusText.Text='Checkpoint copied. Retain it independently; a prepared pin is not proof of commit. Input pins remain unchanged.'}})
$script:window.Add_Closing({param($sender,$eventArgs)
    if($script:busy) {$eventArgs.Cancel=$true; $script:ui.StatusText.Text='Wait for the active operation. Closing cannot cancel an update.'; return}
    Reset-ManagedReview
    if($script:worker -and !$script:worker.HasExited) {$script:worker.StandardInput.Close()}
})
function Quote-ManagedArgument([string]$value) {
    # CommandLineToArgvW quoting only. No shell expression or script interpolation.
    return '"'+([regex]::Replace([regex]::Replace($value,'(\\*)"','$1$1\"'),'(\\+)$','$1$1'))+'"'
}
function Start-ManagedWorker {
    if(!$Directory -or $ExpectedManifest -cnotmatch '^[a-f0-9]{64}$') {throw 'Explicit controller directory and independent inventory pin required.'}
    $start=[Diagnostics.ProcessStartInfo]::new()
    $start.FileName=Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe'
    $arguments=@('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $Directory 'scripts/open-trusted-controller.ps1'),'-Directory',$Directory,'-ExpectedManifest',$ExpectedManifest,'managed-ui-worker')
    $start.Arguments=($arguments | ForEach-Object {Quote-ManagedArgument $_}) -join ' '
    $start.WorkingDirectory=$Directory; $start.UseShellExecute=$false; $start.CreateNoWindow=$true
    $start.RedirectStandardInput=$true; $start.RedirectStandardOutput=$true; $start.RedirectStandardError=$true
    $start.StandardOutputEncoding=[Text.Encoding]::UTF8; $start.StandardErrorEncoding=[Text.Encoding]::UTF8
    $script:worker=[Diagnostics.Process]::Start($start)
    $script:errorTask=$script:worker.StandardError.ReadToEndAsync()
    $script:readTask=$script:worker.StandardOutput.ReadLineAsync(); $script:currentOp='connect'
    Set-ManagedBusy $true
}
$script:timer=[Windows.Threading.DispatcherTimer]::new(); $script:timer.Interval=[TimeSpan]::FromMilliseconds(100)
$script:timer.Add_Tick({
    if($script:reviewDeadline -and [DateTime]::UtcNow -ge $script:reviewDeadline) {Reset-ManagedReview; $script:ui.StatusText.Text='Review expired. Review the change again.'}
    if(!$script:readTask) {return}
    if(!$script:readTask.IsCompleted) {return}
    try {
        $raw=$script:readTask.GetAwaiter().GetResult(); $script:readTask=$null
        if(!$raw -or $raw.Length -gt 65536) {throw 'Connection ended or response exceeded limit.'}
        $response=$raw | ConvertFrom-Json
        if($script:currentOp -eq 'connect') {
            if(!$response.ready -or $response.kind -cne 'inara-protected-management' -or $response.protocol -ne 1) {throw 'Unknown worker.'}
            foreach($capability in @('backup','prepare-profile','signed-lifecycle','reviewed-recovery')) {if($response.capabilities -cnotcontains $capability){throw 'Lifecycle worker capability missing.'}}
            $script:ready=$true; Set-ManagedBusy $false
            $script:ui.ConnectionBadge.Text='LOCAL / CONNECTED'; $script:ui.StatusText.Text='Controller verified. Enter your installation, checkpoint location and independent pin.'
        } else {Receive-Managed $response}
    } catch {
        $script:ready=$false; Reset-ManagedReview; Set-ManagedBusy $false
        $script:ui.ConnectionBadge.Text='DISCONNECTED'
        $script:ui.StatusText.Text='Controller connection ended. Preserve checkpoints and any interrupted transaction. Reopen and review status or recovery before retrying.'
        Show-ManagedUncertainty
    }
})
$script:window.Add_Closed({$script:timer.Stop()})
Set-ManagedBusy $false
if(!$BuildOnly) {
    Start-ManagedWorker
    $script:timer.Start()
    [void]$script:window.ShowDialog()
}
