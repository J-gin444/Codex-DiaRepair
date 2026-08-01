# Codex Thread Recovery Script
# Run this after closing ALL Codex windows

$target = "$env:USERPROFILE\.codex"
$backup = "D:\projects\DiaRepair\备份\20260727_021839_09b546\state_5.sqlite"

Write-Host "=== Codex Thread Recovery ===" -ForegroundColor Cyan
Write-Host ""

# Check Codex is closed
$codexProcs = Get-Process -Name "Codex*" -ErrorAction SilentlyContinue
if ($codexProcs) {
    Write-Host "ERROR: Codex is still running. Close ALL Codex windows first." -ForegroundColor Red
    Write-Host "Running processes:" -ForegroundColor Yellow
    $codexProcs | Select-Object Name, Id
    pause
    exit 1
}

Write-Host "Codex is closed. Proceeding..." -ForegroundColor Green

# Safety backup of current state
$safetyDir = "$target\recovery-auto-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
New-Item -ItemType Directory -Path $safetyDir -Force | Out-Null
Copy-Item "$target\state_5.sqlite*" $safetyDir -Force -ErrorAction SilentlyContinue
Copy-Item "$target\session_index.jsonl" $safetyDir -Force -ErrorAction SilentlyContinue
Write-Host "Safety backup saved to: $safetyDir" -ForegroundColor Green

# Remove stale WAL/SHM and copy backup
Remove-Item "$target\state_5.sqlite-wal" -Force -ErrorAction SilentlyContinue
Remove-Item "$target\state_5.sqlite-shm" -Force -ErrorAction SilentlyContinue
Copy-Item $backup "$target\state_5.sqlite" -Force
Write-Host "Restored state_5.sqlite from backup" -ForegroundColor Green

# Verify
$count = sqlite3 "$target\state_5.sqlite" "SELECT COUNT(*) FROM threads;"
Write-Host ""
Write-Host "=== Recovery Complete ===" -ForegroundColor Cyan
Write-Host "Threads restored: $count" -ForegroundColor Green
Write-Host ""
Write-Host "You can now reopen Codex." -ForegroundColor White
pause
