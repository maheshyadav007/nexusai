param(
    [Parameter(Mandatory = $true)][string]$DataDirectory,
    [string]$LogFile
)
# Deletes one NexusAI installation's user data when the user ticks "Also delete my NexusAI data" while
# uninstalling. Only what NexusAI created is removed, the same rule as the app's own Home reset
# (backend/src/nexusai/kernel/home.py, wipe): other files in the Home folder stay. Links are removed,
# never followed. Exit 0 = everything removed; 52 = something was left (the output says what).
$ErrorActionPreference = 'Stop'
$homeFolders = @('system', 'prompts', 'memory', 'documents', 'artifacts', 'scratch')
$siblingDataFolders = @('NexusAI', 'NexusAI Pilot', 'NexusAI CI')
$left = New-Object System.Collections.Generic.List[string]

function Write-Log([string]$Message) {
    if ($LogFile) { Add-Content -LiteralPath $LogFile -Value ((Get-Date -Format o) + ' remove-data: ' + $Message) }
}

function Test-Link([IO.FileSystemInfo]$Item) {
    return [bool]($Item.Attributes -band [IO.FileAttributes]::ReparsePoint)
}

# Directory.Delete removes links inside the tree without following them.
function Remove-Tree([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $item = Get-Item -LiteralPath $Path -Force
    try {
        if (Test-Link $item) { $item.Delete() }
        # No recursive listing here: in Windows PowerShell it can follow links out of the folder.
        elseif ($item.PSIsContainer) { [IO.Directory]::Delete($Path, $true) }
        else { $item.Delete() }
        Write-Log "removed $Path"
    } catch {
        Write-Log "could not remove ${Path}: $($_.Exception.Message)"
        $left.Add($Path)
    }
}

function Get-HomePath([string]$Folder) {
    try { return [string](Get-Content -LiteralPath (Join-Path $Folder 'home-pointer.json') -Raw | ConvertFrom-Json).path }
    catch { return $null }
}

function Test-SamePath([string]$A, [string]$B) {
    if (-not $A -or -not $B) { return $false }
    return [IO.Path]::GetFullPath($A).TrimEnd('\') -ieq [IO.Path]::GetFullPath($B).TrimEnd('\')
}

try {
    $data = [IO.Path]::GetFullPath($DataDirectory).TrimEnd('\')
    $appData = [IO.Path]::GetFullPath($env:APPDATA).TrimEnd('\')
    if ([IO.Path]::GetDirectoryName($data) -ine $appData -or $siblingDataFolders -notcontains [IO.Path]::GetFileName($data)) {
        throw "Refusing to delete ${data}: it is not a NexusAI data folder."
    }
    $others = @($siblingDataFolders | ForEach-Object { Join-Path $appData $_ } | Where-Object { -not (Test-SamePath $_ $data) -and (Test-Path -LiteralPath $_) })

    $homePath = Get-HomePath $data
    if ($homePath -and (Test-Path -LiteralPath (Join-Path $homePath 'home.json'))) {
        $shared = @($others | Where-Object { Test-SamePath (Get-HomePath $_) $homePath })
        if ($shared.Count -gt 0) {
            Write-Log "Home $homePath is also used by $($shared -join ', '); it was kept"
            $left.Add("$homePath (used by another NexusAI installation)")
        } else {
            foreach ($name in $homeFolders) { Remove-Tree (Join-Path $homePath $name) }
            Remove-Tree (Join-Path $homePath 'home.json')
            if ((Test-Path -LiteralPath $homePath) -and @(Get-ChildItem -LiteralPath $homePath -Force).Count -eq 0) { Remove-Tree $homePath }
        }
    }

    # Saved sign-ins live in Windows Credential Manager under the NexusAI service name, which every
    # NexusAI installation shares; they go only when no other installation is left.
    if ($others.Count -eq 0) {
        Add-Type -Namespace NexusAI -Name Credentials -MemberDefinition @'
[DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
public static extern bool CredEnumerate(string filter, int flags, out int count, out IntPtr credentials);
[DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
public static extern bool CredDelete(string target, int type, int flags);
[DllImport("advapi32.dll")]
public static extern void CredFree(IntPtr buffer);
'@
        $targets = New-Object System.Collections.Generic.List[string]
        foreach ($filter in @('NexusAI', '*@NexusAI')) {
            $count = 0; $buffer = [IntPtr]::Zero
            if ([NexusAI.Credentials]::CredEnumerate($filter, 0, [ref]$count, [ref]$buffer)) {
                try {
                    for ($i = 0; $i -lt $count; $i++) {
                        $entry = [Runtime.InteropServices.Marshal]::ReadIntPtr($buffer, $i * [IntPtr]::Size)
                        # CREDENTIAL: Flags (4), Type (4), TargetName (pointer)
                        $type = [Runtime.InteropServices.Marshal]::ReadInt32($entry, 4)
                        $target = [Runtime.InteropServices.Marshal]::PtrToStringUni([Runtime.InteropServices.Marshal]::ReadIntPtr($entry, 8))
                        $targets.Add("$type|$target")
                    }
                } finally { [NexusAI.Credentials]::CredFree($buffer) }
            }
        }
        foreach ($item in ($targets | Select-Object -Unique)) {
            $type, $target = $item -split '\|', 2
            if ([NexusAI.Credentials]::CredDelete($target, [int]$type, 0)) { Write-Log "removed saved sign-in $target" }
            else { Write-Log "could not remove saved sign-in $target"; $left.Add("saved sign-in $target") }
        }
    } else {
        Write-Log "saved sign-ins kept for $($others -join ', ')"
    }

    Remove-Tree $data
} catch {
    Write-Log $_.Exception.Message
    $left.Add($_.Exception.Message)
}

if ($left.Count -gt 0) {
    Write-Output ('Left in place: ' + ($left -join '; '))
    exit 52
}
Write-Output 'NexusAI data removed.'
exit 0
