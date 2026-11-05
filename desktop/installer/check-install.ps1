param(
    [string]$InstallDirectory,
    [string]$AppGuid,
    [string]$Version,
    [int]$InstallerProcessId = 0,
    [ValidateSet('install', 'uninstall', 'services')][string]$Mode = 'install',
    [int]$TimeoutSeconds = 120,
    [string]$LogFile,
    [switch]$FunctionsOnly
)
$ErrorActionPreference = 'Stop'

function Get-InstallPrefix([string]$Directory) {
    $full = [IO.Path]::GetFullPath($Directory).TrimEnd('\', '/')
    if ($full -eq [IO.Path]::GetPathRoot($full).TrimEnd('\', '/')) { throw 'An installation cannot use an entire drive.' }
    return $full + [IO.Path]::DirectorySeparatorChar
}

function Test-InstallProcess($Entry, [string[]]$Directories, [int[]]$ExcludedIds) {
    if ($ExcludedIds -contains [int]$Entry.ProcessId -or -not $Entry.ExecutablePath) { return $false }
    foreach ($directory in $Directories) {
        if ($Entry.ExecutablePath.StartsWith((Get-InstallPrefix $directory), [StringComparison]::OrdinalIgnoreCase)) { return $true }
    }
    return $false
}

function Write-InstallLog([string]$Message) {
    if ($LogFile) { Add-Content -LiteralPath $LogFile -Value ((Get-Date -Format o) + ' ' + $Message) }
    Write-Output $Message
}

if ($FunctionsOnly) { return }
try {
    $null = Get-InstallPrefix $InstallDirectory
    $null = [Guid]::Parse($AppGuid)
    $roots = @($InstallDirectory)
    foreach ($hive in @('HKCU:', 'HKLM:')) {
        $key = Get-ItemProperty -LiteralPath "$hive\Software\$AppGuid" -ErrorAction SilentlyContinue
        if ($key -and $key.InstallLocation) { $roots += $key.InstallLocation }
        if ($Mode -eq 'install') {
            $old = Get-ItemProperty -LiteralPath "$hive\Software\Microsoft\Windows\CurrentVersion\Uninstall\$AppGuid" -ErrorAction SilentlyContinue
            if ($old -and $old.DisplayVersion -and [Version]$old.DisplayVersion -gt [Version]$Version) {
                Write-InstallLog "A newer version ($($old.DisplayVersion)) is installed. Downgrade to $Version was blocked; no files were changed."
                exit 12
            }
        }
    }
    $roots = @($roots | Select-Object -Unique)
    if ($Mode -eq 'services') { $roots = @($roots | ForEach-Object { Join-Path $_ 'resources' }) }
    $excluded = @($InstallerProcessId, $PID)
    $processes = @(Get-CimInstance Win32_Process)
    $installer = $processes | Where-Object { $_.ProcessId -eq $InstallerProcessId } | Select-Object -First 1
    # Older uninstallers also use an unsafe string-prefix match. Do not let them find this installer.
    foreach ($directory in $roots) {
        if ($Mode -ne 'services' -and $installer -and $installer.ExecutablePath -and $installer.ExecutablePath.StartsWith($directory.TrimEnd('\', '/'), [StringComparison]::OrdinalIgnoreCase)) {
            Write-InstallLog 'Move the installer outside the installation folder and any similarly named sibling path, then run it again. No files were changed.'
            exit 13
        }
    }
    $owned = @($processes | Where-Object { Test-InstallProcess $_ $roots $excluded })
    foreach ($entry in $owned) {
        if ($Mode -ne 'services' -and $entry.Name -in @('NexusAI.exe', 'NexusAI Beta.exe', 'NexusAI Pilot.exe', 'NexusAI CI.exe')) {
            # The existing app decides whether work is idle. Never terminate a process here.
            $request = Start-Process -FilePath $entry.ExecutablePath -ArgumentList '--prepare-install' -PassThru
            try { $null = $request.WaitForExit(10000) } finally { $request.Dispose() }
        }
    }
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ($owned.Count -gt 0 -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 250
        $owned = @(Get-CimInstance Win32_Process | Where-Object { Test-InstallProcess $_ $roots $excluded })
    }
    if ($owned.Count -gt 0) {
        foreach ($entry in $owned) { Write-InstallLog "Still running: $($entry.Name), PID $($entry.ProcessId), $($entry.ExecutablePath)" }
        Write-InstallLog 'NexusAI has not finished closing. Finish or pause active work and close it normally, then retry. If only a local service remains, inspect desktop.log. Installation was stopped; no process was killed.'
        exit 10
    }
    Write-InstallLog 'Application and bundled services are stopped. Safe to continue.'
    exit 0
} catch {
    Write-InstallLog ("Could not verify installation safety: " + $_.Exception.Message + '. Installation was stopped; no process was killed.')
    exit 11
}
