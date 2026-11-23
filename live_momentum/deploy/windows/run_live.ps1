# Supervisor for the Phase 3 LIVE trader (real orders). Restarts it 10 s after a crash.
# Stops for good on exit 2 (access restricted), 3 (key/account check failed), 4 (orders not enabled).
# LIVE_MOMENTUM_ACK must be set in the user environment by the user, e.g.
#   [Environment]::SetEnvironmentVariable("LIVE_MOMENTUM_ACK", "phase3-live:2026-12-20", "User")
$ErrorActionPreference = "Continue"
$repo = (Resolve-Path "$PSScriptRoot\..\..\..").Path
Set-Location $repo
$env:PYTHONPATH = $repo
if (-not $env:LIVE_MOMENTUM_ACK) { $env:LIVE_MOMENTUM_ACK = [Environment]::GetEnvironmentVariable("LIVE_MOMENTUM_ACK", "User") }
$py = Join-Path $repo ".venv\Scripts\python.exe"
$cfg = "live_momentum\deploy\windows\config.live.toml"
New-Item -ItemType Directory -Force "live_momentum\runtime\live\log" | Out-Null
$sup = "live_momentum\runtime\live\log\supervisor.log"
while ($true) {
    Add-Content $sup "$(Get-Date -Format o) start"
    & $py -m live_momentum.run_live --config $cfg *>> "live_momentum\runtime\live\log\stdout.log"
    $code = $LASTEXITCODE
    Add-Content $sup "$(Get-Date -Format o) exit $code"
    if ($code -in 2, 3, 4) { Add-Content $sup "exit $code`: supervisor stops (see live.log)"; break }
    Start-Sleep -Seconds 10
}
