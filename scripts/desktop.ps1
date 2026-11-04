# Entry point for Windows PowerShell 5.1 and PowerShell 7. Changes no global PATH or policy.
param(
    [Parameter(Position=0)][string]$Action = "menu",
    [string]$Version = "",
    [string]$Profile = "",
    [ValidateSet("pilot", "stable")][string]$Channel = "pilot"
)
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$repo = Split-Path $PSScriptRoot -Parent
$tools = Join-Path $repo ".release\tools"
$pins = Get-Content (Join-Path $repo "desktop\toolchain.json") -Raw | ConvertFrom-Json
$pipelineLock = $null

function Get-VerifiedZip([string]$Url, [string]$Checksums, [string]$Filename, [string]$Destination) {
    New-Item -ItemType Directory -Force $tools | Out-Null
    $zip = Join-Path $tools $Filename
    $sum = Join-Path $tools "$Filename.sha256"
    Write-Host "Downloading $Filename (first setup only)..."
    Invoke-WebRequest -UseBasicParsing -Uri $Checksums -OutFile $sum
    $line = Get-Content $sum | Where-Object { $_ -match [regex]::Escape($Filename) } | Select-Object -First 1
    if (-not $line) { throw "No checksum found for $Filename" }
    $expected = ($line.Trim() -split '\s+')[0]
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $zip
    if ((Get-FileHash $zip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected.ToLowerInvariant()) {
        Remove-Item $zip -Force
        throw "Download checksum failed: $Filename. Retry on a trusted connection."
    }
    Expand-Archive -LiteralPath $zip -DestinationPath $Destination -Force
    Remove-Item $zip, $sum -Force
}

try {
    New-Item -ItemType Directory -Force (Join-Path $repo ".release") | Out-Null
    try {
        $pipelineLock = [IO.File]::Open((Join-Path $repo ".release\desktop.lock"), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    } catch { throw "Another desktop command is already running in this checkout. Wait for it to finish." }
    if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq "ARM64") {
        throw "This pipeline currently supports Windows x64 only."
    }
    $nodeDir = Join-Path $tools "node-v$($pins.node)-win-x64"
    $node = Join-Path $nodeDir "node.exe"
    if (-not (Test-Path $node)) {
        $filename = "node-v$($pins.node)-win-x64.zip"
        Get-VerifiedZip "https://nodejs.org/dist/v$($pins.node)/$filename" "https://nodejs.org/dist/v$($pins.node)/SHASUMS256.txt" $filename $tools
    }
    $uvDir = Join-Path $tools "uv-$($pins.uv)"
    if (-not (Test-Path (Join-Path $uvDir "uv.exe"))) {
        $filename = "uv-x86_64-pc-windows-msvc.zip"
        $base = "https://github.com/astral-sh/uv/releases/download/$($pins.uv)"
        Get-VerifiedZip "$base/$filename" "$base/$filename.sha256" $filename $uvDir
    }
    $env:PATH = "$nodeDir;$uvDir;$env:PATH"
    $env:UV_SYSTEM_CERTS = "true"
    $env:NODE_USE_SYSTEM_CA = "1"
    $env:ELECTRON_BUILDER_CACHE = Join-Path $repo ".release\cache\electron-builder"
    $env:ELECTRON_CACHE = Join-Path $repo ".release\cache\electron"
    $env:electron_config_cache = $env:ELECTRON_CACHE
    if ($env:HTTPS_PROXY -or $env:HTTP_PROXY) { $env:ELECTRON_GET_USE_PROXY = "1" }
    $desktop = Join-Path $repo "desktop"
    Push-Location $desktop
    try {
        # npm ci is deliberately repeatable; cached packages keep subsequent runs quick.
        & (Join-Path $nodeDir "npm.cmd") ci --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw "Desktop tool installation failed. See proxy/download troubleshooting in docs/WINDOWS_RELEASE_GUIDE.md." }
    } finally { Pop-Location }
    $cliArgs = @((Join-Path $desktop "release.cjs"), $Action, "--channel", $Channel)
    if ($Version) { $cliArgs += @("--version", $Version) }
    if ($Profile) { $cliArgs += @("--profile", $Profile) }
    & $node @cliArgs
    if ($LASTEXITCODE -ne 0) { throw "Desktop command failed (exit $LASTEXITCODE)." }
} catch {
    Write-Host "`nNexusAI: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    if ($null -ne $pipelineLock) { $pipelineLock.Dispose() }
}
