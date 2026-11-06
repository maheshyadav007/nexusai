$ErrorActionPreference = 'Stop'
# A PowerShell syntax error makes a script do nothing at all, so every installer script must parse.
foreach ($script in Get-ChildItem "$PSScriptRoot\..\installer\*.ps1") {
    $errors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseFile($script.FullName, [ref]$null, [ref]$errors)
    if ($errors.Count -gt 0) { throw "$($script.Name) does not parse: $($errors | ForEach-Object { "line $($_.Extent.StartLineNumber): $($_.Message)" })" }
}
. "$PSScriptRoot\..\installer\check-install.ps1" -FunctionsOnly
$root = 'C:\Apps\NexusAI Beta'
$entry = [PSCustomObject]@{ ProcessId = 42; ExecutablePath = 'C:\Apps\NexusAI Beta\resources\python\python.exe' }
if (-not (Test-InstallProcess $entry @($root) @())) { throw 'Bundled Python must be detected.' }
if (Test-InstallProcess $entry @($root) @(42)) { throw 'The installer itself must be excluded.' }
$entry.ExecutablePath = 'C:\Apps\NexusAI Beta-Setup-0.1.0.exe'
if (Test-InstallProcess $entry @($root) @()) { throw 'Sibling prefix must not match.' }
$entry.ExecutablePath = 'C:\Other\python.exe'
if (Test-InstallProcess $entry @($root) @()) { throw 'Unrelated Python must not match.' }
$entry.ExecutablePath = 'c:\APPS\NEXUSAI BETA\node.exe'
if (-not (Test-InstallProcess $entry @($root + '\') @())) { throw 'Windows path matching must be case insensitive and normalize trailing separators.' }
Write-Host 'Installer process-boundary/exclusion checks passed.'
