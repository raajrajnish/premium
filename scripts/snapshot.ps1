# Copy suzlon's market database into premium (run AFTER suzlon's End of Day has finished).
# premium only ever reads its own copy, so it can never lock or corrupt the original. Read-only for suzlon.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$src = Join-Path (Split-Path -Parent $root) "suzlon\data\market.duckdb"
$dst = Join-Path $root "data\market.duckdb"
if (-not (Test-Path $src)) { Write-Host "Source not found: $src" -ForegroundColor Red; exit 1 }
# Refuse while suzlon is still writing (End of Day download running): DuckDB keeps a .wal file while a writer is open.
if (Test-Path "$src.wal") {
    Write-Host "suzlon's database is still being written (End of Day running?). Try again when it finishes." -ForegroundColor Yellow
    exit 2
}
New-Item -ItemType Directory -Force (Split-Path -Parent $dst) | Out-Null
$tmp = "$dst.tmp"
Copy-Item $src $tmp -Force
Move-Item $tmp $dst -Force
$gb = [math]::Round((Get-Item $dst).Length / 1GB, 2)
Write-Host "Snapshot updated: $dst ($gb GB, $(Get-Date -Format 'yyyy-MM-dd HH:mm'))" -ForegroundColor Green
