param([string]$InstallationRoot, [switch]$BuildOnly)
$ErrorActionPreference = 'Stop'
$script:controlRoot = Split-Path -Parent $PSScriptRoot
if (!$BuildOnly) {
# Bootstrap verification protects against accidental drift, not unsigned publisher substitution.
if ((Get-Item -LiteralPath (Join-Path $script:controlRoot 'desktop-pilot.json')).Length -gt 4194304) {throw 'Setup manifest is excessive.'}
$manifest = Get-Content -LiteralPath (Join-Path $script:controlRoot 'desktop-pilot.json') -Raw | ConvertFrom-Json
if ($manifest.kind -ne 'desktop-core-pilot' -or !$manifest.self_contained) {throw 'Run Setup from a bundled core candidate.'}
foreach ($taskName in @('runtime/python/python.exe','scripts/desktop-control.py','scripts/setup-ui.ps1','native/setup/Setup.xaml')) {
    $record = @($manifest.files | Where-Object {$_.path -ceq $taskName})
    if ($record.Count -ne 1 -or (Get-FileHash -LiteralPath (Join-Path $script:controlRoot $taskName) -Algorithm SHA256).Hash.ToLowerInvariant() -cne $record[0].sha256) {throw 'Setup bootstrap integrity failed. Preserve the candidate.'}
}
}
Add-Type -AssemblyName PresentationFramework,PresentationCore,WindowsBase,System.Windows.Forms
$script:controlRoot = Split-Path -Parent $PSScriptRoot
[xml]$taskXaml = Get-Content -LiteralPath (Join-Path $script:controlRoot 'native/setup/Setup.xaml') -Raw -Encoding UTF8
$reader = New-Object System.Xml.XmlNodeReader $taskXaml
$script:window = [Windows.Markup.XamlReader]::Load($reader)
$script:ui = @{}
# Find names without an XML namespace query so the same XAML works in Windows PowerShell 5.1.
foreach ($taskElement in $taskXaml.SelectNodes('//*')) {
    $taskName = $taskElement.GetAttribute('Name','http://schemas.microsoft.com/winfx/2006/xaml')
    if ($taskName) { $script:ui[$taskName] = $script:window.FindName($taskName) }
}
$script:reviewToken = $null; $script:lastStatus = $null; $script:busy = $false; $script:currentOp = $null
$script:worker = $null; $script:readTask = $null; $script:eraseRequired = $false
$script:actionButtons = @('InstallButton','SelectButton','RollbackButton','LaunchButton','BackupButton','PrepareButton','ActivateRecovery','RollbackRecovery','UninstallButton','EraseButton','ResumeButton')
function Reset-Review {
    $script:reviewToken = $null
    $script:ui.ReviewCard.Visibility = 'Collapsed'
    $script:ui.ConfirmReview.IsEnabled = $false
}
function Set-Busy([bool]$value) {
    $script:busy = $value
    $script:ui.Progress.Visibility = $(if ($value) {'Visible'} else {'Collapsed'})
    foreach ($taskName in @('RootPath','PackagePath','BackupPath','PreparedProfile','BrowseRoot','NewRoot','BrowsePackage','OpenBackup','SaveBackup','CheckRoot','Versions','OpenWorkspace','CancelReview')) { $script:ui[$taskName].IsEnabled = !$value }
    foreach ($taskName in $script:actionButtons) { $script:ui[$taskName].IsEnabled = !$value }
    $script:ui.ConfirmReview.IsEnabled = !$value -and $null -ne $script:reviewToken -and (!$script:eraseRequired -or $script:ui.EraseConfirmation.Text -ceq 'ERASE INARA DATA')
}
function Set-Page([string]$name) {
    foreach ($taskName in @('HomePage','RecoveryPage','RemovePage')) { $script:ui[$taskName].Visibility = $(if ($taskName -eq $name) {'Visible'} else {'Collapsed'}) }
    $script:ui.PageTitle.Text = switch ($name) {'RecoveryPage' {'Keep a way back.'} 'RemovePage' {'Leave on your terms.'} default {'A home for INARA.'}}
    $script:ui.PageDescription.Text = switch ($name) {'RecoveryPage' {'Protect your work. Review the path before switching.'} 'RemovePage' {'Software and personal data are separate decisions.'} default {'Install locally. Choose your version. Keep your work.'}}
    foreach ($taskName in @('NavHome','NavRecovery','NavRemove')) {$script:ui[$taskName].Background='#152837'; $script:ui[$taskName].BorderBrush='#2B485B'}
    $taskNav = switch ($name) {'RecoveryPage' {'NavRecovery'} 'RemovePage' {'NavRemove'} default {'NavHome'}}
    $script:ui[$taskNav].Background='#145963'; $script:ui[$taskNav].BorderBrush='#43BDBB'
    Reset-Review
}
function Set-SetupStatus($value) {
    $script:lastStatus = $value
    $items = @()
    foreach ($version in @($value.versions)) {
        $item = New-Object Windows.Controls.ComboBoxItem
        $item.Content = $version.label; $item.Tag = $version.slot
        $items += $item
    }
    $script:ui.Versions.ItemsSource = $items
    if ($items.Count) {
        $selected = @($items | Where-Object { $_.Tag -eq $value.selected })
        $script:ui.Versions.SelectedItem = $(if ($selected.Count) { $selected[0] } else { $items[0] })
    }
    $script:ui.VersionStatus.Text = if ($value.needs_resume) {'Interrupted removal needs your review.'} elseif (!$value.exists) {'Ready for a fresh installation.'} elseif (!$value.selected) {'No version selected.'} else {'Version selected / ' + $value.selected.Substring(0,12)}
    $script:ui.ResumeButton.Visibility = $(if ($value.needs_resume) {'Visible'} else {'Collapsed'})
    $script:ui.StatusText.Text = if ($value.needs_resume) {'Resume the previously approved removal before other changes.'} else {'Local controls ready. Your data stays separate from installed versions.'}
}
function Show-SetupReview($value) {
    $script:reviewToken = $value.token
    $plan = $value.plan
    $script:eraseRequired = [bool]$plan.confirmation_required
    $script:ui.ReviewHeading.Text = $plan.result
    $lines = @('Installation: ' + $plan.installation)
    if ($plan.package) { $lines += 'Package: ' + $plan.package }
    if ($plan.version) { $lines += 'Version: ' + $plan.version }
    if ($plan.destination) { $lines += 'Destination: ' + $plan.destination }
    if ($null -ne $plan.files) { $lines += ('Files: ' + $plan.files + ' / Size: ' + [Math]::Round($plan.bytes / 1MB,1) + ' MiB') }
    $lines += 'Data: ' + $plan.data_policy
    if ($plan.profile) { $lines += 'Prepared profile: ' + $plan.profile }
    if ($plan.owner_fingerprint) { $lines += 'Owner fingerprint: ' + $plan.owner_fingerprint.Substring(0,12) }
    if ($plan.recovery) {
        $r = $plan.recovery
        $lines += 'Destination: ' + $r.destination
        $lines += 'Owner fingerprint: ' + $r.owner_fingerprint.Substring(0,12)
        $lines += ('Memory: ' + $r.counts.memory + ' / Conversations: ' + $r.counts.conversations + ' / Creative jobs: ' + $r.counts.creative_jobs)
        foreach ($project in $r.projects.PSObject.Properties) { $lines += $project.Name + ' / ' + $project.Value }
        $lines += 'Use current Setup controls after recovery activation.'
    }
    if ($plan.installation_format) { $lines += 'Use current Setup controls after recovery activation.' }
    $script:ui.ReviewText.Text = $lines -join [Environment]::NewLine
    $script:ui.EraseConfirmation.Text = ''
    $script:ui.ErasePrompt.Visibility = $(if ($script:eraseRequired) {'Visible'} else {'Collapsed'})
    $script:ui.ReviewCard.Visibility = 'Visible'
    $script:ui.ConfirmReview.Content = $(if ($script:eraseRequired) {'Erase data'} else {'Confirm'})
    $script:ui.ConfirmReview.IsEnabled = !$script:eraseRequired
    $script:ui.StatusText.Text = 'Review the exact change. Nothing has been applied yet.'
    $script:ui.ReviewCard.BringIntoView()
    $script:ui.CancelReview.Focus() | Out-Null
}
function Send-Control($value) {
    if ($script:busy -or !$script:worker -or $script:worker.HasExited) { return }
    $script:currentOp = $value.op
    Set-Busy $true
    $script:ui.StatusText.Text = 'Working locally... please wait for the result before closing.'
    $raw = [Text.Encoding]::UTF8.GetBytes(($value | ConvertTo-Json -Depth 16 -Compress) + "`n")
    $script:worker.StandardInput.BaseStream.Write($raw,0,$raw.Length)
    $script:worker.StandardInput.BaseStream.Flush()
    $script:readTask = $script:worker.StandardOutput.ReadLineAsync()
}
function Request-Review([string]$action) {
    if ($script:busy) { return }
    Reset-Review
    $request = @{ action=$action; root=$script:ui.RootPath.Text }
    if ($action -in @('install','add_version')) { $request.package=$script:ui.PackagePath.Text }
    if ($action -in @('select','backup','prepare_recovery','activate_recovery','rollback_recovery')) {
        if (!$script:ui.Versions.SelectedItem) { $script:ui.StatusText.Text='Select an installed version on the Installation page first.'; return }
        $request.slot=$script:ui.Versions.SelectedItem.Tag
    }
    if ($action -in @('backup','prepare_recovery')) { $request.file=$script:ui.BackupPath.Text }
    if ($action -eq 'activate_recovery') { $request.profile=$script:ui.PreparedProfile.Text }
    if ($action -eq 'launch') { $request.resident_only = !$script:ui.OpenWorkspace.IsChecked }
    Send-Control @{ op='review'; request=$request }
}
function Pick-Folder([bool]$new) {
    $dialog = New-Object Windows.Forms.FolderBrowserDialog
    $dialog.ShowNewFolderButton = $false
    $dialog.Description = if ($new) {'Choose a parent folder for a new INARA installation.'} else {'Choose an existing managed INARA installation.'}
    if ($dialog.ShowDialog() -eq [Windows.Forms.DialogResult]::OK) { $script:ui.RootPath.Text = $(if ($new) {Join-Path $dialog.SelectedPath 'INARA Pilot'} else {$dialog.SelectedPath}) }
    $dialog.Dispose()
}
$script:ui.NavHome.Add_Click({Set-Page 'HomePage'}); $script:ui.NavRecovery.Add_Click({Set-Page 'RecoveryPage'}); $script:ui.NavRemove.Add_Click({Set-Page 'RemovePage'})
$script:ui.BrowseRoot.Add_Click({Pick-Folder $false}); $script:ui.NewRoot.Add_Click({Pick-Folder $true})
$script:ui.BrowsePackage.Add_Click({$d=New-Object Windows.Forms.FolderBrowserDialog; $d.ShowNewFolderButton=$false; if ($d.ShowDialog() -eq 'OK') {$script:ui.PackagePath.Text=$d.SelectedPath}; $d.Dispose()})
$script:ui.OpenBackup.Add_Click({$d=New-Object Microsoft.Win32.OpenFileDialog; $d.Filter='INARA backups (*.inara)|*.inara'; if ($d.ShowDialog($script:window)) {$script:ui.BackupPath.Text=$d.FileName}})
$script:ui.SaveBackup.Add_Click({$d=New-Object Microsoft.Win32.SaveFileDialog; $d.Filter='INARA backups (*.inara)|*.inara'; $d.FileName='inara-profile.inara'; $d.OverwritePrompt=$true; if ($d.ShowDialog($script:window)) {$script:ui.BackupPath.Text=$d.FileName}})
$script:ui.CheckRoot.Add_Click({Reset-Review; Send-Control @{op='status'; root=$script:ui.RootPath.Text}})
$script:ui.InstallButton.Add_Click({Request-Review $(if ($script:lastStatus -and $script:lastStatus.exists) {'add_version'} else {'install'})})
$script:ui.SelectButton.Add_Click({Request-Review 'select'}); $script:ui.RollbackButton.Add_Click({Request-Review 'rollback'}); $script:ui.LaunchButton.Add_Click({Request-Review 'launch'})
$script:ui.BackupButton.Add_Click({Request-Review 'backup'}); $script:ui.PrepareButton.Add_Click({Request-Review 'prepare_recovery'})
$script:ui.ActivateRecovery.Add_Click({Request-Review 'activate_recovery'}); $script:ui.RollbackRecovery.Add_Click({Request-Review 'rollback_recovery'})
$script:ui.UninstallButton.Add_Click({Request-Review 'uninstall'}); $script:ui.EraseButton.Add_Click({Request-Review 'erase_data'}); $script:ui.ResumeButton.Add_Click({Request-Review 'resume'})
$script:ui.CancelReview.Add_Click({Reset-Review; $script:ui.StatusText.Text='Review cancelled. No change was applied.'})
$script:ui.ConfirmReview.Add_Click({if ($script:reviewToken) {$token=$script:reviewToken; $text=$script:ui.EraseConfirmation.Text; Reset-Review; Send-Control @{op='apply';token=$token;confirmation=$text}}})
$script:ui.EraseConfirmation.Add_TextChanged({$script:ui.ConfirmReview.IsEnabled = !$script:busy -and $null -ne $script:reviewToken -and (!$script:eraseRequired -or $script:ui.EraseConfirmation.Text -ceq 'ERASE INARA DATA')})
foreach ($taskName in @('RootPath','PackagePath','BackupPath','PreparedProfile')) { $script:ui[$taskName].Add_TextChanged({Reset-Review; if ($this -eq $script:ui.RootPath) {$script:lastStatus=$null; $script:ui.StatusText.Text='Folder changed. Check it before choosing an installed version.'}}) }
$script:ui.Versions.Add_SelectionChanged({Reset-Review})
$script:ui.OpenWorkspace.Add_Checked({Reset-Review}); $script:ui.OpenWorkspace.Add_Unchecked({Reset-Review})
Set-Page 'HomePage'
$script:ui.PackagePath.Text = $script:controlRoot
$script:ui.RootPath.Text = if ($InstallationRoot) {$InstallationRoot} else {Join-Path $env:LOCALAPPDATA 'INARA\Pilot'}
function Start-ControlWorker {
$start = New-Object Diagnostics.ProcessStartInfo
$start.FileName = Join-Path $script:controlRoot 'runtime/python/python.exe'
$start.Arguments = '-I -B -X utf8 "' + (Join-Path $script:controlRoot 'scripts/desktop-control.py') + '"'
$start.UseShellExecute=$false; $start.CreateNoWindow=$true; $start.RedirectStandardInput=$true; $start.RedirectStandardOutput=$true; $start.RedirectStandardError=$true
$start.WorkingDirectory=$script:controlRoot
$start.EnvironmentVariables.Remove('ELECTRON_RUN_AS_NODE'); $start.EnvironmentVariables.Remove('INARA_DEV_SERVER')
$script:worker = [Diagnostics.Process]::Start($start)
$script:errorTask = $script:worker.StandardError.ReadToEndAsync()
$script:currentOp='boot'; Set-Busy $true
$script:readTask = $script:worker.StandardOutput.ReadLineAsync()
$script:timer = New-Object Windows.Threading.DispatcherTimer
$script:timer.Interval = [TimeSpan]::FromMilliseconds(100)
$script:timer.Add_Tick({
    if (!$script:readTask -or !$script:readTask.IsCompleted) {return}
    $taskReply=$script:readTask; $script:readTask=$null
    try {
        $line=$taskReply.GetAwaiter().GetResult()
        if (!$line) {throw 'The setup worker stopped. Preserve data and check status before retrying.'}
        $reply=$line | ConvertFrom-Json
        Set-Busy $false
        if ($script:currentOp -eq 'boot') {if (!$reply.ready) {throw 'Local controls did not initialize.'}; $script:ui.StatusText.Text='Controls verified. Choose an installation folder and check its status.'}
        elseif (!$reply.ok) {$script:ui.StatusText.Text=$reply.error; Reset-Review}
        elseif ($script:currentOp -eq 'status') {Set-SetupStatus $reply.result; if ($script:completionNotice) {$script:ui.StatusText.Text=$script:completionNotice; $script:completionNotice=$null}}
        elseif ($script:currentOp -eq 'review') {Show-SetupReview $reply.result}
        else {
            if ($reply.result.profile -and $reply.result.prepared) {$script:ui.PreparedProfile.Text=$reply.result.profile}
            $script:ui.StatusText.Text=if ($reply.result.launch_requested) {$reply.result.message} elseif ($reply.result.removed -eq 'data') {'Owned profiles erased. External encrypted backups were kept.'} elseif ($reply.result.removed -eq 'software') {'Software removed. Your profiles and recovery copies were kept.'} elseif ($reply.result.prepared) {'Recovery copy prepared. Review its activation when ready.'} else {'Change completed. Check the installation status before your next action.'}
            $script:lastStatus=$null
            if (!$reply.result.launch_requested) {$script:completionNotice=$script:ui.StatusText.Text; Send-Control @{op='status';root=$script:ui.RootPath.Text}}
        }
    } catch {Set-Busy $false; Reset-Review; $script:ui.StatusText.Text=$_.Exception.Message; foreach ($taskName in $script:actionButtons) {$script:ui[$taskName].IsEnabled=$false}; $script:ui.CheckRoot.IsEnabled=$false}
})
$script:timer.Start()
$script:window.Add_Closing({ param($sender,$eventArgs)
    if ($script:busy -and $script:currentOp -ne 'boot') {$eventArgs.Cancel=$true; $script:ui.StatusText.Text='An operation is running. Wait for its result before closing.'; return}
    $script:timer.Stop()
    if ($script:worker -and !$script:worker.HasExited) {$script:worker.StandardInput.Close(); if (!$script:worker.WaitForExit(500)) {$script:worker.Kill()}}
})
}
if ($BuildOnly) {return}
Start-ControlWorker
$script:window.ShowDialog() | Out-Null
