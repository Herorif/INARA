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
# Header emblem: the packaged 128 px render, decoded now so the file is not held open. A
# missing or unreadable file leaves the Image empty; Setup still opens.
function Set-SetupEmblem {
    $path = Join-Path $script:controlRoot 'native/setup/emblem-128.png'
    if (!$script:ui.Emblem -or !(Test-Path -LiteralPath $path -PathType Leaf)) {return}
    try {
        $image = New-Object Windows.Media.Imaging.BitmapImage
        $image.BeginInit()
        $image.CacheOption = [Windows.Media.Imaging.BitmapCacheOption]::OnLoad
        $image.UriSource = New-Object Uri ([IO.Path]::GetFullPath($path), [UriKind]::Absolute)
        $image.EndInit()
        $image.Freeze()
        $script:ui.Emblem.Source = $image
    } catch {$script:ui.Emblem.Source = $null}
}
Set-SetupEmblem
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
    $script:ui.ConfirmReview.IsEnabled = !$value -and $null -ne $script:reviewToken -and (!$script:eraseRequired -or $script:ui.EraseConfirmation.Text -ceq 'ERASE JARVIS DATA')
    if ($script:ui.ProvidersPage.Visibility -eq 'Visible') { Update-ProvidersPage }
}
function Set-Page([string]$name) {
    foreach ($taskName in @('HomePage','RecoveryPage','RemovePage','ProvidersPage')) { $script:ui[$taskName].Visibility = $(if ($taskName -eq $name) {'Visible'} else {'Collapsed'}) }
    $script:ui.PageTitle.Text = switch ($name) {'RecoveryPage' {'Keep a way back.'} 'RemovePage' {'Leave on your terms.'} 'ProvidersPage' {'AI providers'} default {'A home for JARVIS.'}}
    $script:ui.PageDescription.Text = switch ($name) {'RecoveryPage' {'Protect your work. Review the path before switching.'} 'RemovePage' {'Software and personal data are separate decisions.'} 'ProvidersPage' {'Add the API keys for Claude and Gemini. You can skip this and add them later.'} default {'Install locally. Choose your version. Keep your work.'}}
    foreach ($taskName in @('NavHome','NavRecovery','NavRemove','NavProviders')) {$script:ui[$taskName].Background='#152837'; $script:ui[$taskName].BorderBrush='#2B485B'}
    $taskNav = switch ($name) {'RecoveryPage' {'NavRecovery'} 'RemovePage' {'NavRemove'} 'ProvidersPage' {'NavProviders'} default {'NavHome'}}
    $script:ui[$taskNav].Background='#145963'; $script:ui[$taskNav].BorderBrush='#43BDBB'
    Reset-Review
    if ($name -eq 'ProvidersPage') { Update-ProvidersPage }
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
    if ($script:secretBusy) { $script:ui.StatusText.Text = 'Wait for the key check to finish.'; return }
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
    $dialog.Description = if ($new) {'Choose a parent folder for a new JARVIS installation.'} else {'Choose an existing managed JARVIS installation.'}
    if ($dialog.ShowDialog() -eq [Windows.Forms.DialogResult]::OK) { $script:ui.RootPath.Text = $(if ($new) {Join-Path $dialog.SelectedPath 'JARVIS Pilot'} else {$dialog.SelectedPath}) }
    $dialog.Dispose()
}
$script:ui.NavHome.Add_Click({Set-Page 'HomePage'}); $script:ui.NavRecovery.Add_Click({Set-Page 'RecoveryPage'}); $script:ui.NavRemove.Add_Click({Set-Page 'RemovePage'})
$script:ui.BrowseRoot.Add_Click({Pick-Folder $false}); $script:ui.NewRoot.Add_Click({Pick-Folder $true})
$script:ui.BrowsePackage.Add_Click({$d=New-Object Windows.Forms.FolderBrowserDialog; $d.ShowNewFolderButton=$false; if ($d.ShowDialog() -eq 'OK') {$script:ui.PackagePath.Text=$d.SelectedPath}; $d.Dispose()})
$script:ui.OpenBackup.Add_Click({$d=New-Object Microsoft.Win32.OpenFileDialog; $d.Filter='JARVIS backups (*.jarvis;*.inara)|*.jarvis;*.inara'; if ($d.ShowDialog($script:window)) {$script:ui.BackupPath.Text=$d.FileName}})
$script:ui.SaveBackup.Add_Click({$d=New-Object Microsoft.Win32.SaveFileDialog; $d.Filter='JARVIS backups (*.jarvis)|*.jarvis'; $d.FileName='jarvis-profile.jarvis'; $d.OverwritePrompt=$true; if ($d.ShowDialog($script:window)) {$script:ui.BackupPath.Text=$d.FileName}})
$script:ui.CheckRoot.Add_Click({Reset-Review; Send-Control @{op='status'; root=$script:ui.RootPath.Text}})
$script:ui.InstallButton.Add_Click({Request-Review $(if ($script:lastStatus -and $script:lastStatus.exists) {'add_version'} else {'install'})})
$script:ui.SelectButton.Add_Click({Request-Review 'select'}); $script:ui.RollbackButton.Add_Click({Request-Review 'rollback'}); $script:ui.LaunchButton.Add_Click({Request-Review 'launch'})
$script:ui.BackupButton.Add_Click({Request-Review 'backup'}); $script:ui.PrepareButton.Add_Click({Request-Review 'prepare_recovery'})
$script:ui.ActivateRecovery.Add_Click({Request-Review 'activate_recovery'}); $script:ui.RollbackRecovery.Add_Click({Request-Review 'rollback_recovery'})
$script:ui.UninstallButton.Add_Click({Request-Review 'uninstall'}); $script:ui.EraseButton.Add_Click({Request-Review 'erase_data'}); $script:ui.ResumeButton.Add_Click({Request-Review 'resume'})
$script:ui.CancelReview.Add_Click({Reset-Review; $script:ui.StatusText.Text='Review cancelled. No change was applied.'})
$script:ui.ConfirmReview.Add_Click({if ($script:reviewToken) {$token=$script:reviewToken; $text=$script:ui.EraseConfirmation.Text; Reset-Review; Send-Control @{op='apply';token=$token;confirmation=$text}}})
$script:ui.EraseConfirmation.Add_TextChanged({$script:ui.ConfirmReview.IsEnabled = !$script:busy -and $null -ne $script:reviewToken -and (!$script:eraseRequired -or $script:ui.EraseConfirmation.Text -ceq 'ERASE JARVIS DATA')})
foreach ($taskName in @('RootPath','PackagePath','BackupPath','PreparedProfile')) { $script:ui[$taskName].Add_TextChanged({Reset-Review; if ($this -eq $script:ui.RootPath) {$script:lastStatus=$null; $script:ui.StatusText.Text='Folder changed. Check it before choosing an installed version.'}}) }
$script:ui.Versions.Add_SelectionChanged({Reset-Review})
$script:ui.OpenWorkspace.Add_Checked({Reset-Review}); $script:ui.OpenWorkspace.Add_Unchecked({Reset-Review})
# AI provider keys: the selected version's own bundled Python runs scripts/jarvis-secrets.py.
# Keys travel only on that child's stdin; they are never placed in arguments, logs or status text.
$script:secretBusy = $false; $script:secretJob = $null; $script:secretQueue = New-Object Collections.Queue; $script:secretTimer = $null
$script:secretFields = @{
    anthropic_api_key = @{box='AnthropicKey'; result='AnthropicResult'}
    gemini_api_key = @{box='GeminiKey'; result='GeminiResult'}
}
function Get-SecretTool {
    $root = $script:ui.RootPath.Text.Trim().TrimEnd('\','/')
    $none = 'Install and select a version first (Installation page, then Check). You can also add keys after installing, from Preferences inside JARVIS.'
    if (!$script:lastStatus -or !$script:lastStatus.exists -or !$script:lastStatus.selected) { return @{ok=$false; reason=$none} }
    $slot = [string]$script:lastStatus.selected
    if ($slot -notmatch '^[a-f0-9]{64}$' -or !$root -or $root.Contains('"')) { return @{ok=$false; reason=$none} }
    $version = Join-Path $root ('versions\' + $slot)
    $tool = @{ok=$true; root=$root; slot=$slot; version=$version; python=(Join-Path $version 'runtime\python\python.exe'); script=(Join-Path $version 'scripts\jarvis-secrets.py')}
    $old = 'This installed version cannot store keys yet. Install a newer version, or add keys later from Preferences inside JARVIS.'
    try {
        $pilot = Join-Path $version 'desktop-pilot.json'
        if (!(Test-Path -LiteralPath $tool.script -PathType Leaf) -or !(Test-Path -LiteralPath $tool.python -PathType Leaf) -or (Get-Item -LiteralPath $pilot).Length -gt 4194304) { return @{ok=$false; reason=$old} }
        # Same drift check Setup applies to its own bootstrap files.
        $versionManifest = Get-Content -LiteralPath $pilot -Raw | ConvertFrom-Json
        foreach ($entry in @(@('runtime/python/python.exe',$tool.python),@('scripts/jarvis-secrets.py',$tool.script))) {
            $record = @($versionManifest.files | Where-Object {$_.path -ceq $entry[0]})
            if ($record.Count -ne 1 -or (Get-FileHash -LiteralPath $entry[1] -Algorithm SHA256).Hash.ToLowerInvariant() -cne $record[0].sha256) { return @{ok=$false; reason='The installed version changed since installation. Check it on the Installation page before adding keys.'} }
        }
    } catch { return @{ok=$false; reason=$old} }
    return $tool
}
function Update-ProviderControls([bool]$available = $true) {
    $enabled = $available -and !$script:busy -and !$script:secretBusy
    foreach ($taskName in @('AnthropicKey','GeminiKey','TestAnthropic','TestGemini','SaveKeys')) { $script:ui[$taskName].IsEnabled = $enabled }
    $script:ui.SkipKeys.IsEnabled = !$script:secretBusy
}
function Update-ProvidersPage {
    $tool = Get-SecretTool
    $script:ui.ProvidersUnavailable.Visibility = $(if ($tool.ok) {'Collapsed'} else {'Visible'})
    $script:ui.ProvidersUnavailableText.Text = $(if ($tool.ok) {''} else {$tool.reason})
    Update-ProviderControls $tool.ok
}
function Set-SecretResult([string]$name, [string]$text, [bool]$good) {
    $target = $script:ui[$script:secretFields[$name].result]
    $target.Text = $text
    $target.Foreground = $(if ($good) {'#6DE5DE'} else {'#F0A5AF'})
}
function Start-SecretQueue {
    if ($script:secretBusy -or $script:secretQueue.Count -eq 0) { return }
    $tool = Get-SecretTool
    if (!$tool.ok) { $script:secretQueue.Clear(); $script:ui.StatusText.Text = $tool.reason; Update-ProvidersPage; return }
    $job = $script:secretQueue.Dequeue()
    $script:secretBusy = $true; $script:ui.Progress.Visibility = 'Visible'; Update-ProviderControls $true
    $script:ui.StatusText.Text = 'Checking the key with its provider. This can take a few seconds.'
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $tool.python
    # Fixed arguments only: the root is a checked local path and the slot a 64-hex id.
    $start.Arguments = '-I -B -X utf8 "' + $tool.script + '" --installation-root "' + $tool.root + '" --slot ' + $tool.slot + ' ' + $job.command + ' ' + $job.name + ' ' + $job.flag
    $start.UseShellExecute=$false; $start.CreateNoWindow=$true; $start.RedirectStandardInput=$true; $start.RedirectStandardOutput=$true; $start.RedirectStandardError=$true
    $start.WorkingDirectory = $tool.version
    foreach ($variable in @('ELECTRON_RUN_AS_NODE','JARVIS_DEV_SERVER','JARVIS_DATA_DIR','INARA_DEV_SERVER','INARA_DATA_DIR','GEMINI_API_KEY','ANTHROPIC_API_KEY','PYTHONPATH','PYTHONHOME')) { $start.EnvironmentVariables.Remove($variable) }
    try {
        $process = [Diagnostics.Process]::Start($start)
        $raw = [Text.Encoding]::UTF8.GetBytes($job.value + "`n")
        $job.value = $null
        $process.StandardInput.BaseStream.Write($raw,0,$raw.Length)
        [Array]::Clear($raw,0,$raw.Length)
        $process.StandardInput.Close()
    } catch {
        $job.value = $null
        $script:secretBusy = $false; $script:ui.Progress.Visibility = 'Collapsed'; Update-ProvidersPage
        Set-SecretResult $job.name 'The key tool could not start. Your keys were not changed.' $false
        return
    }
    $script:secretJob = @{process=$process; job=$job; out=$process.StandardOutput.ReadToEndAsync(); err=$process.StandardError.ReadToEndAsync(); started=[DateTime]::UtcNow}
    if (!$script:secretTimer) {
        $script:secretTimer = New-Object Windows.Threading.DispatcherTimer
        $script:secretTimer.Interval = [TimeSpan]::FromMilliseconds(150)
        $script:secretTimer.Add_Tick({ Complete-SecretJob })
    }
    $script:secretTimer.Start()
}
function Complete-SecretJob {
    $active = $script:secretJob
    if (!$active) { $script:secretTimer.Stop(); return }
    if (!$active.process.HasExited) {
        if (([DateTime]::UtcNow - $active.started).TotalSeconds -lt 60) { return }
        try { $active.process.Kill() } catch {}
        $active.process.WaitForExit(2000) | Out-Null
    }
    $script:secretJob = $null; $script:secretTimer.Stop()
    $job = $active.job
    $reply = $null
    try { $text = $active.out.GetAwaiter().GetResult(); if ($text) { $reply = ($text.Trim() -split "`n")[-1] | ConvertFrom-Json } } catch { $reply = $null }
    if (!$reply) {
        Set-SecretResult $job.name 'The key tool stopped unexpectedly. Your keys were not changed.' $false
    } else {
        Set-SecretResult $job.name ([string]$reply.message) ([bool]$reply.ok)
        if ($reply.saved) { $script:ui[$script:secretFields[$job.name].box].Clear() }
    }
    $active.process.Dispose()
    $script:secretBusy = $false
    if ($script:secretQueue.Count) { Start-SecretQueue; return }
    $script:ui.Progress.Visibility = 'Collapsed'
    $script:ui.StatusText.Text = 'Key check finished.'
    Update-ProvidersPage
}
function Request-Secret([string]$name, [string]$command) {
    if ($script:busy -or $script:secretBusy) { return $false }
    $value = $script:ui[$script:secretFields[$name].box].Password
    if (!$value -or !$value.Trim()) { if ($command -eq 'test') { Set-SecretResult $name 'Enter a key to test.' $false }; return $false }
    $script:secretQueue.Enqueue(@{name=$name; command=$command; flag=$(if ($command -eq 'test') {'--stdin'} else {'--verify'}); value=$value})
    $script:ui[$script:secretFields[$name].result].Text = ''
    return $true
}
$script:ui.NavProviders.Add_Click({Set-Page 'ProvidersPage'})
$script:ui.TestAnthropic.Add_Click({Request-Secret 'anthropic_api_key' 'test' | Out-Null; Start-SecretQueue})
$script:ui.TestGemini.Add_Click({Request-Secret 'gemini_api_key' 'test' | Out-Null; Start-SecretQueue})
$script:ui.SaveKeys.Add_Click({
    if ($script:busy -or $script:secretBusy) { return }
    $queued = @(foreach ($taskName in @('anthropic_api_key','gemini_api_key')) { Request-Secret $taskName 'set' }) -contains $true
    if (!$queued) { $script:ui.StatusText.Text = 'Enter at least one key, or choose Skip for now.'; return }
    Start-SecretQueue
})
$script:ui.SkipKeys.Add_Click({
    if ($script:secretBusy) { return }
    $script:ui.AnthropicKey.Clear(); $script:ui.GeminiKey.Clear()
    Set-Page 'HomePage'
    $script:ui.StatusText.Text = 'No keys were saved. You can add them later from Preferences inside JARVIS.'
})
Set-Page 'HomePage'
$script:ui.PackagePath.Text = $script:controlRoot
$script:ui.RootPath.Text = if ($InstallationRoot) {$InstallationRoot} else {Join-Path $env:LOCALAPPDATA 'JARVIS\Pilot'}
function Start-ControlWorker {
$start = New-Object Diagnostics.ProcessStartInfo
$start.FileName = Join-Path $script:controlRoot 'runtime/python/python.exe'
$start.Arguments = '-I -B -X utf8 "' + (Join-Path $script:controlRoot 'scripts/desktop-control.py') + '"'
$start.UseShellExecute=$false; $start.CreateNoWindow=$true; $start.RedirectStandardInput=$true; $start.RedirectStandardOutput=$true; $start.RedirectStandardError=$true
$start.WorkingDirectory=$script:controlRoot
$start.EnvironmentVariables.Remove('ELECTRON_RUN_AS_NODE'); $start.EnvironmentVariables.Remove('JARVIS_DEV_SERVER'); $start.EnvironmentVariables.Remove('INARA_DEV_SERVER') # pre-rename name, still read as a fallback
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
    if (($script:busy -and $script:currentOp -ne 'boot') -or $script:secretBusy) {$eventArgs.Cancel=$true; $script:ui.StatusText.Text='An operation is running. Wait for its result before closing.'; return}
    $script:timer.Stop()
    if ($script:worker -and !$script:worker.HasExited) {$script:worker.StandardInput.Close(); if (!$script:worker.WaitForExit(500)) {$script:worker.Kill()}}
})
}
if ($BuildOnly) {return}
Start-ControlWorker
$script:window.ShowDialog() | Out-Null
