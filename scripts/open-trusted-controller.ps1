# Keep this bootstrap independently trusted. A script from an unverified bundle
# cannot establish its own authenticity. Never derive ExpectedManifest from a
# received bundle and treat that as owner approval.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Directory,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{64}$')][string]$ExpectedManifest,
    [Parameter(ValueFromRemainingArguments=$true)][string[]]$ControllerArguments
)
$ErrorActionPreference = 'Stop'
$handles = [System.Collections.Generic.List[System.IO.FileStream]]::new()
function Assert-Local([string]$Path) {
    if ($Path.StartsWith('\\')) { throw 'UNC controller paths are refused' }
    $cursor = $Path
    while ($cursor) {
        # Avoid PowerShell provider/object construction for every ancestor of
        # thousands of runtime files. GetAttributes still checks the link itself.
        if ([IO.File]::GetAttributes($cursor) -band [IO.FileAttributes]::ReparsePoint) {
            throw 'Linked controller path'
        }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
}
function Open-Locked([string]$Path) {
    Assert-Local $Path
    $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    $handles.Add($stream)
    $info = [InaraBootstrap.Native]::Information($stream.SafeFileHandle)
    if ($info.NumberOfLinks -ne 1) { throw 'Shared controller file' }
    return $stream
}
function Hash-Stream([IO.FileStream]$Stream) {
    $Stream.Position = 0
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $digest = ([BitConverter]::ToString($sha.ComputeHash($Stream))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose(); $Stream.Position = 0 }
    return $digest
}
try {
    if (-not ('InaraBootstrap.Native' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
namespace InaraBootstrap {
 [StructLayout(LayoutKind.Sequential)] public struct FileInformation {
  public uint Attributes; public System.Runtime.InteropServices.ComTypes.FILETIME Creation, Access, Write;
  public uint Volume, SizeHigh, SizeLow, NumberOfLinks, IndexHigh, IndexLow;
 }
 public static class Native {
  [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetFileInformationByHandle(
   SafeFileHandle handle, out FileInformation information);
  public static FileInformation Information(SafeFileHandle handle) {
   FileInformation value;
   if (!GetFileInformationByHandle(handle, out value)) throw new Win32Exception(Marshal.GetLastWin32Error());
   return value;
  }
 }
}
'@
    }
    $root = [IO.Path]::GetFullPath($Directory).TrimEnd('\')
    Assert-Local $root
    $manifestStream = Open-Locked (Join-Path $root 'controller-manifest.json')
    if ($manifestStream.Length -gt 8388608 -or (Hash-Stream $manifestStream) -cne $ExpectedManifest) {
        throw 'External controller inventory pin differs'
    }
    $reader = [IO.StreamReader]::new($manifestStream, [Text.Encoding]::UTF8, $true, 4096, $true)
    try { $manifest = $reader.ReadToEnd() | ConvertFrom-Json }
    finally { $reader.Dispose() }
    if ($manifest.format -ne 1 -or $manifest.kind -cne 'inara-trusted-controller' -or
        $manifest.files.Count -lt 1 -or $manifest.files.Count -gt 15000) { throw 'Controller format' }
    $expected = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    [void]$expected.Add('controller-manifest.json')
    $total = [long]0
    foreach ($entry in $manifest.files) {
        $name = [string]$entry.path
        if ($name -cnotmatch '^[A-Za-z0-9_./+@-]+$' -or $name.StartsWith('/') -or
            ($name.Split('/') | Where-Object { $_ -in @('', '.', '..') }) -or
            -not $expected.Add($name) -or $entry.sha256 -cnotmatch '^[a-f0-9]{64}$' -or
            $entry.bytes -lt 0 -or $entry.bytes -gt 536870912) { throw 'Unsafe controller inventory' }
        $stream = Open-Locked (Join-Path $root $name)
        if ($stream.Length -ne $entry.bytes -or (Hash-Stream $stream) -cne $entry.sha256) {
            throw 'Controller bytes differ'
        }
        $total += $stream.Length
        if ($total -gt 2147483648) { throw 'Excessive controller' }
    }
    # Walk directories manually: never recurse through a reparse point first.
    $pending = [Collections.Generic.Stack[string]]::new()
    $pending.Push($root)
    $actual = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    while ($pending.Count) {
        foreach ($item in Get-ChildItem -LiteralPath $pending.Pop() -Force) {
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked controller member' }
            if ($item.PSIsContainer) { $pending.Push($item.FullName) }
            else { [void]$actual.Add($item.FullName.Substring($root.Length + 1).Replace('\', '/')) }
        }
    }
    if (-not $actual.SetEquals($expected) -or -not $expected.Contains('runtime/python.exe') -or
        -not $expected.Contains('scripts/controller.py')) { throw 'Controller file closure differs' }
    if (-not $ControllerArguments.Count) { throw 'Supply an explicit controller command' }
    # File handles deny writes/deletion throughout child lifetime. -I ignores
    # Python env/user imports; the bundled _pth isolates runtime dependencies.
    & (Join-Path $root 'runtime/python.exe') -I -B (Join-Path $root 'scripts/controller.py') @ControllerArguments
    $result = $LASTEXITCODE
}
catch {
    [Console]::Error.WriteLine('Controller bootstrap refused: ' + $_.Exception.Message)
    $result = 1
}
finally { foreach ($stream in $handles) { $stream.Dispose() } }
exit $result
