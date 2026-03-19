# Machete Charts Installer for MSFS 2020/2024
# Run: Right-click > Run with PowerShell
# Or:  powershell -ExecutionPolicy Bypass -File install.ps1

$ErrorActionPreference = "Stop"
$PackageName = "machete-charts"

Write-Host ""
Write-Host "====================================" -ForegroundColor Cyan
Write-Host "  Machete Charts Installer" -ForegroundColor Cyan
Write-Host "  FAA Terminal Procedures for MSFS" -ForegroundColor Cyan
Write-Host "====================================" -ForegroundColor Cyan
Write-Host ""

# ── Locate MSFS Community folder ──
$CommunityPaths = @(
    # MSFS 2024 (MS Store)
    "$env:LOCALAPPDATA\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalCache\Packages\Community"
    # MSFS 2020 (MS Store)
    "$env:LOCALAPPDATA\Packages\Microsoft.FlightSimulator_8wekyb3d8bbwe\LocalCache\Packages\Community"
    # MSFS 2020 (Steam)
    "$env:APPDATA\Microsoft Flight Simulator\Packages\Community"
    # MSFS 2024 (Steam)
    "$env:APPDATA\Microsoft Flight Simulator 2024\Packages\Community"
)

# Also check UserCfg.opt for custom install paths
$UserCfgPaths = @(
    "$env:LOCALAPPDATA\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalCache\UserCfg.opt"
    "$env:LOCALAPPDATA\Packages\Microsoft.FlightSimulator_8wekyb3d8bbwe\LocalCache\UserCfg.opt"
    "$env:APPDATA\Microsoft Flight Simulator\UserCfg.opt"
    "$env:APPDATA\Microsoft Flight Simulator 2024\UserCfg.opt"
)

foreach ($cfg in $UserCfgPaths) {
    if (Test-Path $cfg) {
        $content = Get-Content $cfg -Raw
        if ($content -match 'InstalledPackagesPath\s+"([^"]+)"') {
            $customPath = Join-Path $Matches[1] "Community"
            if ($customPath -notin $CommunityPaths) {
                $CommunityPaths = @($customPath) + $CommunityPaths
            }
        }
    }
}

$found = @()
foreach ($path in $CommunityPaths) {
    if (Test-Path $path) {
        $found += $path
    }
}

if ($found.Count -eq 0) {
    Write-Host "ERROR: Could not find MSFS Community folder." -ForegroundColor Red
    Write-Host ""
    Write-Host "Searched:" -ForegroundColor Yellow
    foreach ($p in $CommunityPaths) {
        Write-Host "  $p" -ForegroundColor Gray
    }
    Write-Host ""
    Write-Host "Please enter your Community folder path manually:"
    $manual = Read-Host
    if (-not (Test-Path $manual)) {
        Write-Host "Path does not exist. Aborting." -ForegroundColor Red
        pause
        exit 1
    }
    $CommunityDir = $manual
} elseif ($found.Count -eq 1) {
    $CommunityDir = $found[0]
    Write-Host "Found Community folder:" -ForegroundColor Green
    Write-Host "  $CommunityDir" -ForegroundColor White
} else {
    Write-Host "Multiple Community folders found:" -ForegroundColor Yellow
    for ($i = 0; $i -lt $found.Count; $i++) {
        Write-Host "  [$($i+1)] $($found[$i])" -ForegroundColor White
    }
    Write-Host ""
    $choice = Read-Host "Select (1-$($found.Count))"
    $idx = [int]$choice - 1
    if ($idx -lt 0 -or $idx -ge $found.Count) {
        Write-Host "Invalid selection. Aborting." -ForegroundColor Red
        pause
        exit 1
    }
    $CommunityDir = $found[$idx]
}

$DestDir = Join-Path $CommunityDir $PackageName

# ── Check for existing installation ──
if (Test-Path $DestDir) {
    Write-Host ""
    Write-Host "Existing installation found. It will be updated." -ForegroundColor Yellow
}

# ── Determine source directory ──
# The package files are in machete-charts/ relative to this script,
# or in the same directory if bundled flat
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SourceDir = Join-Path $ScriptDir "machete-charts"

if (-not (Test-Path (Join-Path $SourceDir "manifest.json"))) {
    # Try parent directory (if script is inside installer/)
    $SourceDir = Join-Path (Split-Path -Parent $ScriptDir) "machete-charts"
}

if (-not (Test-Path (Join-Path $SourceDir "manifest.json"))) {
    Write-Host "ERROR: Cannot find machete-charts package files." -ForegroundColor Red
    Write-Host "Expected manifest.json in: $SourceDir" -ForegroundColor Gray
    pause
    exit 1
}

# ── Install ──
Write-Host ""
Write-Host "Installing to:" -ForegroundColor Green
Write-Host "  $DestDir" -ForegroundColor White
Write-Host ""

try {
    Copy-Item -Path $SourceDir -Destination $DestDir -Recurse -Force
    Write-Host "Installation complete!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Installed files:" -ForegroundColor Gray
    Get-ChildItem -Path $DestDir -Recurse -File | ForEach-Object {
        $rel = $_.FullName.Substring($DestDir.Length + 1)
        Write-Host "  $rel" -ForegroundColor Gray
    }
} catch {
    Write-Host "ERROR: Installation failed." -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    pause
    exit 1
}

Write-Host ""
Write-Host "====================================" -ForegroundColor Cyan
Write-Host "  Machete Charts installed!" -ForegroundColor Green
Write-Host "  Restart MSFS to activate." -ForegroundColor Cyan
Write-Host "====================================" -ForegroundColor Cyan
Write-Host ""
pause
