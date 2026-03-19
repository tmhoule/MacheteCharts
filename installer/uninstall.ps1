# Machete Charts Uninstaller for MSFS
# Run: Right-click > Run with PowerShell

$ErrorActionPreference = "Stop"
$PackageName = "machete-charts"

Write-Host ""
Write-Host "Machete Charts Uninstaller" -ForegroundColor Cyan
Write-Host ""

# Search all possible locations
$CommunityPaths = @(
    "$env:LOCALAPPDATA\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalCache\Packages\Community"
    "$env:LOCALAPPDATA\Packages\Microsoft.FlightSimulator_8wekyb3d8bbwe\LocalCache\Packages\Community"
    "$env:APPDATA\Microsoft Flight Simulator\Packages\Community"
    "$env:APPDATA\Microsoft Flight Simulator 2024\Packages\Community"
)

$removed = 0
foreach ($path in $CommunityPaths) {
    $target = Join-Path $path $PackageName
    if (Test-Path $target) {
        Write-Host "Removing: $target" -ForegroundColor Yellow
        Remove-Item -Path $target -Recurse -Force
        Write-Host "  Removed." -ForegroundColor Green
        $removed++
    }
}

if ($removed -eq 0) {
    Write-Host "Machete Charts was not found in any Community folder." -ForegroundColor Gray
} else {
    Write-Host ""
    Write-Host "Machete Charts has been uninstalled." -ForegroundColor Green
    Write-Host "Restart MSFS to complete removal." -ForegroundColor Cyan
}

Write-Host ""
pause
