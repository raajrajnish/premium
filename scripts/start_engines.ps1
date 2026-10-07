# Start (or restart) the premium paper engines U1-U4 and the dashboard, each in its own minimized window.
# Reads only the Nifty system's recorder files; never touches the Nifty system. PAPER ONLY.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\start_engines.ps1
$ErrorActionPreference = "Continue"
$p = Split-Path -Parent $PSScriptRoot
$day = Get-Date -Format yyyy-MM-dd

# close any previous premium engine/dashboard windows (only premium's own scripts)
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'u[1-4]_watch\.py|u1_ui\.py' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

$engines = @(
    @{ title = "premium U1 watch (paper)"; script = "u1_watch.py"; dir = "u1" },
    @{ title = "premium U2 watch (paper)"; script = "u2_watch.py"; dir = "u2" },
    @{ title = "premium U3 watch (paper)"; script = "u3_watch.py"; dir = "u3" },
    @{ title = "premium U4 watch (paper)"; script = "u4_watch.py"; dir = "u4" }
)
foreach ($e in $engines) {
    New-Item -ItemType Directory -Force (Join-Path $p "data\$($e.dir)") | Out-Null
    $cmd = "`$Host.UI.RawUI.WindowTitle='$($e.title)'; `$env:VIRTUAL_ENV=`$null; `$env:PYTHONIOENCODING='utf-8'; " +
           "uv run python scripts/$($e.script) 2>&1 | Tee-Object -Append -FilePath data\$($e.dir)\$($day)_watch.log"
    Start-Process -FilePath "powershell" -WorkingDirectory $p -WindowStyle Minimized -ArgumentList "-NoExit", "-Command", $cmd
}
$ui = "`$Host.UI.RawUI.WindowTitle='premium U1 dashboard'; `$env:VIRTUAL_ENV=`$null; `$env:PYTHONIOENCODING='utf-8'; uv run python scripts/u1_ui.py"
Start-Process -FilePath "powershell" -WorkingDirectory $p -WindowStyle Minimized -ArgumentList "-NoExit", "-Command", $ui
Write-Host "Started U1-U4 watchers and the dashboard (http://127.0.0.1:8760)."
